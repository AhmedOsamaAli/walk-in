"""Every sentence names the survey's own area: a 30-minute drive or a 25 km drive is never called a walk, a line about
what people here rank or love names the owner's age focus (supply never does), and a walk reads as it always has."""
from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from app import engine
from app.catchment import Catchment, Reach, circle_catchment
from app.llm import LLM
from app.survey import concepts, experience, kit, pipeline
from app.survey.concepts import for_whom, one_liner, rule_concept, wildcard_line
from app.survey.design import design_concept
from app.survey.dossier import build_dossier
from app.survey.evidence import annotate, competition, gap_evidence, gap_for, inspect_payload, risk
from app.survey.models import RunState, RunStore, Site
from tests.fakes import SITE as FAKE_SITE
from tests.fakes import FakeQloo, FakeWalker
from tests.test_kit import RING, SITE, assert_valid, build, facts_of, kit_lines, sheet, world

PREPARED = date(2026, 10, 23)
DRIVE = ("drive", 30, None, "30-minute drive")
DISTANCE = ("distance", 10, 25.0, "25 km drive")
# What would call the area a walk. 'Walk in and say hello', 'walk-ins' and people 'walking past' the door are no area.
WALKED = ("minute walk", "the walk", "on foot", "short walk", "walking distance", "walking routes", "steps from")


def surveyed(travel: str = "walk", minutes: int = 10, km: float | None = None, ages: str = "all",
             catchment: Catchment | None = None, **row_fields) -> RunState:
    """The kit tests' Austin corner (tests.test_kit.world) surveyed as a walk, a drive or a road distance, for an age
    group: the gap table read again with that area, and the bakery concept made from it."""
    run = world(**row_fields)
    site = run.site
    site.travel, site.minutes, site.km, site.ages = travel, minutes, km, ages
    run.catchment = catchment or Catchment(*SITE, minutes, "street network", RING, travel=travel, km=km)
    run.gaps = [annotate(run, row) for row in run.gaps]
    bakery = gap_for(run, "Bakery")
    run.concepts = [{**rule_concept(run, bakery), "name": "Golden Hour", "signature": ["Kouign amann", "Rye loaf"]}]
    return run


def said_as_walk(text: str) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in WALKED if phrase in lowered]


# ---------- The evidence and the concepts ----------

@pytest.mark.parametrize("travel, minutes, km, label", [DRIVE, DISTANCE])
def test_the_evidence_and_the_concept_name_the_drive_or_the_road_distance(travel, minutes, km, label):
    run = surveyed(travel, minutes, km)
    row = gap_for(run, "Bakery")
    assert f"Only 2 bakeries inside the {label}, where a block this dense usually has about 5.2." in row["why"]
    assert (f"All 3 bakeries people here love more than the rest of the city does are outside the {label}, a median "
            f"2.8 km away: Crumb, Rise and Proof.") in row["why"]
    concept = run.concepts[0]
    assert concept["for_whom"].startswith(f"People within a {label} who now travel a median 2.8 km to bakeries")
    assert concept["one_liner"] == (f"Bakery closer to home: 2 inside the {label} where a block this dense has about 5.2, "
                                    f"and people here travel 2.8 km for their favorites.")
    assert concept["beat_competitors"].startswith(f"2 bakeries inside the {label}; the best rated is Dawn Rolls")
    assert f"none inside the {label} is: " in concept["beat_competitors"]
    text = json.dumps([row["why"], concept], ensure_ascii=False)
    assert not said_as_walk(text), said_as_walk(text)


def test_a_walk_reads_as_it_always_has():
    run = surveyed()  # a 10-minute walk, for everyone
    row = gap_for(run, "Bakery")
    assert row["why"] == gap_evidence(row, 10) and row["why"][1].startswith("Only 2 bakeries inside the 10-minute walk")
    assert row["why"][2].startswith("All 3 bakeries people here love more than the rest of the city does are outside the walk")
    concept = run.concepts[0]
    assert concept["for_whom"].startswith("Neighbors within a 10-minute walk who now travel a median 2.8 km to bakeries")
    assert concept["one_liner"].startswith("Bakery close to home: 2 inside the walk where")
    # Callers that still pass a walk's minutes read exactly like the label.
    assert one_liner(row, "10-minute walk") == one_liner(row, 10) and for_whom(row, "10-minute walk") == for_whom(row, 10)
    assert competition(row, "10-minute walk") == competition(row, 10) and risk(row, "10-minute walk") == risk(row, 10)


def test_the_age_focus_names_whose_rankings_and_favorites_a_line_reads_never_the_supply():
    run = surveyed(ages="25_34")
    demand, supply, travel = gap_for(run, "Bakery")["why"]
    assert demand.startswith("People here aged 25–34 rank bakery #6 among the place types they engage with")
    assert supply.startswith("Only 2 bakeries inside the 10-minute walk") and "aged" not in supply
    assert travel.startswith("All 3 bakeries people here aged 25–34 love more than the rest of the city does")
    concept = run.concepts[0]
    assert concept["for_whom"].startswith("Neighbors aged 25–34 within a 10-minute walk who now travel")
    assert concept["for_whom"].endswith("; the bakeries people here aged 25–34 love draw families and couples")
    assert "people here aged 25–34 travel 2.8 km for their favorites" in concept["one_liner"]
    assert "2 bakeries inside the walk; the best rated" in concept["beat_competitors"]  # the supply is everyone's
    drive = surveyed(*DRIVE[:3], ages="under_25")
    assert drive.concepts[0]["for_whom"].startswith("People aged under 25 within a 30-minute drive who now travel")
    assert gap_for(drive, "Bakery")["why"][0].startswith("People here aged under 25 rank bakery #6")


def test_the_wildcard_says_nothing_inside_the_area_is_both():
    run = surveyed(*DRIVE[:3])
    coffee, wine = gap_for(run, "Coffee shop"), gap_for(run, "Wine Bar")
    assert wildcard_line(coffee, wine, "30-minute drive", "35_54") == (
        "A coffee shop by day and a wine bar by night, under one roof: two things people here aged 35–54 love, and "
        "nothing inside the 30-minute drive is both.")
    assert wildcard_line(coffee, wine, 10) == (
        "A coffee shop by day and a wine bar by night, under one roof: two things people here love, and nothing inside "
        "the 10-minute walk is both.")


def test_the_agent_is_told_the_area_and_never_assumes_a_walk():
    assert "walking" not in concepts.CONCEPT_SYSTEM and "inside the walk" not in concepts.CONCEPT_SYSTEM
    assert "walk" not in json.dumps(concepts.CONCEPT_TOOLS)
    run = surveyed(*DRIVE[:3], ages="25_34")
    brief = concepts.agent_brief(run)
    assert brief["catchment"]["area"] == "30-minute drive" and brief["site"]["age_focus"] == "25–34"
    row = brief["gap_table"][1]
    assert row["genre"] == "Bakery" and row["places_inside_the_area"] == "2"
    assert row["do_people_here_travel_for_it"].startswith(
        "3 of the 3 places people here aged 25–34 love more than the rest of the city does are outside the 30-minute drive")
    assert "walk" not in json.dumps(brief, ensure_ascii=False).lower()
    payload = inspect_payload(run, gap_for(run, "Bakery"))
    assert payload["competitors_inside_the_area"] and "walk" not in json.dumps(payload, ensure_ascii=False).lower()


def test_the_taste_basis_follows_the_taste_neighborhood_and_the_age_focus():
    assert experience.basis(surveyed()) == experience.BASIS  # a walk-sized survey for everyone
    assert experience.basis(surveyed(ages="55_plus")) == (
        "What people aged 55+ within 1.5 km over-index on compared with same-size areas a few kilometres around (Qloo).")
    drive = surveyed(*DRIVE[:3], catchment=circle_catchment(*SITE, 30, Reach("drive", 30)))
    taste = engine.taste_m(drive.catchment)
    away = round(engine.reference_distance(taste) / 1000)
    assert taste > 10_000 and experience.basis(drive) == (
        f"What people within {round(taste / 1000)} km over-index on compared with same-size areas about {away} km away "
        f"(Qloo).")
    assert experience.plan(drive, "Wine Bar")["basis"] == experience.basis(drive)


# ---------- The dossier ----------

@pytest.mark.parametrize("travel, minutes, km, label", [DRIVE, DISTANCE])
def test_the_dossier_names_the_area_in_every_section(travel, minutes, km, label):
    run = surveyed(travel, minutes, km)
    dossier = build_dossier(run, 0, sheet(run), prepared=PREPARED)
    cover = dossier["cover"]
    assert cover["area_label"] == label and cover["walk_minutes"] == minutes  # kept for old screens
    assert cover["basis"].startswith(f"The site and the {label} the survey measured on")
    case = dossier["case"]
    assert case["who"]["text"].startswith(f"People within a {label} who now travel")
    assert case["who"]["basis"].startswith(f"People inside the {label}, the trips they make")
    numbers = {n["label"]: n for n in case["numbers"]}
    assert numbers["Supply"]["value"] == f"2 inside the {label}, about 5.2 typical"
    assert numbers["Pull"]["value"] == f"3 of 3 loved places outside the {label}; median distance 2.8 km"
    steps = [s["do"] for s in dossier["first_90_days"]["steps"]]
    assert steps[0].startswith(f"Check the {label} on maps and on the ground and re-check what the ads will claim")
    assert f"Nextdoor, for the neighborhoods of the {label}: " in " ".join(steps)
    assert steps[-1] == f"Run Walk-in again on the same pin and {label} to see whether the gap closed."
    drawn = dossier["method"]["items"][0]
    trip = "reachable in 30 minutes by car" if travel == "drive" else "within 25 km by road"
    assert drawn["topic"] == f"The {label}" and drawn["how"].startswith(f"The area {trip} over the street network")
    assert "Distances to the places locals love are straight lines, not routes by road." in dossier["method"]["limits"]
    text = json.dumps(dossier, ensure_ascii=False)
    assert not said_as_walk(text), said_as_walk(text)


@pytest.mark.parametrize("reach, size, rule, source", [
    (Reach("walk", 10), "800 m", "80 m per minute", "A circle of 80 m per minute of walking"),
    (Reach("drive", 30), "12 km", "400 m per minute of driving, for city traffic",
     "A circle of 400 m per minute of driving, for city traffic"),
    (Reach("distance", 10, 25.0), "17.5 km", "0.7 times the road distance, as roads wind",
     "A circle of 0.7 times the road distance, as roads wind"),
])
def test_without_street_routing_the_circle_follows_the_travel_mode(reach, size, rule, source):
    run = surveyed(reach.travel, reach.minutes, reach.km, catchment=circle_catchment(*SITE, reach.minutes, reach))
    dossier = build_dossier(run, 0, sheet(run), prepared=PREPARED)
    area = "walk" if reach.travel == "walk" else reach.label
    assert dossier["method"]["items"][0] == {
        "topic": f"The {area}", "how": f"A circle of {size} around the pin ({rule}), because street routing was unavailable."}
    assert {"name": source, "used_for": f"The {area}, because street routing was unavailable"} in dossier["cover"]["sources"]


def test_the_sources_name_the_trip_supply_is_compared_with():
    def traced_for(run: RunState) -> str:
        sources = build_dossier(run, 0, sheet(run), prepared=PREPARED)["cover"]["sources"]
        return next(source["used_for"] for source in sources if source["name"].startswith("Valhalla"))

    walk = surveyed(catchment=Catchment(*SITE, 10, "street network", RING, RING))
    assert traced_for(walk) == "The walk, traced over the streets, and the 20-minute walk that supply is compared with"
    # Without the longer outline, a circle stands in, and the line says so.
    assert traced_for(surveyed()) == ("The walk, traced over the streets, and the area twice as wide as the 10-minute "
                                      "walk that supply is compared with")
    drive = surveyed(*DRIVE[:3], catchment=Catchment(*SITE, 30, "street network", RING, RING, travel="drive"))
    assert traced_for(drive) == ("The 30-minute drive, traced over the streets, and the 60-minute drive that supply is "
                                 "compared with")


def test_the_maps_name_the_age_focus_where_they_say_whose_trips_they_show():
    run = surveyed(ages="25_34")
    cover_map = build_dossier(run, 0, sheet(run), prepared=PREPARED)["cover"]["map"]
    assert cover_map["caption"] == ("2 bakeries inside the 10-minute walk; people here aged 25–34 travel a median 2.8 km "
                                    "for the 3 they love")
    assert "Letters: the places of this kind people here aged 25–34 love more than the city does" in cover_map["basis"]
    assert build(run, sheet(run))["poster"]["map"]["caption"] == "2.8 km: where people here aged 25–34 go for bakeries now"


# ---------- The launch kit ----------

@pytest.mark.parametrize("travel, minutes, km, claim, kept, beyond", [
    ("drive", 30, None, "The only bakery within a 30-minute drive",
     ("The only bakery within a 30-minute drive", "It is the only bakery within a thirty-minute drive.",
      "Golden Hour is the only bakery within a 30 minute drive. Come say hello."),
     ("The only bakery within a 30-minute walk", "The only bakery within 30 minutes", "The only bakery in Holly")),
    ("distance", 10, 25.0, "The only bakery within a 25 km drive",
     ("The only bakery within a 25 km drive", "Golden Hour is the only bakery within a 25-km drive.",
      "It is the only bakery within a 25 kilometre drive."),
     # A straight 25 km reaches farther than a 25 km drive.
     ("The only bakery within 25 km", "The only bakery within a 25 km walk", "The only bakery within a 50 km drive")),
])
def test_the_only_claim_keeps_to_the_drive_or_the_road_distance_it_names(travel, minutes, km, claim, kept, beyond):
    run = surveyed(travel, minutes, km)
    only = {"id": "only", "kind": "only", "line": claim,
            "proof": "Qloo lists no bakery inside the area, and OpenStreetMap shows none either."}
    facts = facts_of(run, sheet(run), claims=[only])
    for line in kept:
        assert facts.check(line) == [], (line, facts.check(line))
    for line in beyond:
        assert 'beyond what the "only" claim proves' in " | ".join(facts.check(line)), line


def test_copy_for_a_drive_never_says_the_place_is_a_walk_away():
    run = surveyed(*DRIVE[:3])
    facts = facts_of(run, sheet(run))
    for line in ("A short walk away", "Steps from home", "Within walking distance", "Ten minutes on foot"):
        assert "says the place is a walk away, but the area is a 30-minute drive" in " | ".join(facts.check(line)), line
    for line in ("Walk in and say hello", "30 minutes by car", "Within a 30-minute drive", "Now open"):
        assert facts.check(line) == [], (line, facts.check(line))
    walk = surveyed()
    assert facts_of(walk, sheet(walk)).check("A short walk away") == []
    # The figures of the area are its own: a road distance's minutes are none of them.
    assert kit.area_numbers(run) == {"30"} and kit.area_numbers(walk) == {"10"}
    assert kit.area_numbers(surveyed(*DISTANCE[:3])) == {"25"}


@pytest.mark.parametrize("travel, minutes, km, label, trip", [
    ("drive", 30, None, "30-minute drive", "30 minutes by car"),
    ("drive", 60, None, "60-minute drive", "60 minutes by car"),  # 'Within a 60-minute drive': 24 of 30 characters
    ("distance", 10, 25.0, "25 km drive", "25 km by road"),
])
def test_rules_copy_and_the_poster_name_the_drive_or_the_road_distance(travel, minutes, km, label, trip):
    run = surveyed(travel, minutes, km)
    design = sheet(run)
    result = build(run, design)
    ads = result["copy"]
    assert_valid(ads, facts_of(run, design))
    headlines = ads["google_search"]["headlines"]
    assert f"Within a {label}" in headlines and trip in headlines and len(headlines) >= 8
    assert f"Come for the kouign amann, which no bakery within a {label} is known for." in ads["google_search"]["descriptions"]
    lines = " ".join(kit_lines(ads))
    assert not said_as_walk(lines), said_as_walk(lines)
    poster = result["poster"]
    assert poster["area_label"] == label and poster["minutes"] == minutes


def test_the_model_is_told_the_area_and_who_each_channel_reaches_in_it():
    run = surveyed(*DRIVE[:3])
    design = sheet(run)
    concept = run.concepts[0]
    name = kit.business_name(run, concept, design)
    claims = kit.usable_claims(concept, design)[0]
    brief = kit.model_brief(run, concept, design, name, claims, kit.channel_keys(design),
                            kit.facts_for(run, concept, design, name, claims))
    assert brief["where"]["area"] == "30-minute drive" and "walk_minutes" not in brief["where"]
    assert brief["channels"]["nextdoor"]["reaches"] == "Neighbors in the neighborhoods of the 30-minute drive."
    assert brief["channels"]["meta"]["reaches"] == "People inside a radius that covers the 30-minute drive."
    assert "walk minutes" not in kit.KIT_SYSTEM
    walk = surveyed()
    assert kit.reaches("nextdoor", walk.site.area) == kit.REACHES["nextdoor"]


# ---------- A whole survey ----------

async def survey(**brief) -> tuple[RunState, dict]:
    q = FakeQloo()

    async def ignore(event: str, data: dict) -> None:
        pass

    site = Site(*FAKE_SITE, "Test Corner, Testville", **brief)
    run = await pipeline.analyze_site(q, FakeWalker(), LLM("", None, "test-model"), RunStore(), site, ignore)
    return run, await design_concept(run, 0, q)


@pytest.mark.parametrize("brief, label", [
    ({"travel": "drive", "minutes": 30}, "30-minute drive"),
    ({"travel": "distance", "km": 25.0}, "25 km drive"),
])
def test_a_survey_of_a_drive_or_a_road_distance_never_calls_it_a_walk(brief, label):
    run, design = asyncio.run(survey(**brief))
    assert run.site.area == label and run.catchment.source == "circle"
    why = [line for row in run.gaps for line in row["why"]]
    assert any(f"inside the {label}" in line for line in why)
    ranked = [c for c in run.concepts if not c.get("wildcard")]
    assert ranked and all(c["for_whom"].startswith(f"People within a {label}") for c in ranked)
    wildcard = run.concepts[-1]
    assert wildcard.get("wildcard") and f"No place inside the {label} is both a seafood place and a wine bar." in wildcard["why_here"]
    dossier = build_dossier(run, 0, design, prepared=PREPARED)
    assert dossier["cover"]["area_label"] == label
    text = json.dumps({"why": why, "concepts": run.concepts, "dossier": dossier}, ensure_ascii=False)
    assert not said_as_walk(text), said_as_walk(text)
