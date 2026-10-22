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
from tests.fakes import FakeImages, FakeQloo, FakeWalker
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
    assert list(numbers) == ["Demand", "Supply", "Pull", "Price position", "Capacity"]
    assert numbers["Demand"]["data"] == {"here": row["demand_rank"], "around": row["ref_rank"]}
    assert numbers["Demand"]["value"] == "#6 here, #14.5 in the areas around"
    assert numbers["Supply"]["data"] == {"inside": row["nearby_count"], "typical": row["expected_nearby"]}
    assert numbers["Supply"]["value"] == "2 inside the walk, about 5.2 typical"
    assert numbers["Pull"]["data"] == {"outside": row["favorites_far"], "of": row["favorites_total"], "median_km": 2.8}
    assert numbers["Pull"]["value"] == "3 of 3 loved places outside the walk; median distance 2.8 km"
    price = numbers["Price position"]
    assert price["data"] == {"level": design["price_level"], "open": 3, "loved": row["price"]["loved"], "inside": row["price"]["nearby"]}
    assert price["value"] == "$$$: a level locals love that no place inside the walk charges"
    assert price["basis"].startswith(row["price"]["basis"])
    assert numbers["Capacity"]["data"] == space.fit("Bakery", 60, None)["capacity"] == {"mode": "seated", "low": 23, "high": 27}
    assert numbers["Capacity"]["value"] == "About 23–27 seated guests at most in 60 m² (646 ft²)"
    assert case["decision"] == {
        "kind": "gap", "stamp": "Clear gap", "rank": 2, "of": 8, "gap_score": 64,
        "reason": "Bakery ranks #2 of the 8 categories measured here, with a gap score of 64 of 100.",
        "basis": case["decision"]["basis"],
    }
    assert case["who"]["text"].startswith("Neighbors within a 10-minute walk who now travel a median 2.8 km to bakeries")
    assert case["risk"]["text"] and case["risk"]["check"] and case["risk"]["text"] != case["risk"]["check"]


def test_no_price_level_is_turned_into_money():
    run = world()
    text = json.dumps(dossier_of(run), ensure_ascii=False)
    assert "$$$" in text
    assert not re.search(r"\$\s*\d", text)
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
    assert (corner["price"], corner["rating"], corner["known_for"], corner["main"]) == ("$", 4.4, ["sourdough"], True)
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


def test_the_offer_marks_what_is_new_and_prices_by_level():
    run = world()
    offer = dossier_of(run)["offer"]
    items = {i["item"]: i for i in offer["items"]}
    assert items["Kouign amann"] == {"item": "Kouign amann", "places": 2, "of": 3, "new_here": True}
    assert all(i["places"] for i in offer["sheet"])  # the rules sheet's offer is the evidence's own
    assert offer["price"]["ladder"] == [
        {"level": 1, "label": "$", "loved": 0, "inside": 2}, {"level": 2, "label": "$$", "loved": 1, "inside": 0},
        {"level": 3, "label": "$$$", "loved": 2, "inside": 0}, {"level": 4, "label": "$$$$", "loved": 0, "inside": 0},
    ]
    assert [(a["name"], a["url"]) for a in offer["price"]["anchors"]] == [
        ("Crumb", "https://crumb.example/"), ("Rise", "https://rise.example/")]
    assert offer["price"]["label"] == "$$$" and offer["price"]["open_note"].startswith("No $$$ bakery inside the walk")


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
    assert [n["label"] for n in dossier["case"]["numbers"]] == ["Demand", "Supply", "Price position"]
    assert "capacity" not in dossier["room"] and design["capacity"] is None
    assert "International Building Code, Table 1004.5" not in [s["name"] for s in dossier["cover"]["sources"]]
    asks = [q["ask"] for q in dossier["before_you_sign"]["questions"]]
    assert "What is the floor area, and what occupant load does the certificate of occupancy allow?" in asks
    assert "guests at most" not in json.dumps(dossier, ensure_ascii=False)
    assert {c["kind"] for c in dossier["launch"]["claims"]} == {"new"}  # nothing priced inside: no 'only', no promise
    # A sheet without a launch plan or an experience plan has no such sections, and no channel steps.
    bare = dossier_of(run, {**design, "launch": None, "experience": None})
    assert "launch" not in bare["sections"] and "experience" not in bare["sections"]
    assert [s["when"] for s in bare["first_90_days"]["steps"]] == ["Before signing", "Before opening", "Opening week", "Day 60"]


def test_the_first_90_days_follow_the_evidence():
    run = world()
    steps = dossier_of(run)["first_90_days"]["steps"]
    assert [s["when"] for s in steps] == [
        "Before signing", "Before signing", "Before opening", "Before opening", "Opening week", "Opening week",
        "Opening week", "Opening week", "Weeks 2–4", "Weeks 2–4", "Day 30", "Day 60",
    ]
    assert '"The only $$$ bakery within a 10-minute walk"' in steps[0]["do"] and "Kouign amann" in steps[0]["do"]
    assert steps[1]["do"].endswith("(morning).") and "foot traffic" in steps[1]["basis"]
    assert steps[2]["do"] == "Set prices at $$$ after reading the menus of Crumb and Rise."
    assert steps[3]["do"] == f"Build the service to keep the promise the ads make: {launch.PROMISES['Long waits and lines']}."
    assert steps[4]["do"].startswith("Open Mon–Thu 11 am–10 pm") and steps[5]["do"] == launch.INTENT_ANGLE["Routine visit"]
    assert [s["do"].split(":")[0] for s in steps[6:10]] == [
        "Nextdoor, for the neighborhoods of the walk", "A radius ad that covers the walk",
        "Spotify, for awareness across the city", "The Google segment, for people who now travel to places like it",
    ]
    assert "utm_campaign=golden-hour-launch" in steps[10]["do"]
    assert steps[11]["basis"] == "Today: 2 inside the walk, about 5.2 typical; gap score 64 of 100."


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


def test_the_room_keeps_no_number_the_design_model_wrote():
    run = world()
    design = sheet(run)
    rules_room = dossier_of(run, design)["room"]
    # The rules sheet's seating carries the computed capacity estimate, which is not the model's: it stays.
    assert rules_room["interior"]["seating"] == design["interior"]["seating"]
    assert design["capacity"] in rules_room["interior"]["seating"]
    written = {**design, "interior": {**design["interior"], "seating": "Communal tables for 40 guests",
                                      "mood": "Warm and bright", "materials": ["Oak", "2 kinds of tile"], "seats": 40}}
    room = dossier_of(run, written)["room"]
    assert "seating" not in room["interior"] and "seats" not in room["interior"]
    assert room["interior"]["mood"] == "Warm and bright" and room["interior"]["materials"] == ["Oak"]
    assert room["capacity"] == design["capacity"] == "about 23–27 seated guests at most"


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
        return run, await design_concept(llm, FakeImages(enabled=False), run, 0, q)

    run, design = asyncio.run(survey())
    dossier = build_dossier(run, 0, design, prepared=PREPARED)
    assert {"cover", "case", "alternatives", "competition", "travel", "offer", "launch", "method"} <= set(dossier["sections"])
    row = gap_for(run, run.concepts[0]["genre"])
    demand = dossier["case"]["numbers"][0]
    assert demand["data"] == {"here": row["demand_rank"], "around": row["ref_rank"]}
    assert dossier["competition"]["count"] == row["nearby_count"] == len(dossier["competition"]["places"])
    assert dossier["method"]["items"][0]["how"].startswith("A circle of 800 m around the pin")
    assert not re.search(r"\$\s*\d", json.dumps(dossier, ensure_ascii=False))
