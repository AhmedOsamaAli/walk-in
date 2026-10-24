"""The dossier: every section with its basis, numbers equal to the evidence, nothing invented when evidence is missing."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, date, datetime

from app import space
from app.llm import LLM
from app.survey import launch, pipeline
from app.survey.concepts import rule_concept
from app.survey.design import design_concept
from app.survey.dossier import SECTIONS, VERDICT_STAMPS, build_dossier
from app.survey.evidence import gap_for
from app.survey.models import RunStore, Site
from tests.fakes import SITE as FAKE_SITE
from tests.fakes import FakeQloo, FakeWalker
from tests.test_kit import RING, sheet, world

PREPARED = date(2026, 10, 22)


def dossier_of(run, design: dict | None = None, index: int = 0, copy: dict | None = None) -> dict:
    return build_dossier(run, index, design or sheet(run, index), copy, prepared=PREPARED)


def test_every_section_is_present_with_its_basis():
    run = world()
    dossier = dossier_of(run)
    assert dossier["sections"] == list(SECTIONS)
    for key in SECTIONS:
        assert dossier[key]["basis"], key
    assert all(n["label"] and n["value"] and n["basis"] for n in dossier["case"]["numbers"])
    assert all(s["basis"] for s in dossier["first_90_days"]["steps"])
    assert all(q["basis"] for q in dossier["before_you_sign"]["questions"])
    assert all(i["how"] for i in dossier["method"]["items"]) and dossier["method"]["freshness"]
    cover = dossier["cover"]
    assert cover["concept"] == "Golden Hour" and cover["genre"] == "Bakery" and cover["site_label"] == "Test Corner, Austin"
    assert (cover["lat"], cover["lon"], cover["walk_minutes"]) == (30.26, -97.72, 10)
    assert cover["ring"] == [[lat, lon] for lon, lat in RING]
    assert cover["neighborhoods"] == ["Holly", "East Cesar Chavez"]
    assert cover["evidence_date"] == datetime.fromtimestamp(run.created_at, UTC).date().isoformat()
    assert cover["prepared_date"] == "2026-10-22"
    assert [s["name"] for s in cover["sources"]] == [
        "Qloo Insights API", "Valhalla routing on OpenStreetMap data (FOSSGIS)", "International Building Code, Table 1004.5",
    ]


def test_the_case_numbers_are_the_evidence():
    run = world()
    design = sheet(run)
    row = gap_for(run, "Bakery")
    case = dossier_of(run, design)["case"]
    numbers = {n["label"]: n for n in case["numbers"]}
    assert list(numbers) == ["Demand", "Supply", "Pull", "Capacity"]
    assert numbers["Demand"]["data"] == {"here": row["demand_rank"], "around": row["ref_rank"]}
    assert numbers["Demand"]["value"] == "#6 here, #14.5 in the areas around"
    assert numbers["Supply"]["data"] == {"inside": row["nearby_count"], "typical": row["expected_nearby"]}
    assert numbers["Supply"]["value"] == "2 inside the walk, about 5.2 typical"
    assert numbers["Pull"]["data"] == {"outside": row["favorites_far"], "of": row["favorites_total"], "median_km": 2.8}
    assert numbers["Pull"]["value"] == "3 of 3 loved places outside the walk; median distance 2.8 km"
    assert numbers["Capacity"]["data"] == space.fit("Bakery", 60, None)["capacity"] == {"mode": "seated", "low": 23, "high": 27}
    assert numbers["Capacity"]["value"] == "About 23–27 seated guests at most in 60 m² (646 ft²)"
    assert case["decision"] == {
        "kind": "gap", "stamp": "Clear gap", "rank": 2, "of": 8, "gap_score": 64,
        "reason": "Bakery ranks #2 of the 8 categories measured here, with a gap score of 64 of 100.",
        "basis": case["decision"]["basis"],
    }
    assert case["who"]["text"].startswith("Neighbors within a 10-minute walk who now travel a median 2.8 km to bakeries")
    assert case["risk"]["text"] and case["risk"]["check"] and case["risk"]["text"] != case["risk"]["check"]


def test_no_price_appears_anywhere_in_the_report():
    # Every place in this world lists a Qloo price level, and still none reaches the page, as $ or in money.
    run = world()
    text = json.dumps(dossier_of(run), ensure_ascii=False)
    assert "$" not in text and "price_level" not in text and "Price position" not in text
    assert not re.search(r"\b(USD|dollars?|€|£)\b", text, re.IGNORECASE)


def test_competitors_carry_their_complaints_with_counts():
    competition = dossier_of(world())["competition"]
    places = {p["name"]: p for p in competition["places"]}
    assert list(places) == ["Corner Loaf", "Dawn Rolls"] and competition["count"] == 2
    assert [(c["theme"], c["mentions"]) for c in places["Corner Loaf"]["complaints"]] == [
        ("Long waits and lines", 7), ("Rude staff", 3)]
    assert [(c["theme"], c["mentions"]) for c in places["Dawn Rolls"]["complaints"]] == [
        ("Long waits and lines", 4), ("Hygiene", 2)]
    assert places["Dawn Rolls"]["complaints"][1]["keywords"] == ["dirty tables"]
    corner = places["Corner Loaf"]
    assert (corner["rating"], corner["known_for"], corner["main"]) == (4.4, ["sourdough"], True)
    assert "price" not in corner
    assert competition["themes"] == [
        {"theme": "Long waits and lines", "places": 2, "mentions": 11},
        {"theme": "Rude staff", "places": 1, "mentions": 3},
        {"theme": "Hygiene", "places": 1, "mentions": 2},
    ]
    promises = competition["your_answer"]["promises"]
    assert [p["promise"] for p in promises] == [
        launch.PROMISES["Long waits and lines"], launch.PROMISES["Rude staff"], launch.PROMISES["Hygiene"]]
    assert promises[0]["mentions"] == 11 and promises[0]["move"]


def test_travel_lists_where_locals_go_now():
    travel = dossier_of(world())["travel"]
    assert [(p["name"], p["km"]) for p in travel["places"]] == [("Crumb", 2.2), ("Rise", 2.8), ("Proof", 3.3)]
    assert (travel["places"][0]["url"], travel["places"][0]["link"]) == ("https://crumb.example/", "site")
    assert (travel["outside"], travel["of"], travel["median_km"]) == (3, 3, 2.8)


def test_the_offer_marks_what_is_new_and_carries_no_price():
    run = world()
    offer = dossier_of(run)["offer"]
    items = {i["item"]: i for i in offer["items"]}
    assert items["Kouign amann"] == {"item": "Kouign amann", "places": 2, "of": 3, "new_here": True}
    # The sheet leads with the concept's own signature; an item the loved places are known for carries their count.
    assert offer["sheet"][:2] == [{"item": "Kouign amann", "places": 2, "new_here": True},
                                  {"item": "Rye loaf", "places": None, "new_here": None}]
    assert "price" not in offer


def test_alternatives_mark_the_chosen_gap_and_say_why_not_the_stronger_ones():
    items = dossier_of(world())["alternatives"]["items"]
    # By gap score, as the rank counts: the thin Yoga studio row (45) comes before Japanese (40).
    assert [i["genre"] for i in items] == ["Wine Bar", "Bakery", "Coffee shop", "Brunch", "Yoga studio", "Japanese"]
    assert [i["position"] for i in items] == [1, 2, 3, 4, 5, 6]
    assert [(i["genre"], i["position"]) for i in items if i["chosen"]] == [("Bakery", 2)]
    assert items[0]["why"] == "Your notes rule it out: it serves alcohol."
    assert items[0]["why_not"] == "Scores higher, but your notes rule it out: it serves alcohol."
    assert all("why_not" not in i for i in items[1:])
    assert items[1]["why"].startswith("Bakery close to home")


def test_the_rank_and_the_alternatives_count_in_one_order():
    run = world()
    run.concepts.append(rule_concept(run, gap_for(run, "Japanese")))
    dossier = dossier_of(run, index=1)
    decision = dossier["case"]["decision"]
    assert (decision["rank"], decision["of"]) == (6, 8)
    items = dossier["alternatives"]["items"]
    assert [i["position"] for i in items if i["chosen"]] == [decision["rank"]]
    # Every category scoring above the chosen one is shown, with why it was not chosen; the thin one too.
    higher = [r["genre"] for r in sorted(run.gaps, key=lambda r: -r["gap_score"]) if r["gap_score"] > 40]
    assert [i["genre"] for i in items if "why_not" in i] == higher == [
        "Wine Bar", "Bakery", "Coffee shop", "Brunch", "Yoga studio"]
    assert next(i for i in items if i["genre"] == "Yoga studio")["why_not"].startswith("Scores higher on thin data")
    # A chosen category ranked below the first six still brings every one above it.
    run.concepts.append(rule_concept(run, gap_for(run, "Gift shop")))
    items = dossier_of(run, index=2)["alternatives"]["items"]
    assert [i["position"] for i in items] == list(range(1, 9)) and items[-1]["chosen"] and items[-1]["genre"] == "Gift shop"


def test_the_business_the_owner_asked_for_carries_its_verdict():
    run = world(verdict=True)
    run.concepts.append(rule_concept(run, gap_for(run, "Coffee shop")))
    decision = dossier_of(run)["case"]["decision"]
    assert (decision["kind"], decision["stamp"], decision["rank"], decision["of"]) == ("verdict", VERDICT_STAMPS["strong"], 2, 8)
    assert decision["reason"] == run.verdict["headline"] and "asked" not in decision
    other = dossier_of(run, index=1)["case"]["decision"]
    assert other["kind"] == "gap" and other["rank"] == 3
    assert other["asked"] == {"business": "bakery", "stamp": "Strong fit", "reason": run.verdict["headline"]}


def test_missing_evidence_leaves_sections_out_instead_of_inventing_them():
    run = world(notes="", size_m2=None, favorites_kind="citywide", nearby_count=0, _nearby_entities=[], competitors=[])
    design = sheet(run)
    dossier = dossier_of(run, design)
    assert "competition" not in dossier and "travel" not in dossier
    assert [n["label"] for n in dossier["case"]["numbers"]] == ["Demand", "Supply"]
    assert "capacity" not in dossier["room"] and design["capacity"] is None
    assert "International Building Code, Table 1004.5" not in [s["name"] for s in dossier["cover"]["sources"]]
    asks = [q["ask"] for q in dossier["before_you_sign"]["questions"]]
    assert "What is the floor area, and what occupant load does the certificate of occupancy allow?" in asks
    assert "guests at most" not in json.dumps(dossier, ensure_ascii=False)
    assert {c["kind"] for c in dossier["launch"]["claims"]} == {"only", "new"}  # none of the kind inside: 'only', no promise
    # A sheet without a launch plan or an experience plan has no such sections, and no channel steps.
    bare = dossier_of(run, {**design, "launch": None, "experience": None})
    assert "launch" not in bare["sections"] and "experience" not in bare["sections"]
    assert [s["when"] for s in bare["first_90_days"]["steps"]] == ["Before signing", "Opening week", "Day 60"]


def test_the_first_90_days_follow_the_evidence():
    run = world()
    steps = dossier_of(run)["first_90_days"]["steps"]
    assert [s["when"] for s in steps] == [
        "Before signing", "Before signing", "Before opening", "Opening week", "Opening week",
        "Opening week", "Opening week", "Weeks 2–4", "Weeks 2–4", "Day 30", "Day 60",
    ]
    assert '"Kouign amann, which no bakery within a 10-minute walk is known for"' in steps[0]["do"]
    assert steps[1]["do"].endswith("(morning).") and "foot traffic" in steps[1]["basis"]
    assert steps[2]["do"] == f"Build the service to keep the promise the ads make: {launch.PROMISES['Long waits and lines']}."
    assert not any("$" in s["do"] or "price" in s["do"].lower() for s in steps)
    assert steps[3]["do"].startswith("Open Mon–Thu 11 am–10 pm") and steps[4]["do"] == launch.INTENT_ANGLE["Routine visit"]
    assert [s["do"].split(":")[0] for s in steps[5:9]] == [
        "Nextdoor, for the neighborhoods of the walk", "A radius ad that covers the walk",
        "Spotify, for awareness across the city", "The Google segment, for people who now travel to places like it",
    ]
    assert "utm_campaign=golden-hour-launch" in steps[9]["do"]
    assert steps[10]["basis"] == "Today: 2 inside the walk, about 5.2 typical; gap score 64 of 100."


def test_landlord_questions_come_from_what_the_business_needs():
    run = world()
    sign = dossier_of(run)["before_you_sign"]
    asks = [q["ask"] for q in sign["questions"]]
    assert asks[0].startswith("Does the unit have, or allow, a full kitchen with extraction")
    assert asks[1] == "Does the lease's permitted use, and the zoning, allow a bakery?"
    assert asks[2] == ("Does the certificate of occupancy allow 27 guests? At 60 m² (646 ft²) the plan assumes about "
                       "23–27 seated guests at most.")
    assert sign["checks"][0]["risk"] and sign["checks"][0]["check"]
    # A wine bar needs a light kitchen and a liquor licence; a unit said to have a full kitchen is asked about its state.
    wine_run = world(notes="")
    wine_run.concepts.append(rule_concept(wine_run, gap_for(wine_run, "Wine Bar")))
    wine_run.site.kitchen = "full"
    wine = [q["ask"] for q in dossier_of(wine_run, index=1)["before_you_sign"]["questions"]]
    assert wine[0] == "Are the prep sinks, the refrigeration and the electrical capacity part of the lease?"
    assert wine[1] == "Does the lease's permitted use, and the zoning, allow a wine bar, and can the unit get a liquor licence?"


def test_the_room_is_the_unit_its_capacity_and_its_hours_only():
    run = world()
    design = sheet(run)
    room = dossier_of(run, design)["room"]
    assert set(room) == {"unit", "capacity", "capacity_basis", "hours", "hours_basis", "basis"}
    assert room["capacity"] == design["capacity"] == "about 23–27 seated guests at most"
    # A sheet saved before the cuts still carries a model's interior and the design DNA; the report shows neither.
    old = {**design, "interior": {"mood": "Warm and bright", "materials": ["Oak"]}, "dna": {"decor": ["Industrial chic"]}}
    assert dossier_of(run, old)["room"] == room


def test_the_pull_is_the_trip_to_the_loved_places_outside_the_walk():
    # Two medians: over every loved place (1.9 km, inside the walk too) and over those outside it (2.8 km).
    dossier = dossier_of(world(median_favorite_km=1.9, median_far_km=2.8))
    pull = next(n for n in dossier["case"]["numbers"] if n["label"] == "Pull")
    assert pull["value"] == "3 of 3 loved places outside the walk; median distance 2.8 km"
    assert pull["data"]["median_km"] == dossier["travel"]["median_km"] == 2.8
    assert "of the 3 outside the walk" in pull["basis"] and "over the 3 outside the walk" in dossier["travel"]["basis"]
    # Without the trip outside the walk, the distance is left out rather than the diluted one put in its place.
    unknown = dossier_of(world(median_favorite_km=1.9, median_far_km=None))
    pull = next(n for n in unknown["case"]["numbers"] if n["label"] == "Pull")
    assert pull["value"] == "3 of 3 loved places outside the walk" and pull["data"]["median_km"] is None
    assert unknown["travel"]["median_km"] is None and "median" not in unknown["travel"]["basis"]
    assert "1.9" not in json.dumps({"pull": pull, "travel": unknown["travel"]})


def test_a_wildcard_concept_is_untested_and_says_so():
    run = world()
    run.concepts[0]["wildcard"] = True
    dossier = dossier_of(run)
    assert "no direct proof of demand" in dossier["case"]["untested"]["text"]
    first = dossier["before_you_sign"]["checks"][0]
    assert "no place like it exists nearby" in first["risk"] and "no direct proof of demand" in first["risk"]
    assert first["check"] and first["basis"]
    plain = dossier_of(world())
    assert "untested" not in plain["case"] and len(plain["before_you_sign"]["checks"]) == 1


def test_a_real_survey_run_yields_a_traceable_dossier():
    q = FakeQloo()

    async def ignore(event: str, data: dict) -> None:
        pass

    async def survey():
        llm = LLM("", None, "test-model")
        site = Site(*FAKE_SITE, "Test Corner, Testville", size_m2=80)
        run = await pipeline.analyze_site(q, FakeWalker(), llm, RunStore(), site, ignore)
        return run, await design_concept(run, 0, q)

    run, design = asyncio.run(survey())
    dossier = build_dossier(run, 0, design, prepared=PREPARED)
    assert {"cover", "case", "alternatives", "competition", "travel", "offer", "launch", "method"} <= set(dossier["sections"])
    row = gap_for(run, run.concepts[0]["genre"])
    demand = dossier["case"]["numbers"][0]
    assert demand["data"] == {"here": row["demand_rank"], "around": row["ref_rank"]}
    assert dossier["competition"]["count"] == row["nearby_count"] == len(dossier["competition"]["places"])
    assert dossier["method"]["items"][0]["how"].startswith("A circle of 800 m around the pin")
    assert not re.search(r"\$\s*\d", json.dumps(dossier, ensure_ascii=False))


def test_an_old_price_level_only_claim_is_left_out_with_a_note():
    from app.survey.dossier import usable_claims
    old = {"launch": {"claims": [
        {"kind": "only", "line": "The only $$ bakery within a 10-minute walk", "proof": "None of the 2 that list a price"},
        {"kind": "new", "line": "Kouign amann, which no bakery nearby is known for", "proof": "2 of 3 loved places"},
    ]}}
    claims, notes = usable_claims({}, old)
    assert [c["kind"] for c in claims] == ["new"]
    assert notes == ['Left out "The only $$ bakery within a 10-minute walk": it is about a price level, which Walk-in '
                     'no longer uses.']


def test_supply_says_routing_failed_only_when_the_walk_itself_is_a_circle():
    from app.catchment import Catchment, circle_catchment
    from app.survey.dossier import around_text
    run = world()
    traced = run.catchment
    assert traced.source != "circle" and traced.around is None  # a traced walk saved before the around area existed
    assert around_text(run) == "the count in a circle twice the walk's radius"
    run.catchment = circle_catchment(traced.lat, traced.lon, 10)
    assert around_text(run).endswith("(street routing was unavailable)")
    run.catchment = Catchment(traced.lat, traced.lon, 10, "street network", traced.ring, traced.ring)
    assert around_text(run).startswith("the count inside the area a 20-minute walk reaches over the streets")


def test_the_number_of_comparison_areas_is_the_number_used():
    from app.survey.evidence import areas_text
    assert areas_text({"ref_areas": 6}) == "six same-size areas"
    assert areas_text({"ref_areas": 4}) == "four same-size areas"  # two fell in open water
    assert areas_text({}) == "same-size areas"


# ---------- The cover's map ----------

STREETS = {
    "box": [[30.25, -97.73], [30.27, -97.71]], "layers": ["primary", "secondary", "residential", "pedestrian"],
    "streets": {"primary": [[[30.26, -97.73], [30.26, -97.71]]], "secondary": [], "residential": [], "pedestrian": []},
    "water": [], "parks": [], "points": 2, "tolerance_m": 2.0, "dropped": [], "credit": "© OpenStreetMap contributors",
    "source": "first.test", "as_of": "2026-10-23T17:33:41Z",
}


def test_the_cover_map_pins_the_competition_tables_places_with_the_surveys_numbers():
    run = world()
    dossier = build_dossier(run, 0, sheet(run), prepared=PREPARED, streets=STREETS)
    cover_map = dossier["cover"]["map"]
    table = dossier["competition"]["places"]
    assert [pin["name"] for pin in cover_map["pins"]] == [place["name"] for place in table] == ["Corner Loaf", "Dawn Rolls"]
    assert [(pin["n"], pin["main"]) for pin in cover_map["pins"]] == [(1, True), (2, True)]
    assert [pin["distance_m"] for pin in cover_map["pins"]] == [place["distance_m"] for place in table]
    assert cover_map["streets"] == STREETS and "area" not in cover_map  # the cover's area_label names the area
    assert cover_map["basis"].endswith("Streets and water: OpenStreetMap, data of 2026-10-23.")
    assert dossier_of(run)["cover"]["map"]["streets"] is None  # no street map: the cover says so, nothing is drawn up


def test_only_the_places_the_survey_numbers_carry_numbers_and_a_place_without_a_location_has_no_pin():
    from app import scoring
    from tests.test_kit import SITE, bakery
    run = world()
    row = gap_for(run, "Bakery")
    more = [bakery(f"Loaf {k}", 20 + k, 1, 0.0004 * k) for k in range(1, 7)]
    more[0]["location"] = None  # Qloo gives this one no location
    row["_nearby_entities"] = row["_nearby_entities"] + more
    row["competitors"] = [scoring.place_card(place, SITE) for place in row["_nearby_entities"][:8]]
    dossier = dossier_of(run)
    pins = dossier["cover"]["map"]["pins"]
    # The survey lists six and numbers those with a location 1, 2, 3…; the rest of the table's places are dots.
    assert [(pin["name"], pin["n"]) for pin in pins] == [
        ("Corner Loaf", 1), ("Dawn Rolls", 2), ("Loaf 2", 3), ("Loaf 3", 4), ("Loaf 4", 5), ("Loaf 5", None),
        ("Loaf 6", None),
    ]
    assert [place["name"] for place in dossier["competition"]["places"]][2] == "Loaf 1"  # in the table, without a pin


def test_the_cover_map_letters_the_trips_as_the_travel_list_and_states_the_claim():
    dossier = dossier_of(world())
    cover_map = dossier["cover"]["map"]
    assert [(t["key"], t["name"], t["km"], t["bearing"]) for t in cover_map["trips"]] == [
        ("A", "Crumb", 2.2, 0), ("B", "Rise", 2.8, 0), ("C", "Proof", 3.3, 0)]
    assert [t["name"] for t in cover_map["trips"]] == [p["name"] for p in dossier["travel"]["places"]]
    assert cover_map["caption"] == ("2 bakeries inside the 10-minute walk; people here travel a median 2.8 km for the 3 "
                                    "they love")
    # Favorites that are the whole city's, not the neighbors' own, are no trips: the line keeps to the count.
    citywide = dossier_of(world(favorites_kind="citywide"))["cover"]["map"]
    assert citywide["trips"] == [] and citywide["caption"] == "2 bakeries inside the 10-minute walk"
    none = dossier_of(world(nearby_count=0, _nearby_entities=[], competitors=[]))["cover"]["map"]
    assert none["pins"] == [] and none["caption"].startswith("No bakery inside the 10-minute walk; ")


def test_a_drive_area_is_named_by_its_label_and_its_pins_are_the_tables_rows():
    from app.catchment import Catchment
    run = world()
    traced = run.catchment
    run.catchment = Catchment(traced.lat, traced.lon, 30, "street network", traced.ring, travel="drive")
    dossier = dossier_of(run)
    cover_map = dossier["cover"]["map"]
    assert cover_map["caption"].startswith("2 bakeries inside the 30-minute drive; ")
    assert "inside the 30-minute drive" in cover_map["basis"] and "walk" not in cover_map["caption"]
    assert len(cover_map["pins"]) <= len(dossier["competition"]["places"])
