"""The engine's place queries: paging through Qloo's 50-result pages, and leaving out places Qloo marks closed."""
import asyncio

from app import engine


def place(index: int, closed: bool = False) -> dict:
    return {"entity_id": f"p{index}", "name": f"Place {index}", "properties": {"is_closed": closed}}


class PagedQloo:
    """Answers place queries from a fixed list, 50 at a time, like Qloo's insights."""

    def __init__(self, places: list[dict]) -> None:
        self.places = places
        self.offsets: list[int] = []

    async def insights(self, params: dict) -> dict:
        offset = params.get("offset", 0)
        self.offsets.append(offset)
        return {"results": {"entities": self.places[offset:offset + params["take"]]}}


def test_closed_places_are_left_out_after_paging_so_paging_still_reaches_every_page():
    # The first page is full but holds a closed place; dropping it before paging would stop at one page.
    places = [place(i, closed=i == 3) for i in range(70)]
    q = PagedQloo(places)
    found = asyncio.run(engine.places_upto(q, {"filter.location": "x"}, "urn:tag:genre:place:bar", limit=100))
    assert q.offsets == [0, 50]
    assert len(found) == 69 and "p3" not in {p["entity_id"] for p in found}


def test_a_single_page_query_drops_closed_places_unless_asked_to_keep_them():
    q = PagedQloo([place(1), place(2, closed=True)])
    assert [p["entity_id"] for p in asyncio.run(engine.places_in(q, {}))] == ["p1"]
    assert [p["entity_id"] for p in asyncio.run(engine.places_in(q, {}, include_closed=True))] == ["p1", "p2"]


def test_favorites_located_far_outside_the_search_area_are_dropped():
    # Zamalek's search area is 15 km; a place placed in Austin, Texas is a data error, not a trip people make.
    here = {"entity_id": "a", "name": "Near", "location": {"lat": 30.07, "lon": 31.23}}
    austin = {"entity_id": "b", "name": "Far", "location": {"lat": 30.2622, "lon": -97.7247}}
    unknown = {"entity_id": "c", "name": "Nowhere"}
    kept = engine.near([here, austin, unknown], 30.0626, 31.2197)
    assert [p["entity_id"] for p in kept] == ["a", "c"]
