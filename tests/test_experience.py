from app.survey import experience
from app.survey.models import RunState, Site


def card(name, **extra):
    return {"id": f"id-{name}", "name": name, "image": None, **extra}


TASTE = {
    "artists": [card("Pop Star"), card("Indie Band")],
    "brands": [card("Big Soda")],
    "distinctive_artists": [card("Indie Band", since=2019), card("Jazz Elder", since=1975), card("Middle Act", since=2010)],
    "distinctive_movies": [card("Harbor Film", year=1998)],
    "distinctive_tv": [card("Pier Show", year=2021)],
    "distinctive_podcasts": [card("Block Radio")],
}


def run_with(taste=TASTE):
    run = RunState(id="r", site=Site(0, 0, "Test"))
    run.taste = taste
    return run


def test_plan_programs_by_kind_of_business():
    bar = experience.plan(run_with(), "Wine Bar", this_year=2026)
    assert [a["name"] for a in bar["soundtrack"]] == ["Indie Band", "Jazz Elder", "Middle Act"]
    assert [a.get("era") for a in bar["soundtrack"]] == ["new", "classic", None]
    assert [s["name"] for s in bar["screen"]] == ["Harbor Film", "Pier Show"]
    assert bar["screen"][0] == {"id": "id-Harbor Film", "name": "Harbor Film", "year": 1998, "era": "classic"}
    assert [t["name"] for t in bar["talks"]] == ["Block Radio"]
    assert "1.5 km" in bar["basis"] and bar["licensing"]

    cafe = experience.plan(run_with(), "Coffee shop", this_year=2026)
    assert "screen" not in cafe and [t["name"] for t in cafe["talks"]] == ["Block Radio"]
    restaurant = experience.plan(run_with(), "Seafood", this_year=2026)
    assert set(restaurant) == {"soundtrack", "basis", "licensing"}
    shop = experience.plan(run_with(), "Gift shop", this_year=2026)
    assert set(shop) == {"soundtrack", "basis", "licensing"}


def test_plan_is_empty_without_signature_taste():
    assert experience.plan(run_with({"artists": [card("Pop Star")]}), "Wine Bar") is None


def test_fan_taste_is_specific_only_when_it_differs_from_the_area():
    ignored = {"artists": [card("Pop Star"), card("Indie Band")], "brands": [card("Big Soda")]}
    assert experience.is_specific(ignored, TASTE) is False
    specific = {"artists": [card("Sea Shanty Crew"), card("Indie Band")], "brands": [card("Cider Co")]}
    assert experience.is_specific(specific, TASTE) is True
    assert experience.is_specific({"artists": [], "brands": []}, TASTE) is False
