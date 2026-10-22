"""The launch plan: who to reach, where, when, and claims that carry their proof."""
from app import scoring
from app.catchment import Catchment
from app.survey import launch
from app.survey.evidence import price_evidence
from app.survey.models import RunState, Site
from tests.fakes import place

TAGS = {
    "crowd": "urn:tag:customer_identity:qloo",
    "time": "urn:tag:time_of_day_fit:qloo",
    "intent": "urn:tag:visit_intent:qloo",
    "menu": "urn:tag:menu_highlight:qloo",
}


def bakery(name: str, index: int, level: int, website: str | None = None, **tags: list[str]) -> dict:
    entity = place(name, "Bakery", 30.26 + index / 1000, -97.72, index)
    entity["properties"]["price_level"] = level
    if website:
        entity["properties"]["website"] = website
    for family, labels in tags.items():
        entity["tags"] += [{"id": f"{TAGS[family]}:{label.lower()}", "name": label, "type": TAGS[family]} for label in labels]
    return entity


LOVED = [
    bakery("Crumb", 1, 3, "https://crumb.example/", crowd=["Families", "Couples"], time=["Morning"],
           intent=["Routine visit"], menu=["Kouign amann"]),
    bakery("Rise", 2, 3, "https://rise.example/", crowd=["Families", "Couples", "Locals"], time=["Morning", "Midday"],
           intent=["Routine visit"], menu=["Kouign amann"]),
    bakery("Proof", 3, 2, crowd=["Families"], time=["Morning"], intent=["Destination"]),
]
# Places 4 and 8 have 'long wait' in their reviews (see tests.fakes.place).
INSIDE = [bakery("Corner Loaf", 4, 1), bakery("Dawn Rolls", 8, 1)]


def gap_row() -> dict:
    row = {
        "genre": "Bakery", "genre_id": LOVED[0]["tags"][0]["id"], "demand_rank": 6, "nearby_count": 2,
        "favorites_kind": "local", "favorites_far": 3, "favorites_total": 3, "leakage": 1.0, "median_favorite_km": 1.4,
        "median_far_km": 2.1,
        "_favorite_entities": LOVED, "favorites": [{**scoring.place_card(e), "within_walk": False} for e in LOVED],
        "_nearby_entities": INSIDE, "competitors": [scoring.place_card(e) for e in INSIDE],
    }
    row["price"] = price_evidence(row)
    return row


def survey() -> RunState:
    site = Site(30.26, -97.72, "Test Corner")
    run = RunState(id="r1", site=site)
    run.catchment = Catchment(30.26, -97.72, 10, "test", [(-97.725, 30.26), (-97.72, 30.265), (-97.715, 30.26), (-97.72, 30.255)])
    hoods = ["Holly", "Holly", "Holly", "East Cesar Chavez", "East Cesar Chavez", ""]
    run.block = [{"name": f"P{i}", "properties": {"neighborhood": h}} for i, h in enumerate(hoods)]
    run.taste = {
        "distinctive_artists": [{"name": "Gary Clark Jr."}, {"name": "Mobley"}],
        "distinctive_podcasts": [{"name": "Stassi"}],
        "distinctive_brands": [{"name": "Patagonia"}],
    }
    return run


CONCEPT = {"name": "Golden Hour", "genre": "Bakery", "price_level": 3, "signature": ["Kouign amann", "Rye loaf"]}


def test_the_plan_reaches_who_the_places_draw_and_what_the_area_over_indexes_on():
    plan = launch.plan(survey(), CONCEPT, gap_row(), shared={"Mobley", "A Fan-Only Brand"}, hours="Daily 7 am–3 pm")
    audience = plan["audience"]
    assert audience["crowd"] == [{"label": "Families", "places": 3, "of": 3}, {"label": "Couples", "places": 2, "of": 3}]
    # Names this category's fans share with the area's signature come first; fan-only names are not the area's.
    assert audience["artists"] == ["Mobley", "Gary Clark Jr."] and audience["shared"] == ["Mobley"]
    assert plan["where"]["neighborhoods"] == ["Holly", "East Cesar Chavez"]
    assert 550 <= plan["where"]["reach_m"] <= 560  # the farthest point of the walk: 0.005° of latitude north or south
    assert [s["name"] for s in plan["where"]["sites_like"]] == ["Crumb", "Rise"]
    assert plan["when"]["times"][0] == {"label": "Morning", "places": 3, "of": 3}
    assert plan["when"]["intents"] == [{"label": "Routine visit", "places": 2, "of": 3,
                                        "angle": launch.INTENT_ANGLE["Routine visit"]}]
    assert plan["when"]["hours"] == "Daily 7 am–3 pm"


def test_every_claim_carries_its_proof_and_none_names_a_competitor():
    plan = launch.plan(survey(), CONCEPT, gap_row())
    claims = {c["kind"]: c for c in plan["claims"]}
    assert list(claims) == ["only", "new", "closer", "promise"]
    assert claims["only"]["line"] == "The only $$$ bakery within a 10-minute walk"
    assert claims["only"]["proof"] == "None of the 2 bakeries inside the walk that list a price is $$$; 2 of the bakeries locals love are."
    assert claims["new"]["line"] == "Kouign amann, which no bakery within a 10-minute walk is known for"
    assert claims["new"]["proof"] == "2 of the bakeries locals love are known for it; none inside the walk is."
    assert claims["closer"]["proof"].endswith("a median 2.1 km away.")
    assert claims["promise"]["line"] == launch.PROMISES["Long waits and lines"]
    assert "2 of the bakeries inside the walk flag long waits and lines" in claims["promise"]["proof"]
    text = " ".join(c["line"] + " " + c["proof"] for c in plan["claims"])
    assert not any(name in text for name in ("Corner Loaf", "Dawn Rolls"))


def test_a_proof_counts_one_place_in_the_singular():
    row = gap_row()
    rise = {**LOVED[1], "tags": [t for t in LOVED[1]["tags"] if t["type"] != TAGS["menu"]]}
    row["_favorite_entities"] = [LOVED[0], rise, LOVED[2]]
    new = next(c for c in launch.claims(survey(), CONCEPT, row) if c["kind"] == "new")
    assert new["proof"] == "1 of the bakeries locals love is known for it; none inside the walk is."


def test_no_only_claim_when_the_level_is_charged_inside_the_walk_or_nothing_inside_is_priced():
    cheap = launch.claims(survey(), {**CONCEPT, "price_level": 1}, gap_row())
    assert "only" not in {c["kind"] for c in cheap}
    empty = gap_row()
    empty["_nearby_entities"], empty["competitors"] = [], []
    empty["price"] = price_evidence(empty)
    assert "only" not in {c["kind"] for c in launch.claims(survey(), CONCEPT, empty)}


def test_cautions_follow_what_the_plan_says():
    plan = launch.plan(survey(), CONCEPT, gap_row())
    assert plan["cautions"] == [launch.NO_COMPETITORS, launch.WALK_FIRST, launch.KEEP_PROMISES, launch.NO_ENDORSEMENT]
    # A plan with no 'only', 'new' or promise line and no names to target needs only the rule about competitors.
    quiet = launch.cautions([{"kind": "closer"}], {"artists": [], "podcasts": [], "screen": [], "brands": []})
    assert quiet == [launch.NO_COMPETITORS]


def test_channels_turn_the_plan_into_platform_settings():
    plan = launch.plan(survey(), CONCEPT, gap_row())
    channels = {c["channel"]: c["setting"] for c in plan["channels"]}
    assert channels["Spotify Ads"] == "Target fans of Gary Clark Jr. and Mobley and listeners of Stassi, in your city."
    assert channels["Nextdoor"] == "Neighborhoods: Holly, East Cesar Chavez."
    assert channels["Google Ads custom segment"] == "People who browse websites like: crumb.example, rise.example."
    assert channels["Meta or Google local ads"].startswith(f"A radius of {plan['where']['reach_m']} m around your door")
