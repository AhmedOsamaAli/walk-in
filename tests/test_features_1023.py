"""The features of Oct 23: the area as a walk, a drive or a road distance; the owner's age focus; the audience of the
places people here love; and the chain check in "Test my idea"."""
from __future__ import annotations

import asyncio
import json
import math

import httpx
import pytest

from app import catchment as area
from app import engine
from app.demographics import age_signal, ages_label
from app.llm import LLM
from app.survey import audience, design, intents, pipeline
from app.survey.models import RunStore, Site
from tests.fakes import CHAIN_AROUND, CHAIN_INSIDE, SITE, FakeOsm, FakeQloo, FakeWalker

# ---------- The area: walk, drive or road distance ----------


def test_the_area_names_itself_in_sentences_and_chips():
    assert area.Reach("walk", 10).label == "10-minute walk" and area.Reach("walk", 10).short == "10-min walk"
    assert area.Reach("drive", 30).label == "30-minute drive" and area.Reach("drive", 30).short == "30-min drive"
    assert area.Reach("distance", 10, 25.0).label == "25 km drive" and area.Reach("distance", 10, 2.5).label == "2.5 km drive"
    assert area.area_text(10) == "10-minute walk" and area.area_text("30-minute drive") == "30-minute drive"


def test_the_area_compared_with_is_twice_as_long_within_what_the_router_answers():
    assert area.Reach("walk", 10).around == area.Reach("walk", 20)
    assert area.Reach("drive", 40).around == area.Reach("drive", 60)  # capped at the router's 60 minutes
    assert area.Reach("drive", 60).around is None
    assert area.Reach("distance", 10, 30.0).around.km == 60.0
    assert area.Reach("distance", 10, 100.0).around is None


@pytest.mark.parametrize("travel, minutes, km, message", [
    ("walk", 4, None, "Walk time must be 5 to 60 minutes"),
    ("drive", 90, None, "Drive time must be 5 to 60 minutes"),
    ("distance", 10, None, "A road distance must be 1 to 100 km"),
    ("distance", 10, 150, "A road distance must be 1 to 100 km"),
    ("boat", 10, None, "The area must be a walk, a drive or a road distance"),
])
def test_an_area_the_router_cannot_trace_is_refused_in_plain_words(travel, minutes, km, message):
    with pytest.raises(ValueError, match=message):
        area.make_reach(travel, minutes, km)


def test_a_custom_walk_or_distance_is_kept_as_asked():
    assert area.make_reach("walk", 7) == area.Reach("walk", 7)
    assert area.make_reach("distance", None, 12.34) == area.Reach("distance", 10, 12.3)


def test_long_outlines_are_simplified_for_qloo_and_short_ones_kept_exactly():
    walk = area.circle_ring(40.0, -73.0, 800)  # 41 points: a walk keeps every point, so its cached answers still match
    assert area.simplify_ring(walk) == walk
    big = area.circle_ring(40.0, -73.0, 30_000, vertices=900)
    small = area.simplify_ring(big)
    assert len(small) <= area.QLOO_RING_POINTS and small[0] == small[-1]
    assert math.isclose(area.ring_area_m2(small, 40.0), area.ring_area_m2(big, 40.0), rel_tol=0.02)
    drive = area.Catchment(40.0, -73.0, 30, "street network", big, travel="drive")
    assert drive.wkt.count(",") < area.QLOO_RING_POINTS and len(drive.ring) == 901  # the map still gets every point


def contour(value: float, radius_m: float) -> dict:
    ring = area.circle_ring(40.0, -73.0, radius_m)
    return {"properties": {"contour": float(value)}, "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}


def service(tmp_path, reply: dict | None, seen: list) -> area.CatchmentService:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=reply) if reply is not None else httpx.Response(503)

    svc = area.CatchmentService(tmp_path)
    svc._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return svc


def test_a_drive_is_traced_by_car_with_its_longer_drive(tmp_path):
    seen: list = []
    reply = {"features": [contour(40, 16_000), contour(20, 9_000)]}
    got = asyncio.run(service(tmp_path, reply, seen).area(40.0, -73.0, area.Reach("drive", 20)))
    assert seen[0]["costing"] == "auto" and seen[0]["contours"] == [{"time": 20}, {"time": 40}]
    assert got.source == "street network" and got.travel == "drive" and got.label == "20-minute drive"
    assert got.around is not None and got.around_label == "40-minute drive"
    public = got.public()
    assert public["travel"] == "drive" and public["label"] == "20-minute drive" and public["short"] == "20-min drive"


def test_a_road_distance_is_traced_as_a_distance_and_cached_apart_from_walks(tmp_path):
    seen: list = []
    reply = {"features": [contour(25, 18_000)]}
    got = asyncio.run(service(tmp_path, reply, seen).area(40.0, -73.0, area.Reach("distance", 10, 25.0)))
    assert seen[0]["contours"] == [{"distance": 25.0}, {"distance": 50.0}]
    assert got.travel == "distance" and got.km == 25.0 and got.label == "25 km drive"
    # Without the longer outline, supply is compared with a circle, and the words say so.
    assert got.around is None and got.around_label == "area twice as wide as the 25 km drive"
    again = asyncio.run(service(tmp_path, None, []).area(40.0, -73.0, area.Reach("distance", 10, 25.0)))
    assert again.ring == got.ring
    assert asyncio.run(service(tmp_path, None, []).walk(40.0, -73.0, 10)).source == "circle"  # not the drive's outline


def test_without_routing_a_drive_falls_back_to_a_circle_sized_for_driving(tmp_path):
    got = asyncio.run(service(tmp_path, None, []).area(40.0, -73.0, area.Reach("drive", 10)))
    assert got.source == "circle" and got.travel == "drive"
    assert 3_900 <= got.radius_m <= 4_000  # 400 m a minute
    road = area.circle_catchment(40.0, -73.0, 10, area.Reach("distance", 10, 20.0))
    assert 13_800 <= road.radius_m <= 14_000  # 0.7 of the road distance


def test_drive_and_distance_outlines_have_believable_sizes():
    city_drive = area.circle_ring(40.0, -73.0, 6_000)
    assert area.plausible(city_drive, 40.0, 10, area.Reach("drive", 10))
    assert not area.plausible(area.circle_ring(40.0, -73.0, 40), 40.0, 10, area.Reach("drive", 10))
    assert not area.plausible(area.circle_ring(40.0, -73.0, 30_000), 40.0, 10, area.Reach("distance", 10, 20.0))


def test_a_drive_widens_where_favorites_and_taste_are_read():
    walk = area.circle_catchment(*SITE, 10)
    drive = area.circle_catchment(*SITE, 30, area.Reach("drive", 30))
    assert engine.favorites_m(walk) == engine.FAVORITES_M and engine.taste_m(walk) == engine.TASTE_M
    assert engine.favorites_m(drive) == round(2.5 * drive.radius_m) > engine.FAVORITES_M
    assert engine.metro_m(drive) > engine.METRO_M and engine.taste_m(drive) == round(drive.radius_m)


# ---------- A survey of a drive, for an age group ----------


async def survey(osm_client=None, **brief) -> tuple[object, list[tuple[str, dict]], FakeQloo]:
    events: list[tuple[str, dict]] = []
    q = FakeQloo()

    async def emit(event: str, data: dict) -> None:
        events.append((event, json.loads(json.dumps(data))))

    site = Site(*SITE, "Test Corner, Testville", **brief)
    run = await pipeline.analyze_site(
        q, FakeWalker(), LLM("", None, "test-model"), RunStore(), site, emit, osm_client=osm_client,
    )
    return run, events, q


def test_the_age_focus_leans_every_ranking_and_favorite_toward_that_age_group():
    assert age_signal("all") == {} and ages_label("all") is None
    assert age_signal("25_34") == {"signal.demographics.age": "25_to_29,30_to_34", "signal.demographics.age.weight": "high"}
    run, events, q = asyncio.run(survey(ages="25_34"))
    started = next(data for event, data in events if event == "run")
    assert started["ages_label"] == "25–34" and started["area_label"] == "10-minute walk"
    assert started["site"]["ages"] == "25_34"
    rankings = [p for p in q.requests if p.get("filter.type") == "urn:tag"]
    assert rankings and all(p.get("signal.demographics.age") == "25_to_29,30_to_34" for p in rankings)
    favorites = [p for p in q.requests if p.get("filter.type") == "urn:entity:place" and "signal.location" in p]
    assert favorites and all(p.get("signal.demographics.age.weight") == "high" for p in favorites)
    supply = [p for p in q.requests if p.get("filter.type") == "urn:entity:place" and "signal.location" not in p]
    assert supply and not any("signal.demographics.age" in p for p in supply)  # what is there is counted for everyone
    labels = [data["label"] for event, data in events if event == "status" and data["step"] == "demand"]
    assert labels[0] == "Ranking what people here aged 25–34 engage with against same-size areas around"


def test_a_survey_for_everyone_sends_no_age_signal():
    _, events, q = asyncio.run(survey())
    assert not any("signal.demographics.age" in p for p in q.requests)
    assert next(data for event, data in events if event == "run")["ages_label"] is None


def test_a_drive_survey_traces_the_drive_and_says_so():
    run, events, _ = asyncio.run(survey(travel="drive", minutes=30))
    catchment = next(data for event, data in events if event == "catchment")
    assert catchment["travel"] == "drive" and catchment["label"] == "30-minute drive"
    assert next(data for event, data in events if event == "run")["area_label"] == "30-minute drive"
    walk_step = [data["label"] for event, data in events if event == "status" and data["step"] == "walk"]
    assert walk_step[0] == "Tracing a 30-minute drive over the street network"
    assert run.catchment.radius_m > 10_000


def test_an_area_too_large_for_openstreetmap_is_not_sent_to_it_and_says_so():
    osm_client = FakeOsm()
    _, events, _ = asyncio.run(survey(osm_client, travel="drive", minutes=30))
    assert osm_client.scans == 0
    notices = [data["message"] for event, data in events if event == "notice"]
    assert any("larger than 30 km²" in message for message in notices)
    assert not any(event == "status" and data["step"] == "osm" for event, data in events)
    rows = next(data for event, data in events if event == "gaps")["rows"]
    assert rows and all(not row["osm"]["checked"] for row in rows)
    assert rows[0]["osm"]["note"] == "Not cross-checked: OpenStreetMap is read for areas up to 30 km², and this one is larger."
    _, walked, _ = asyncio.run(survey(FakeOsm()))
    assert any(event == "status" and data["step"] == "osm" for event, data in walked)  # a walk is still checked


# ---------- Who the places people here love draw ----------


def answers(*leans: dict, female: float = 0.4) -> list[dict]:
    return [{"entity_id": f"p{i}", "query": {"age": lean, "gender": {"male": -female, "female": female}}}
            for i, lean in enumerate(leans)]


AGES = {"24_and_younger": -0.3, "25_to_29": 0.05, "30_to_34": 0.2, "35_to_44": 0.25, "45_to_54": -0.1, "55_and_older": -0.4}


def test_the_audience_is_the_median_lean_over_the_places_and_names_only_clear_leans():
    noisy = {**AGES, "30_to_34": -0.85}  # one place's odd answer does not move the median
    got = audience.read(answers(AGES, AGES, noisy, AGES), ["A", "B", "C", "D"], "Seafood")
    assert [b["band"] for b in got["bands"]] == ["Under 25", "25–29", "30–34", "35–44", "45–54", "55+"]
    assert got["ages"] == "30–44" and (got["age_min"], got["age_max"]) == (30, 44)
    assert got["gender"] == "women" and got["ad"] == "Ages 30–44, women"
    assert got["line"] == "The 4 seafood places people here love draw 30–44-year-olds most, and lean toward women."
    assert got["basis"].startswith("Qloo's audience data for the 4 seafood places people here love")


def test_a_mild_lean_is_said_but_not_targeted_and_no_lean_says_so():
    mild = audience.read(answers(AGES, AGES, AGES, female=0.2), ["A", "B", "C"], "Wine Bar")
    assert mild["gender"] == "women" and mild["ad"] == "Ages 30–44, all genders (the lean toward women is mild)"
    flat = {key: 0.02 for key in AGES}
    none = audience.read(answers(flat, flat, flat, female=0.05), ["A", "B", "C"], "Coffee shop")
    assert none["ages"] is None and none["gender"] is None and none["ad"] is None
    assert none["line"].endswith("draw every age group and both women and men about equally: no need to narrow an ad by either.")
    older = {**{key: -0.2 for key in AGES}, "45_to_54": 0.2, "55_and_older": 0.3}
    assert audience.read(answers(older, older, older), ["A", "B", "C"], "Diner")["ages"] == "45+"
    young = {**{key: -0.2 for key in AGES}, "24_and_younger": 0.4}
    got = audience.read(answers(young, young, young, female=-0.5), ["A", "B", "C"], "Diner")
    assert got["ages"] == "Under 25" and got["gender"] == "men" and got["ad"] == "Ages 18–24, men"


def test_too_few_places_give_no_audience():
    assert audience.read(answers(AGES, AGES), ["A", "B"], "Seafood") is None


def test_the_audience_lists_only_the_places_qloo_answered_for():
    places = [{"entity_id": "p0", "name": "A"}, {"entity_id": "p1", "name": "B"}, {"entity_id": "p2", "name": "C"}]
    rows = [{"entity_id": "p0", "query": {"age": AGES}}, {"entity_id": "p1", "query": {}},
            {"entity_id": "p2", "query": {"age": AGES}}]
    assert audience.answered_names(rows, places) == ["A", "C"]


def test_a_lone_word_one_places_reviews_mention_is_not_what_a_concept_is_known_for():
    from app.survey.evidence import offer_items
    from tests.fakes import GENRES, place

    def cafe(name: str, keywords: list[tuple[str, int]], index: int) -> dict:
        entity = place(name, "Coffee shop", 40.001 + index / 1000, -73.0, index)
        entity["tags"] = [t for t in entity["tags"] if "menu_highlight" not in t["type"]]
        entity["properties"]["keywords"] = [{"name": k, "count": c} for k, c in keywords]
        return entity

    loved = [cafe("Cafe Alpha", [("medicine", 2), ("brownie cheesecake", 2), ("croissant", 2)], 0),
             cafe("Cafe Beta", [("croissant", 2), ("cardamom", 3)], 1),
             cafe("Cafe Gamma", [("turkish coffee", 2)], 2)]
    row = {"genre": "Coffee shop", "genre_id": GENRES["Coffee shop"], "_favorite_entities": loved,
           "favorites": [{"name": e["name"]} for e in loved], "_nearby_entities": []}
    items = {i["item"] for i in offer_items(row, limit=10)}
    assert "Medicine" not in items  # one word, one place, two mentions: no evidence of a dish
    assert {"Croissant", "Brownie cheesecake", "Turkish coffee", "Cardamom"} <= items


OLDER = {"24_and_younger": -0.4, "25_to_29": -0.3, "30_to_34": -0.2, "35_to_44": -0.1, "45_to_54": 0.3, "55_and_older": 0.4}


def test_the_tip_names_who_the_loved_places_draw_that_the_places_already_here_do_not():
    loved = audience.read(answers(AGES, AGES, AGES), ["A", "B", "C"], "Hamburger restaurant")
    here = audience.read(answers(OLDER, OLDER, OLDER, female=-0.3), ["D", "E", "F"], "Hamburger restaurant")
    assert audience.tip(loved, here, "Hamburger restaurant", "walk", 6) == (
        "The 6 hamburger places already inside the walk draw people 45 and over and lean toward men. The ones people "
        "here love draw 30–44-year-olds, leaning toward women: aim the concept at them.")
    neutral = audience.read(answers(AGES, AGES, AGES, female=0.0), ["D", "E", "F"], "Wine Bar")
    assert audience.tip(loved, neutral, "Wine Bar", "30-minute drive") is None  # places for everyone serve women too
    men = audience.read(answers(AGES, AGES, AGES, female=-0.3), ["D", "E", "F"], "Wine Bar")
    assert audience.tip(loved, men, "Wine Bar", "30-minute drive") == (
        "The wine bars already inside the 30-minute drive lean toward men. The ones people here love draw women: aim "
        "the concept at them.")


def test_no_tip_when_the_places_already_here_draw_the_same_people_or_only_a_little_less():
    loved = audience.read(answers(AGES, AGES, AGES), ["A", "B", "C"], "Seafood")
    assert audience.tip(loved, loved, "Seafood") is None
    weaker = {key: value - 0.05 for key, value in AGES.items()}
    same_group = audience.read(answers(weaker, weaker, weaker, female=0.2), ["D", "E", "F"], "Seafood")
    assert audience.tip(loved, same_group, "Seafood") is None  # the same age group and gender, a little less: no gap


def test_the_sheet_reads_the_places_already_here_with_one_more_call():
    async def sheet():
        run, _, q = await survey()
        index = next(i for i, c in enumerate(run.concepts) if c["genre"] == "Seafood")
        return await design.design_concept(run, index, q), q

    made, q = asyncio.run(sheet())
    people = made["audience"]
    # The fake world has one seafood place inside the walk: too few to read, so no tip and no extra call.
    assert people["inside"] is None and people["tip"] is None
    assert len([p for p in q.requests if p.get("filter.type") == "urn:demographics"]) == 1


def test_the_category_in_general_stands_in_when_too_few_loved_places_have_audience_data_and_says_so():
    got = audience.read(answers(AGES), [], "Seafood", general=True)
    assert got["general"] and got["places"] == [] and got["ages"] == "30–44"
    assert got["line"] == "Seafood places in general draw 30–44-year-olds most, and lean toward women."
    assert got["basis"].startswith("Qloo's audience data for seafood places in general, everywhere")
    assert audience.read([], [], "Seafood", general=True) is None


def test_the_design_sheet_and_its_ads_carry_the_audience():
    async def sheet():
        run, _, q = await survey()
        index = next(i for i, c in enumerate(run.concepts) if c["genre"] == "Seafood")
        return await design.design_concept(run, index, q), q

    made, q = asyncio.run(sheet())
    people = made["audience"]
    assert people["ages"] == "30–44" and people["gender"] == "women" and len(people["places"]) >= 3
    assert made["launch"]["audience"]["people"] == people
    settings = {c["channel"]: c["setting"] for c in made["launch"]["channels"]}
    assert "Ages 30–44, women." in settings["Meta or Google local ads"]
    assert made["launch"]["where"]["label"] == "10-minute walk"
    asked = [p for p in q.requests if p.get("filter.type") == "urn:demographics"]
    assert len(asked) == 1 and len(asked[0]["signal.interests.entities"].split(",")) <= audience.MAX_PLACES


# ---------- The chain check ----------


@pytest.mark.parametrize("query, name, named", [
    ("Starbucks", "Starbucks", True),
    ("a Starbucks franchise", "Starbucks", True),
    ("Blue Bottle", "Blue Bottle Coffee", True),
    ("Shake Shack", "Steak 'n Shake", False),
    ("Joe Coffee", "Trader Joe's", False),
    ("bakery", "Carlo's Bakery", False),
    ("pizza", "Pizza Hut", False),
    ("sushi", "Sushi Shop", False),
    ("coffee shop", "The Body Shop", False),
    ("cafe", "Cafe", False),
])
def test_a_chain_counts_only_when_the_owner_named_it(query, name, named):
    assert engine.is_brand_named(query, name) is named


def test_a_chain_is_judged_as_its_stores_category_and_its_stores_are_counted():
    run, events, _ = asyncio.run(survey(intent="open", business="Bean Chain"))
    verdict = next(data for event, data in events if event == "verdict")
    assert verdict["found"] and verdict["genre"] == "Coffee shop"
    chain = verdict["chain"]
    assert chain["brand"] == "Bean Chain" and chain["inside"] == CHAIN_INSIDE and chain["around"] == CHAIN_AROUND
    assert chain["line"] == (f"{CHAIN_INSIDE} Bean Chain locations are already inside the 10-minute walk, and "
                             f"{CHAIN_AROUND} within the area twice as wide as the 10-minute walk.")
    assert "Qloo files its stores as Coffee shop" in chain["basis"] and "_genre" not in chain


def test_a_category_word_is_never_taken_for_a_chain():
    _, events, q = asyncio.run(survey(intent="open", business="bakery"))
    verdict = next(data for event, data in events if event == "verdict")
    assert verdict["genre"] == "Bakery" and verdict["chain"] is None
    assert not any(p.get("types") == "urn:entity:brand" for p in q.requests)  # a category's own name is not searched


def test_a_chain_check_that_fails_leaves_the_verdict_to_the_words():
    class Failing(FakeQloo):
        async def search(self, params: dict) -> dict:
            from app.qloo import QlooError

            if params.get("types") == "urn:entity:brand":
                raise QlooError("Qloo /search returned HTTP 500")
            return await super().search(params)

    async def judge():
        run, _, _ = await survey()
        run.site.business = "Seafood"
        return await intents.chain_check(Failing(), run, "Bean Chain")

    assert asyncio.run(judge()) is None


# ---------- Fixes from the pre-deploy review (Oct 24) ----------


def test_a_decimal_road_distance_matches_valhallas_contour_cut_to_two_decimals():
    ring = area.circle_ring(40.0, -73.0, 1500)
    data = {"features": [{"properties": {"contour": 2.29},
                          "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}]}
    assert area.parse_isochrone(data, 2.3) is not None
    assert area.parse_isochrone(data, 2.4) is None


def test_an_area_too_large_for_openstreetmap_says_so_and_never_that_it_did_not_answer():
    _, events, _ = asyncio.run(survey(FakeOsm(), travel="drive", minutes=30))
    rows = next(data for event, data in events if event == "gaps")["rows"]
    assert all(row["osm"]["reason"] == "too_big" for row in rows)
    lines = [line for row in rows for line in row.get("why") or []]
    assert not any("did not answer" in line for line in lines)
    assert any("too large for OpenStreetMap" in line for line in lines)


def test_the_agent_sees_what_the_loved_places_offer():
    from app.survey.evidence import inspect_payload

    run, _, _ = asyncio.run(survey())
    row = next(r for r in run.gaps if r["genre"] == "Seafood")
    offered = inspect_payload(run, row)["what_these_places_offer"]
    assert offered and "menu" in offered


def test_a_big_chain_keeps_its_50_plus_when_qloo_lists_closed_stores_among_them():
    class ManyStores(FakeQloo):
        async def insights(self, params: dict) -> dict:
            if params.get("filter.references_brand"):
                offset = int(params.get("offset", 0))
                stores = []
                for i in range(offset, min(offset + 50, 120)):
                    store = {"entity_id": f"s{i}", "name": f"Store {i}", "properties": {"is_closed": i % 20 == 0}}
                    stores.append(store)
                return {"results": {"entities": stores}}
            return await super().insights(params)

    stores, capped = asyncio.run(engine.brand_stores(ManyStores(), {"filter.location": "x"}, "brand", 50))
    assert len(stores) == 50 and capped
    few, more = asyncio.run(engine.brand_stores(ManyStores(), {"filter.location": "x"}, "brand", 150))
    assert len(few) == 114 and not more  # 120 listed, 6 closed, and the last page was not full
