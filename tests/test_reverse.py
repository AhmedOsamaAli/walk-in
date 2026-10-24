"""The address of a pin dropped on the map (GET /api/reverse): the street address and the part of town, from
OpenStreetMap Nominatim, asked in English, cached and throttled like the address search."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.geocode import Geocoder, address_of
from tests.account_fakes import configure, make_client

WILLIAMSBURG = {
    "display_name": "131, South 2nd Street, Williamsburg, Brooklyn, Kings County, New York, 11249, United States",
    "address": {"house_number": "131", "road": "South 2nd Street", "quarter": "Williamsburg", "suburb": "Brooklyn",
                "city_district": "Kings County", "city": "New York", "postcode": "11249", "country": "United States"},
}


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    return configure(monkeypatch)


def test_the_label_is_the_street_address_and_the_two_smallest_parts_of_town():
    assert address_of(WILLIAMSBURG) == {
        "label": "131 South 2nd Street, Williamsburg, Brooklyn", "address": WILLIAMSBURG["display_name"],
    }
    zamalek = {"display_name": "17, Shagarat Al Dur Street, Mohamed Mazhar, Zamalek, Cairo, 11568, Egypt",
               "address": {"house_number": "17", "road": "Shagarat Al Dur Street", "neighbourhood": "Mohamed Mazhar",
                           "suburb": "Zamalek", "state": "Cairo"}}
    assert address_of(zamalek)["label"] == "17 Shagarat Al Dur Street, Mohamed Mazhar, Zamalek"
    austin = {"display_name": "East 6th Street, East Cesar Chavez, Austin, Travis County, Texas, United States",
              "address": {"road": "East 6th Street", "neighbourhood": "East Cesar Chavez", "city": "Austin",
                          "county": "Travis County"}}
    assert address_of(austin)["label"] == "East 6th Street, East Cesar Chavez, Austin"
    # Without a street, the first two parts of the full line.
    park = {"display_name": "McCarren Park, Greenpoint, Brooklyn, New York", "address": {"leisure": "McCarren Park"}}
    assert address_of(park)["label"] == "McCarren Park, Greenpoint"
    assert address_of({"error": "Unable to geocode"}) is None
    assert address_of({}) is None


def test_the_lookup_asks_nominatim_in_english_and_keeps_the_answer():
    asked: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json=WILLIAMSBURG)

    async def scenario() -> tuple[dict | None, dict | None]:
        geocoder = Geocoder(httpx.AsyncClient(base_url="https://nominatim.test", transport=httpx.MockTransport(answer)))
        try:
            return await geocoder.reverse(40.713501, -73.962499), await geocoder.reverse(40.7135012, -73.9624988)
        finally:
            await geocoder.aclose()

    first, again = asyncio.run(scenario())
    assert first == again == address_of(WILLIAMSBURG)
    assert len(asked) == 1  # the same point, to a metre, is read from the cache
    params = asked[0].url.params
    assert asked[0].url.path == "/reverse" and params["zoom"] == "18" and params["format"] == "jsonv2"
    assert asked[0].headers["Accept-Language"] == "en"


class Answers:
    def __init__(self, found: dict | None = None, fail: bool = False) -> None:
        self.found, self.fail = found, fail

    async def reverse(self, lat: float, lon: float) -> dict | None:
        if self.fail:
            raise httpx.ConnectError("down")
        return self.found

    async def aclose(self) -> None:
        pass


def test_the_route_gives_the_address_or_says_why_not():
    with make_client() as client:
        services = client.app.state.services
        assert client.get("/api/reverse", params={"lat": 40.7135, "lon": -73.9625}).json() == {
            "label": "1 Test Street, Testville", "address": "1, Test Street, Testville, Testland",
        }
        services.geocoder = Answers(found=None)
        assert client.get("/api/reverse", params={"lat": 0, "lon": 0}).status_code == 404
        services.geocoder = Answers(fail=True)
        response = client.get("/api/reverse", params={"lat": 40.7, "lon": -73.9})
        assert response.status_code == 502 and "unavailable" in response.json()["detail"]
        assert client.get("/api/reverse", params={"lat": 91, "lon": 0}).status_code == 422
