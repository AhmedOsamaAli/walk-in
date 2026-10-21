"""Owner notes read as hard rules: what is understood, what it rules out, and what it leaves alone."""
from __future__ import annotations

import pytest

from app.survey import constraints


@pytest.mark.parametrize("notes, understood", [
    ("no alcohol licence", ["no alcohol"]),
    ("We have no liquor license and want mid-range prices", ["no alcohol", "mid-range prices ($$)"]),
    ("halal, family friendly", ["halal: no pork or alcohol", "family friendly"]),
    ("vegan menu, 1,200 sq ft, no kitchen", ["vegetarian offer", "unit of about 111 m²", "no kitchen"]),
    ("60m2 unit with a patio, upscale", ["upscale prices ($$$–$$$$)", "unit of about 60 m²", "outdoor space"]),
    ("no hood, budget", ["budget prices ($–$$)", "light prep only, no extraction"]),
    ("Open late, near the university", []),
])
def test_notes_are_understood(notes, understood):
    assert constraints.parse(notes).understood == understood


def test_unit_details_come_from_the_notes():
    rules = constraints.parse("about 60 m², no outdoor space, full kitchen")
    assert (rules.size_m2, rules.kitchen, rules.outdoor) == (60.0, "full", False)
    assert constraints.parse("1,500 square feet").size_m2 == 139.4


def test_no_alcohol_rules_out_bars_but_not_cafes_or_juice_bars():
    rules = constraints.parse("no alcohol")
    for genre in ("Wine bar", "Cocktail Bar", "Pub", "Brewery", "Night club", "Sports Bar", "Lounge"):
        assert rules.allows_genre(genre) == (False, "serves alcohol"), genre
    for genre in ("Juice bar", "Coffee shop", "Espresso bar", "Sushi bar", "Hookah lounge", "Bakery", "Barbecue"):
        assert rules.allows_genre(genre) == (True, None), genre


def test_family_friendly_rules_out_nightlife_only():
    rules = constraints.parse("family friendly")
    assert not rules.allows_genre("Night club")[0] and not rules.allows_genre("Cocktail bar")[0]
    assert rules.allows_genre("Ice cream shop")[0] and rules.allows_genre("Seafood")[0]
    assert rules.allows_item("Wine pairing")  # a family restaurant may still pour wine


def test_items_follow_the_notes():
    dry = constraints.parse("halal")
    assert not dry.allows_item("Bloody mary") and not dry.allows_item("Pork belly bites") and not dry.allows_item("Craft beer")
    assert dry.allows_item("Chilli poached eggs") and dry.allows_item("Mint lemonade")
    veg = constraints.parse("vegetarian")
    assert not veg.allows_item("Brisket tacos") and veg.allows_item("Elote")
    assert not veg.allows_item("Grilled octopus") and not veg.allows_item("Steamed mussels")
    assert veg.allows_item("Mushroom risotto") and veg.allows_item("Union Square greens")


def test_price_range_clamps_levels():
    assert constraints.parse("budget").price_level(4) == 2
    assert constraints.parse("upscale").price_level(1) == 3
    assert constraints.parse("").price_level(3) == 3
    assert constraints.parse("").as_evidence() is None
    assert constraints.parse("no alcohol").as_evidence()["no_alcohol"].startswith("never propose")
