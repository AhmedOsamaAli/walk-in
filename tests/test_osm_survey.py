"""The OpenStreetMap cross-check inside a survey: OpenStreetMap is read alongside Qloo, the places only it shows inside the
walk count as supply, the evidence names them, and a survey whose cross-check fails goes on and says so."""
from __future__ import annotations

import asyncio
import json

import pytest

from app import osm, schemas, scoring
from app.llm import LLM
from app.survey import launch, pipeline, snapshot
from app.survey.concepts import one_liner
from app.survey.evidence import (
    competition,
    gap_evidence,
    gap_reading,
    gap_summary,
    price_evidence,
    public_gap,
    risk,
)
from app.survey.models import RunStore, Site
from tests.fakes import OSM_AS_OF, SITE, FakeOsm, FakeQloo, FakeWalker, offset, place


async def survey(osm_client=None, qloo: FakeQloo | None = None, **brief) -> tuple[object, list[tuple[str, dict]], FakeQloo]:
    events: list[tuple[str, dict]] = []
    q = qloo or FakeQloo()

    async def emit(event: str, data: dict) -> None:
        events.append((event, json.loads(json.dumps(data))))

    run = await pipeline.analyze_site(
        q, FakeWalker(), LLM("", None, "test-model"), RunStore(), Site(*SITE, "Test Corner, Testville", **brief), emit,
        osm_client=osm_client,
    )
    return run, events, q


def rows_of(events: list[tuple[str, dict]]) -> dict[str, dict]:
    rows = next(data for event, data in events if event == "gaps")["rows"]
    return {row["genre"]: row for row in rows}


def osm_steps(events: list[tuple[str, dict]]) -> list[tuple[str, str]]:
    return [(data["state"], data["label"]) for event, data in events if event == "status" and data["step"] == "osm"]


def test_a_survey_counts_the_places_only_openstreetmap_shows_inside_the_walk():
    _, plain, _ = asyncio.run(survey())
    run, events, q = asyncio.run(survey(FakeOsm()))
    assert osm_steps(events) == [("running", osm.LABEL), ("done", osm.LABEL)]
    assert not any(event == "notice" for event, _ in events)
    before, after = rows_of(plain), rows_of(events)

    bakery = after["Bakery"]
    # Qloo lists 4 bakeries; OpenStreetMap shows them, a place Qloo lists as a coffee shop that it tags a bakery, and two
    # more Qloo does not list. A bakery beyond the walk is no part of it.
    assert bakery["nearby_count"] == 4 and bakery["osm"]["checked"] and bakery["osm"]["count"] == 4
    assert bakery["osm"]["as_of"] == OSM_AS_OF and bakery["osm"]["credit"] == "© OpenStreetMap contributors"
    extra = bakery["osm"]["extra"]
    assert [p["name"] for p in extra] == ["Crumb & Co", "Sunrise Pastry"]  # nearest first
    assert extra[0] == {
        "name": "Crumb & Co", "lat": pytest.approx(offset(250, 120)[0]), "lon": pytest.approx(offset(250, 120)[1]),
        "url": "https://www.openstreetmap.org/node/103", "tag": "shop=bakery", "distance_m": 250,
    }
    # Six bakeries where a block this dense holds about four: no longer a typical supply, and scored lower.
    assert before["Bakery"]["reading"] == "Steady demand" and bakery["reading"] == "Crowded"
    assert bakery["relative_supply"] > before["Bakery"]["relative_supply"]
    assert bakery["gap_score"] < before["Bakery"]["gap_score"]
    assert bakery["expected_nearby"] == before["Bakery"]["expected_nearby"]
    assert bakery["why"][1:3] == [
        "6 bakeries inside the 10-minute walk (4 on Qloo, 2 more on OpenStreetMap), more than the about 4 a block this "
        "dense usually has.",
        "OpenStreetMap shows 2 more bakeries inside the walk that Qloo doesn't list: Crumb & Co and Sunrise Pastry.",
    ]
    # The price claim rests on Qloo's price levels: it stands, with a caution.
    assert bakery["price"]["basis"] == (
        "The bakeries people here love are $$ (median of 10); the 4 inside the walk are $$. Prices are Qloo's: "
        "OpenStreetMap shows 2 more bakeries inside the walk that Qloo doesn't list, and their prices are not known."
    )

    seafood = after["Seafood"]
    assert [p["name"] for p in seafood["osm"]["extra"]] == ["Saltmarsh Fish Bar"]
    assert seafood["reading"] == "Clear gap"
    assert seafood["why"][1] == ("Only 2 seafood places inside the 10-minute walk (1 on Qloo, 1 more on OpenStreetMap), "
                                 "where a block this dense usually has about 4.7.")
    # Other categories keep their supply: the site's baseline is Qloo's own.
    assert after["Brunch"]["relative_supply"] == before["Brunch"]["relative_supply"]
    assert after["Brunch"]["osm"] == {"checked": True, "count": 0, "extra": [], "as_of": OSM_AS_OF,
                                      "credit": "© OpenStreetMap contributors"}
    # A ramen shop is a Japanese restaurant.
    assert [p["name"] for p in after["Japanese"]["osm"]["extra"]] == ["Kumo Ramen"]
    # Every place only OpenStreetMap seems to show was looked up by name on Qloo before being called missing from it.
    searched = sorted(r["query"] for r in q.requests if r.get("path") == "/search")
    assert searched == ["Crumb & Co", "Kumo Ramen", "Saltmarsh Fish Bar", "Sunrise Pastry"]
    # Rows are typed for the API, and the run saves and restores with its cross-check.
    for row in rows_of(events).values():
        assert schemas.GapRow.model_validate(row).osm is not None
    restored = snapshot.load_run(json.loads(json.dumps(snapshot.dump_run(run))))
    assert public_gap(restored.gaps[0])["osm"] == public_gap(run.gaps[0])["osm"]


class QlooListingSunrise(FakeQloo):
    """Qloo knows Sunrise Pastry, as a dessert shop next to where OpenStreetMap has it; only a name search finds it."""

    async def search(self, params: dict) -> dict:
        await super().search(params)
        if params.get("query") == "Sunrise Pastry":
            return {"results": [place("Sunrise Pastry Shop", "Dessert shop", *offset(430, 300))]}
        return {"results": []}


def test_a_place_qloo_lists_under_another_kind_is_not_called_missing_from_qloo():
    _, events, _ = asyncio.run(survey(FakeOsm(), qloo=QlooListingSunrise()))
    bakery = rows_of(events)["Bakery"]
    assert [p["name"] for p in bakery["osm"]["extra"]] == ["Crumb & Co"]
    assert "OpenStreetMap shows 1 more bakery inside the walk that Qloo doesn't list: Crumb & Co." in bakery["why"]


def test_when_openstreetmap_does_not_answer_the_survey_goes_on_and_says_so():
    _, events, q = asyncio.run(survey(FakeOsm(fail=True)))
    assert osm_steps(events) == [("running", osm.LABEL), ("failed", osm.LABEL)]
    assert [data["message"] for event, data in events if event == "notice"] == [pipeline.OSM_FAILED]
    assert "error" not in [event for event, _ in events] and [event for event, _ in events][-1] == "done"
    rows = rows_of(events)
    assert all(row["osm"]["reason"] == "unavailable" and not row["osm"]["checked"] for row in rows.values())
    # The rows are scored on Qloo's places alone, and a count that says a kind is short says it was not checked.
    seafood = rows["Seafood"]
    assert seafood["why"][-1] == "Not cross-checked: OpenStreetMap did not answer in time, so this count is Qloo's alone."
    assert not any("Not cross-checked" in line for line in rows["Brunch"]["why"])
    assert not any(r.get("path") == "/search" for r in q.requests)


def test_without_an_openstreetmap_client_rows_say_the_cross_check_is_off():
    _, events, _ = asyncio.run(survey())
    assert osm_steps(events) == []
    rows = rows_of(events)
    assert all(row["osm"] == osm.unchecked("off") for row in rows.values())
    assert not any("OpenStreetMap" in line for row in rows.values() for line in row["why"])


def test_the_app_cross_checks_its_surveys_with_its_openstreetmap_service():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.test_e2e import RUN_PARAMS, make_services, sse_events

    services = make_services()
    services.osm = FakeOsm()
    with TestClient(create_app(lambda: services)) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
    assert osm_steps(events) == [("running", osm.LABEL), ("done", osm.LABEL)] and services.osm.scans == 1
    bakery = rows_of(events)["Bakery"]
    assert [p["name"] for p in bakery["osm"]["extra"]] == ["Crumb & Co", "Sunrise Pastry"]
    assert events[-1][0] == "done"


def test_categories_measured_later_are_cross_checked_too():
    # The owner asks for ramen, outside the gap table: it is measured live, with the survey's OpenStreetMap places.
    _, events, _ = asyncio.run(survey(FakeOsm(), intent="open", business="ramen"))
    verdict = next(data for event, data in events if event == "verdict")
    row = verdict["row"]
    assert row["nearby_count"] == 0 and [p["name"] for p in row["osm"]["extra"]] == ["Kumo Ramen"]
    assert "OpenStreetMap shows 1 ramen place inside the walk that Qloo doesn't list: Kumo Ramen." in verdict["evidence"]
    # A kind no tag pins down is measured as before and says it was not checked.
    _, events, _ = asyncio.run(survey(FakeOsm(), intent="open", business="board game cafe"))
    row = next(data for event, data in events if event == "verdict")["row"]
    assert row["osm"]["reason"] == "unmapped"


# ---------- Scoring and evidence, row by row ----------

def row_with(nearby: int, extra: list[str], around: int = 12, genre: str = "Bakery", **over) -> dict:
    row = {
        "genre_id": "urn:tag:genre:place:restaurant:bakery", "genre": genre, "demand_rank": 4, "ref_rank": 9.0,
        "nearby_count": nearby, "nearby_capped": False, "around_count": around, "around_capped": False,
        "favorites_kind": "local", "favorites_total": 5, "favorites_far": 4, "median_favorite_km": 2.0,
        "median_far_km": 2.3, "storefront_share": 1.0,
        "osm": {"checked": True, "count": nearby + len(extra), "as_of": None,
                "extra": [{"name": name, "lat": 0.0, "lon": 0.0, "url": f"https://www.openstreetmap.org/node/{i}",
                           "distance_m": 100 * (i + 1)} for i, name in enumerate(extra)]},
        "competitors": [], "favorites": [], "_favorite_entities": [], "_nearby_entities": [],
    }
    return row | over


def score(*rows: dict) -> list[dict]:
    return scoring.score_gaps(list(rows), catchment_area_m2=1.0, around_area_m2=4.0)


def test_extras_count_as_supply_on_the_sites_own_baseline():
    plain = {r["genre"]: r for r in score(row_with(0, [], genre="A"), row_with(3, [], genre="B"), row_with(3, [], genre="C"))}
    checked = {r["genre"]: r for r in score(row_with(0, ["X", "Y"], genre="A"), row_with(3, [], genre="B"),
                                            row_with(3, [], genre="C"))}
    assert scoring.supply_count(checked["A"]) == 2 and checked["A"]["nearby_count"] == 0
    assert checked["A"]["relative_supply"] > plain["A"]["relative_supply"]
    assert checked["A"]["gap_score"] < plain["A"]["gap_score"]
    assert checked["A"]["expected_nearby"] == plain["A"]["expected_nearby"]
    assert checked["B"]["relative_supply"] == plain["B"]["relative_supply"]  # the baseline is Qloo's


def test_the_evidence_names_the_extras_plainly():
    row = score(row_with(0, ["Joe's Bakery & Coffee Shop", "Insomnia Cookies"]))[0]
    lines = gap_evidence(row)
    assert "OpenStreetMap shows 2 bakeries inside the walk that Qloo doesn't list: Joe's Bakery & Coffee Shop and "\
           "Insomnia Cookies." in lines
    assert lines[1].startswith("2 bakeries inside the 10-minute walk (none on Qloo, 2 on OpenStreetMap)")
    row = score(row_with(1, ["Joe's Bakery & Coffee Shop", "Insomnia Cookies"]))[0]
    assert ("OpenStreetMap shows 2 more bakeries inside the walk that Qloo doesn't list: Joe's Bakery & Coffee Shop and "
            "Insomnia Cookies.") in gap_evidence(row)
    many = score(row_with(1, [f"Bakery {i}" for i in range(6)]))[0]
    assert gap_evidence(many)[2].endswith(": Bakery 0, Bakery 1, Bakery 2, Bakery 3 and 2 more.")
    # The agent sees both counts, and that nothing is known of the extras but their names.
    summary = gap_summary(row)
    assert summary["places_within_walk"] == "3"
    assert summary["openstreetmap_cross_check"].startswith("the places within the walk are 1 Qloo lists and 2 only "
                                                           "OpenStreetMap shows (Joe's Bakery & Coffee Shop and Insomnia Cookies)")


def test_competition_and_risk_count_both_maps():
    row = score(row_with(0, ["Crumb & Co"]))[0]
    assert competition(row, 10) == ("No bakery Qloo lists competes inside the 10-minute walk, but OpenStreetMap shows 1 "
                                    "bakery there: Crumb & Co.")
    crowded = score(row_with(4, [f"Extra {i}" for i in range(5)], around=8))[0]
    assert risk(crowded, 10).startswith("9 bakeries are already inside the walk, more than the block's density predicts")


def test_a_count_that_says_a_kind_is_short_says_when_it_was_not_cross_checked():
    others = (row_with(6, [], genre="Bakery"), row_with(6, [], genre="Cafe"))
    scored = score(row_with(0, [], genre="New American", favorites_kind="citywide") | {"osm": osm.unchecked("unmapped")},
                   *others)
    unmapped = next(row for row in scored if row["genre"] == "New American")
    assert unmapped["relative_supply"] < 0.75
    assert gap_evidence(unmapped)[-1] == ("Not cross-checked: no OpenStreetMap tag reliably marks New American places, so "
                                         "this count is Qloo's alone.")
    assert gap_summary(unmapped)["openstreetmap_cross_check"].startswith("Not cross-checked")
    scored = score(row_with(0, [], genre="Wine Bar", favorites_kind="citywide") | {"osm": osm.unchecked("off")}, *others)
    off = next(row for row in scored if row["genre"] == "Wine Bar")
    assert off["relative_supply"] < 0.75 and not any("cross-checked" in line for line in gap_evidence(off))


def test_price_claims_resting_on_qloo_get_a_caution_only_when_openstreetmap_adds_places():
    priced = [place(f"Priced {i}", "Bakery", *offset(100, 10 * i), i) for i in range(3)]
    row = row_with(3, ["Crumb & Co"], _nearby_entities=priced)
    assert price_evidence(row)["caution"] == ("Prices are Qloo's: OpenStreetMap shows 1 more bakery inside the walk that "
                                              "Qloo doesn't list, and its price is not known.")
    assert price_evidence(row)["basis"].endswith(price_evidence(row)["caution"])
    assert "caution" not in price_evidence(row_with(3, [], _nearby_entities=priced))
    # Without priced places inside the walk there is no claim about them to caution.
    assert "caution" not in price_evidence(row_with(0, ["Crumb & Co"]))


def test_the_travel_badge_says_people_here():
    travel = score(row_with(6, [], around=12) | {"favorites_far": 5, "favorites_total": 5})[0]
    assert gap_reading(travel) == "People here travel for it"


def test_launch_claims_resting_on_qloo_say_when_openstreetmap_shows_more_places():
    from tests.test_launch import CONCEPT, gap_row
    from tests.test_launch import survey as launch_survey

    row = gap_row()
    row["osm"] = row_with(2, ["Crumb & Co", "Sunrise Pastry"])["osm"]
    claims = {c["kind"]: c for c in launch.claims(launch_survey(), CONCEPT, row)}
    assert claims["only"]["line"] == "The only $$$ bakery within a 10-minute walk"  # the claim stays as stated
    assert claims["only"]["proof"] == (
        "None of the 2 bakeries inside the walk that list a price is $$$; 2 of the bakeries locals love are. Prices are "
        "Qloo's: OpenStreetMap shows 2 more bakeries inside the walk that Qloo doesn't list, and their prices are not known."
    )
    assert claims["new"]["proof"].endswith(
        "Reviews are Qloo's: OpenStreetMap shows 2 more bakeries inside the walk that Qloo doesn't list, and what they are "
        "known for is not known."
    )
    assert claims["closer"]["proof"].endswith("a median 2.1 km away.")  # trips do not rest on the places inside
    # The ad lines never name the places OpenStreetMap shows, as they never name a competitor.
    assert not any(name in c["line"] for c in claims.values() for name in ("Crumb & Co", "Sunrise Pastry"))


def test_a_rule_concepts_one_liner_counts_both_maps():
    rows = score(row_with(1, ["Saltmarsh Fish Bar"], genre="Seafood", around=24),
                 row_with(6, [], genre="Bakery", around=24), row_with(6, [], genre="Cafe", around=24))
    seafood = next(row for row in rows if row["genre"] == "Seafood")
    assert one_liner(seafood, 10).startswith("Seafood close to home: 2 inside the walk where a block this dense has about")
