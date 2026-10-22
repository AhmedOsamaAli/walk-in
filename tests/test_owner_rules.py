"""The owner's rules are hard rules: a budget is the lowest price level, a unit without a hood gets nothing that needs one,
a size is a fit every concept states, and every concept has a real name. The model is told the rules; the server checks
its answer, repairs what it can once and drops the rest, saying why in the payload's notes."""
from __future__ import annotations

import asyncio

import pytest

from app import scoring
from app.llm import LLM
from app.survey import concepts, constraints, design
from app.survey.evidence import annotate, price_evidence
from app.survey.models import RunState, Site
from tests.fakes import FakeImages, place, slug
from tests.test_e2e import RUN_PARAMS, first, make_client, scripted_llm, sse_events, tool_call

SITE = (40.7145, -73.9580)
MENU = "urn:tag:menu_highlight:qloo"


def venue(name: str, genre: str, index: int, price: int | None, items: tuple[str, ...] = (), km: float = 2.5) -> dict:
    """A place of `genre` known for `items` (menu tags only, no review keywords), `km` north of the site."""
    entity = place(name, genre, SITE[0] + km / 111.32 + index / 100_000, SITE[1], index)
    entity["tags"] = [t for t in entity["tags"] if t["type"] != MENU] + [
        {"id": f"{MENU}:{slug(item)}", "name": item, "type": MENU} for item in items
    ]
    entity["properties"].update({"price_level": price, "keywords": []})
    return entity


def gap(genre: str, loved: list[dict], inside: list[dict], rank: int = 3, score: int = 50, **fields) -> dict:
    """A measured gap row: `loved` are favorites outside the walk (people here travel to them), `inside` competitors."""
    row = {
        "genre": genre, "genre_id": f"urn:tag:genre:place:test_{slug(genre)}", "demand_rank": rank,
        "ref_rank": rank + 1.0, "lift": 0.1, "nearby_count": len(inside), "nearby_capped": False, "around_count": 30,
        "around_capped": False, "expected_nearby": float(len(inside)), "relative_supply": 1.0, "favorites_kind": "local",
        "favorites_total": len(loved), "favorites_far": len(loved), "median_favorite_km": 2.0, "median_far_km": 2.5,
        "leakage": 1.0, "evidence": "ok", "storefront_share": 1.0, "gap_score": score, "_favorite_entities": loved,
        "favorites": [{**scoring.place_card(e, SITE), "within_walk": False} for e in loved],
        "_nearby_entities": inside, "competitors": [scoring.place_card(e, SITE) for e in inside], "city_favorites": [],
    }
    return {**row, **fields}


COCKTAILS = ("Banana espresso martini", "Deviled eggs", "Crispy potatoes", "Grilled octopus")
CAFE_ITEMS = ("Ube latte", "Orange olive oil muffin", "Cardamom bun")


def cocktail_bar(**fields) -> dict:
    loved = [venue(f"Velvet Room {i}", "Cocktail bar", i, 2, COCKTAILS) for i in range(3)]
    inside = [venue(f"Corner Pour {i}", "Cocktail bar", 10 + i, 2, ("Margaritas",), km=0.2) for i in range(4)]
    return gap("Cocktail bar", loved, inside, rank=3, score=50, **fields)


def coffee_shop(**fields) -> dict:
    loved = [venue(f"Bean There {i}", "Coffee shop", 20 + i, 2, CAFE_ITEMS) for i in range(3)]
    inside = [venue(f"Daily Grind {i}", "Coffee shop", 30 + i, 2, ("Drip coffee",), km=0.3) for i in range(5)]
    return gap("Coffee shop", loved, inside, rank=5, score=45, **fields)


def burger_joint(**fields) -> dict:
    loved = [venue(f"Patty Palace {i}", "Hamburger restaurant", 40 + i, 2, ("Smash burger", "Cheesy fries")) for i in range(3)]
    inside = [venue(f"Bun Stop {i}", "Hamburger restaurant", 50 + i, 2, ("Onion rings",), km=0.2) for i in range(3)]
    return gap("Hamburger restaurant", loved, inside, rank=7, score=40, **fields)


def world(notes: str = "", size_m2: float | None = None, kitchen: str | None = None, rows=None,
          label: str = "Williamsburg, Brooklyn") -> RunState:
    site = Site(*SITE, label, notes=notes, size_m2=size_m2, kitchen=kitchen)
    run = RunState(id="rules", site=site, constraints=constraints.parse(notes))
    rows = rows if rows is not None else [cocktail_bar(), coffee_shop(), burger_joint()]
    run.block = [entity for row in rows for entity in row["_nearby_entities"]]
    run.gaps = [annotate(run, row) for row in rows]
    return run


def model_concept(name: str, genre: str, signature: list[str], one_liner: str = "A short positioning", **fields) -> dict:
    return {"name": name, "genre": genre, "one_liner": one_liner, "signature": signature, **fields}


# ---------- Budget ----------

@pytest.mark.parametrize("notes", [
    "budget prices", "halal, family friendly, budget prices", "cheap eats", "affordable", "low prices", "low-cost",
    "keep prices low", "we are on a budget", "inexpensive", "wallet-friendly menu", "not too expensive",
    "good value for money", "budget-friendly",
])
def test_any_plain_budget_phrasing_means_the_lowest_level(notes):
    rules = constraints.parse(notes)
    assert rules.budget and rules.price == (1, 1) and "budget prices ($)" in rules.understood
    assert rules.price_level(2) == 1 and rules.price_level(4) == 1


@pytest.mark.parametrize("notes", ["not cheap", "no budget limit, upscale", "premium cocktails"])
def test_a_negated_or_other_price_word_is_not_a_budget(notes):
    assert not constraints.parse(notes).budget


def test_a_budget_concept_is_priced_below_the_block_and_says_so():
    run = world("budget prices")
    row = concepts.gap_for(run, "Coffee shop")
    # The places people here love and the five inside the walk are $$: budget is $, below them, never $$.
    assert concepts.grounded_price(run, row, 2)[0] == 1 and concepts.grounded_price(run, row, None)[0] == 1
    price = row["price"]
    assert price["level"] == 1 and price["budget"]["usual"] == 2 and price["budget"]["below"] is True
    assert price["basis"].endswith(
        "Budget, as your notes ask: $, below the block's usual $$ for coffee shops (the median of the 5 inside the walk)."
    )
    assert concepts.price_line(run, row, 1) == "Budget: $, below the block's usual $$ for coffee shops."


def test_without_priced_places_of_its_kind_the_whole_block_sets_the_comparison():
    run = world("budget")
    row = concepts.gap_for(run, "Coffee shop")
    for entity in row["_nearby_entities"]:
        entity["properties"]["price_level"] = None
    block = {"level": 3, "places": 12}
    basis = price_evidence(row, run.constraints, block)["basis"]
    assert basis.endswith("Budget, as your notes ask: $, below the block's usual $$$ (the median of the 12 places inside "
                          "the walk that list a price).")
    # When the block is $ already, budget is still $, and it says it competes on value instead.
    cheap = price_evidence(row, run.constraints, {"level": 1, "places": 8})["budget"]
    assert cheap["below"] is False and cheap["line"].startswith("Budget: $, the lowest level")


def test_the_model_cannot_price_a_budget_concept_at_two_dollars():
    run = world("budget prices")
    notes: list[str] = []
    cleaned = concepts.clean_concepts(run, [model_concept("Ube & Oak", "Coffee shop", ["Ube latte"], price_level=2)], notes)
    assert cleaned[0]["price_level"] == 1 and "Budget, as your notes ask: $" in cleaned[0]["price_basis"]
    assert "Budget: $, below the block's usual $$ for coffee shops." in cleaned[0]["owner_rules"]
    assert "Ube & Oak: priced $ for your budget, not $$." in notes
    upscale = model_concept("Gilded Bean", "Coffee shop", ["Ube latte"], "An upscale espresso salon")
    assert concepts.clean_concepts(run, [upscale], notes)[0]["one_liner"] != "An upscale espresso salon"


def test_rule_concepts_are_budget_too():
    run = world("budget prices")
    assert all(c["price_level"] == 1 and "Budget" in c["price_basis"] for c in concepts.rule_concepts(run))


# ---------- No hood, no kitchen ----------

HOOD_ITEMS = [
    ("Crispy potatoes", "a deep fryer"), ("Truffle fries", "a deep fryer"), ("Fried chicken sandwich", "a deep fryer"),
    ("Vegetable tempura", "a deep fryer"), ("Chicken katsu sando", "a deep fryer"), ("Karaage", "a deep fryer"),
    ("Falafel wrap", "a deep fryer"), ("Taameya sandwich", "a deep fryer"), ("Glazed donuts", "a deep fryer"),
    ("Churros", "a deep fryer"), ("Onion rings", "a deep fryer"), ("Fish and chips", "a deep fryer"),
    ("Smash burger", "a griddle or flat-top"), ("Mushroom cheeseburger", "a griddle or flat-top"),
    ("Stuffed mushroom sliders", "a griddle or flat-top"),
    ("Buttermilk pancakes", "a griddle or flat-top"), ("Pan-seared halloumi", "a griddle or flat-top"),
    ("Grilled octopus", "a grill"), ("Charcoal kofta", "a grill"), ("Lamb kebab", "a grill"),
    ("Shish tawook", "a grill"), ("Ribeye steak", "a grill"), ("Chicken shawarma", "a grill"),
    ("Vegetable stir-fry", "a wok burner"), ("Egg fried rice", "a wok burner"),
    ("Truffle pizza", "a pizza oven"), ("Wood-fired flatbread", "a pizza oven"), ("Calzone", "a pizza oven"),
    # Models type non-breaking hyphens and spaces: the rules read them as plain ones.
    ("Wood\u2011fired flatbread", "a pizza oven"), ("Flat\u2011top eggs", "a griddle or flat-top"),
    ("Deep\u2011fried\u00a0cauliflower", "a deep fryer"),
]
HOOD_FREE_ITEMS = [
    "Honeycomb fig burrata", "Ube latte", "Orange olive oil muffin", "Roasted beet salad", "Avocado toast",
    "Deviled eggs", "Banana espresso martini", "Fresh spring rolls", "Matcha tiramisu", "Mushroom flatbread",
    "Double espresso shot", "Twenty layer crepe cake",
]


@pytest.mark.parametrize("item, equipment", HOOD_ITEMS)
def test_items_that_need_a_hood_are_out_in_a_light_kitchen(item, equipment):
    rules = constraints.parse("light-prep kitchen with no extraction hood")
    assert rules.hood_free and rules.item_problem(item) == f"needs {equipment} under an extraction hood"
    assert constraints.parse("").allows_item(item)  # a full kitchen, or none said, allows them


@pytest.mark.parametrize("item", HOOD_FREE_ITEMS)
def test_baked_and_cold_items_stay_in_a_light_kitchen(item):
    assert constraints.parse("no hood").allows_item(item)


def test_no_kitchen_means_nothing_cooked_at_all():
    rules = constraints.parse("no kitchen")
    assert rules.no_cooking and rules.hood_free
    for item in ("Avocado toast", "Matcha ramen", "Baked oats", "Shakshuka", "Crispy potatoes", "Waffles"):
        assert rules.item_problem(item) == "needs cooking, and the unit has no kitchen", item
    for item in ("Iced latte", "Croissant", "Caesar salad", "Fruit smoothie", "Chocolate truffles", "No-bake cheesecake"):
        assert rules.allows_item(item), item


def test_the_unit_in_the_form_is_a_rule_too_and_the_stricter_kitchen_wins():
    rules = constraints.parse("")
    rules.adopt_unit(45, "light")
    assert rules.hood_free and rules.size_m2 == 45 and not rules.allows_item("Crispy potatoes")
    assert rules.as_evidence()["no_hood"].startswith("no item that needs an extraction hood")
    full = constraints.parse("full kitchen")
    full.adopt_unit(None, "light")
    assert full.kitchen == "light"
    bare = constraints.parse("no kitchen")
    bare.adopt_unit(None, "full")
    assert bare.kitchen == "none"
    hoodless = constraints.parse("we are not allowed a hood")
    assert hoodless.no_hood and hoodless.kitchen == "light"


def test_hood_items_taken_from_loved_places_are_replaced_by_hood_free_ones():
    run = world("vegetarian menu only", size_m2=45, kitchen="light")
    row = concepts.gap_for(run, "Cocktail bar")
    # The evidence itself never offers what the rules forbid.
    assert [i["item"] for i in concepts.offer_items(row, run.constraints)] == ["Banana espresso martini", "Deviled eggs"]
    kept, removed = concepts.ruled_signature(["Crispy potatoes", "Banana espresso martini", "Truffle pizza", "Grilled octopus"],
                                             row, run)
    assert kept == ["Banana espresso martini", "Deviled eggs"]
    assert removed == [("Crispy potatoes", "needs a deep fryer under an extraction hood"),
                       ("Truffle pizza", "needs a pizza oven under an extraction hood"),
                       ("Grilled octopus", "has meat or fish")]


def test_a_replacement_never_repeats_an_item_the_concept_has():
    run = world("no hood")
    kept, removed = concepts.ruled_signature(["Ube lattes", "Churros"], concepts.gap_for(run, "Coffee shop"), run)
    assert kept == ["Ube lattes", "Orange olive oil muffin"] and [item for item, _ in removed] == ["Churros"]
    assert concepts.same_item("Wine flights", "Wine flight tasting") and not concepts.same_item("Mulled wine", "Wine flights")


def test_a_concept_that_loses_its_signature_is_dropped_and_the_notes_say_why():
    run = world("no hood", rows=[cocktail_bar(), coffee_shop(), burger_joint()])
    # Every item the loved coffee shops are known for is fine, so a bad signature is replaced, not dropped ...
    notes: list[str] = []
    kept = concepts.clean_concepts(run, [model_concept("Sugar Rush", "Coffee shop", ["Churros", "Fried dough"])], notes)
    assert kept[0]["signature"] == ["Ube latte", "Orange olive oil muffin", "Cardamom bun"]
    # ... but when nothing they are known for works without a hood, the concept goes.
    for entity in concepts.gap_for(run, "Coffee shop")["_favorite_entities"]:
        entity["tags"] = [t for t in entity["tags"] if t["type"] != MENU] + [
            {"id": f"{MENU}:churros", "name": "Churros", "type": MENU}]
    notes.clear()
    assert concepts.clean_concepts(run, [model_concept("Sugar Rush", "Coffee shop", ["Churros", "Fried dough"])], notes) == []
    assert notes[-1] == ("Dropped Sugar Rush (Coffee Shop): nothing on its menu works under your rules, and the places "
                         "people here love offer nothing that does.")
    assert concepts.loses_signature(run, concepts.gap_for(run, "Coffee shop"))


def test_a_one_liner_that_promises_what_the_rules_forbid_gives_way_to_the_evidence():
    run = world("light kitchen")
    notes: list[str] = []
    line = "Espresso by day with spicy fried chicken sandwiches and loaded fries"
    cleaned = concepts.clean_concepts(run, [model_concept("Night Owl", "Coffee shop", ["Ube latte"], line)], notes)
    assert cleaned[0]["one_liner"] == concepts.one_liner(concepts.gap_for(run, "Coffee shop"), 10)
    assert notes == ["Night Owl: its one-liner mentioned 'fried', which needs a deep fryer under an extraction hood; the "
                     "evidence's own line replaces it."]


def test_each_concept_states_its_hood_free_method():
    run = world("no extraction hood", kitchen="light")
    assert concepts.kitchen_line(run, "Coffee shop", ["Ube latte", "Orange olive oil muffin"]) == (
        "No hood needed: drinks are made at the counter and the food is baked in a ventless oven; nothing is fried, "
        "grilled or cooked on a flat-top."
    )
    assert concepts.kitchen_line(run, "Cocktail bar", ["Banana espresso martini", "Deviled eggs"]) == (
        "No hood needed: drinks are made at the bar and the food is assembled cold; nothing is fried, grilled or cooked "
        "on a flat-top."
    )
    assert concepts.kitchen_line(run, "Bookstore", []) == "Needs no hood: nothing is cooked."
    assert concepts.kitchen_line(world("no kitchen"), "Juice bar", ["Green juice"]).startswith(
        "Needs no kitchen: nothing is cooked on site")
    assert concepts.kitchen_line(world(""), "Coffee shop", ["Ube latte"]) is None


def test_the_rules_are_stated_as_hard_rules_to_the_model():
    for words in ("Hard rules", "price_level 1 ($)", "deep fryer", "pizza oven", "Breakfast, Zamalek", "people here"):
        assert words in concepts.CONCEPT_SYSTEM, words
    assert "locals" not in concepts.CONCEPT_SYSTEM.replace('never "locals"', "")
    assert "ventless oven" in design.DESIGN_SYSTEM and "price_level is 1" in design.DESIGN_SYSTEM
    rules = constraints.parse("halal, family friendly, budget prices").as_evidence()
    assert rules["budget"].startswith("price_level 1 ($) only") and rules["price_levels_allowed"] == [1]


# ---------- Size ----------

def test_each_concept_says_how_it_fits_the_unit():
    run = world("vegetarian", size_m2=45, kitchen="light")
    assert concepts.unit_line(run, "Cocktail bar") == "Fits 45 m² (484 ft²): a bar counter and about 20–24 seats at most."
    assert concepts.unit_line(run, "Coffee shop") == "Fits 45 m² (484 ft²): a counter and about 20–24 seats at most."
    assert concepts.unit_line(run, "Live music venue") == (
        "Fits 45 m² (484 ft²): a bar along one wall and room for about 62–72 standing guests at most.")
    assert concepts.unit_line(run, "Bookstore") == "Fits 45 m² (484 ft²): a shop floor with a counter."
    assert concepts.unit_line(world(""), "Coffee shop") is None
    # A size written only in the notes counts too.
    assert concepts.unit_line(world("a unit of about 60 m²"), "Coffee shop").startswith("Fits 60 m² (646 ft²)")
    for concept in concepts.rule_concepts(run):
        assert concept["owner_rules"][0].startswith("Fits 45 m² (484 ft²)")
        assert concept["owner_rules"][1].startswith("No hood needed")
        assert "Vegetarian: no meat or fish on the menu." in concept["owner_rules"]


# ---------- Diet, halal, families ----------

def test_diet_halal_and_family_rules_still_hold():
    veg = constraints.parse("vegetarian menu only")
    assert veg.allows_genre("Seafood") == (False, "serves meat or fish")
    assert veg.allows_genre("Steak house")[0] is False and veg.allows_genre("Vegan burger joint")[0] is True
    assert veg.allows_genre("Coffee shop")[0] and not veg.allows_item("Grilled octopus")
    # Goat's cheese is no meat, and a plant 'steak' or vegan 'chicken' is no meat either; goat curry is.
    for item in ("Mediterranean flatbread with goat cheese", "Cauliflower steak", "Vegan chicken nuggets", "Bean burger"):
        assert veg.allows_item(item), item
    assert veg.item_clash("Goat curry") == ("Goat", "has meat or fish")
    assert not constraints.parse("vegetarian, no hood").allows_item("Cauliflower wings")  # still fried
    # What an item says it is made without is not held against it; what it still has is.
    for item in ("Anchovy-free Caesar salad", "Caesar salad, no anchovies", "Fish\u2011free sushi rolls"):
        assert veg.allows_item(item), item
    assert veg.item_clash("Brisket\u2011free charcuterie board") == ("charcuterie", "has meat or fish")
    assert veg.item_clash("Chicken salad, no bacon") == ("Chicken", "has meat or fish")
    halal = constraints.parse("halal, family friendly")
    assert not halal.allows_item("Mulled wine") and not halal.allows_item("Bacon roll")
    assert not halal.allows_item("Alcohol-free wine")  # still wine
    assert halal.allows_item("Mushroom bao, no pork")
    assert halal.allows_genre("Cocktail bar") == (False, "serves alcohol")
    assert halal.allows_item("Double espresso shot")  # an espresso shot is not a drink of alcohol
    run = world("halal, family friendly, budget prices", rows=[cocktail_bar(), coffee_shop(), burger_joint()])
    built = concepts.rule_concepts(run)
    assert "Cocktail bar" not in [c["genre"] for c in built]
    assert all({"Halal: no pork and no alcohol.", "Family friendly: no bar and no nightlife."} <= set(c["owner_rules"])
               for c in built)


# ---------- Names ----------

@pytest.mark.parametrize("name, genre, label, placeholder", [
    ("Breakfast, Zamalek", "Breakfast", "Zamalek, Cairo", True),
    ("Zamalek Cafe", "Cafe", "Zamalek, Cairo", True),
    ("Zamalek Café", "Cafe", "Zamalek, Cairo", True),
    ("The Wine Bar", "Wine Bar", "Williamsburg, Brooklyn", True),
    ("Seafood, Test Corner", "Seafood", "Test Corner, Testville", True),
    ("", "Cafe", "Zamalek, Cairo", True),
    ("Nile Courtyard Cafe", "Cafe", "Zamalek, Cairo", False),
    ("Ube & Oak", "Coffee shop", "Williamsburg, Brooklyn", False),
    ("Daybreak Table", "Breakfast", "Zamalek, Cairo", False),
])
def test_placeholder_names_are_recognized(name, genre, label, placeholder):
    assert concepts.placeholder_name(name, genre, label) is placeholder


def test_every_concept_gets_a_real_name():
    run = world("budget", label="Zamalek, Cairo")
    built = concepts.rule_concepts(run)
    names = [c["name"] for c in built]
    assert len(set(names)) == len(names)
    assert not any(concepts.placeholder_name(c["name"], c["genre"], run.site.label) or "," in c["name"] for c in built)
    assert names == [c["name"] for c in concepts.rule_concepts(run)]  # the same site gets the same names
    notes: list[str] = []
    renamed = concepts.clean_concepts(run, [model_concept("Coffee Shop, Zamalek", "Coffee shop", ["Ube latte"])], notes)
    assert not concepts.placeholder_name(renamed[0]["name"], "Coffee shop", run.site.label)
    assert notes == [f"Coffee Shop, Zamalek was renamed {renamed[0]['name']}: it was only the category and the place."]


def test_an_invented_name_never_reuses_an_existing_place():
    run = world("")
    first_choice = concepts.invent_name(run, "Coffee shop", set())
    run.block.append(venue(first_choice, "Coffee shop", 99, 2, km=0.1))
    assert concepts.invent_name(run, "Coffee shop", set()) != first_choice


@pytest.mark.parametrize("place", ["Golden Hour Bakery", "Cafe Golden Hour", "Café Golden Hour", "The Golden Hour Co."])
def test_a_name_is_taken_by_a_place_with_the_same_name_and_a_category_word(place):
    places = {place, "Otis"}
    assert concepts.taken_name("Golden Hour", places) == place
    assert concepts.taken_name("Golden Hour Coffee", places) == place
    assert concepts.taken_name("Otis & Main", places) == "Otis"
    assert concepts.taken_name("Golden", places) is None  # a shorter name is another name
    assert concepts.taken_name("The Bakery", places) is None  # category words alone are anyone's
    assert concepts.taken_name("Sunbeam", places) is None


def test_a_model_name_taken_by_a_place_with_a_category_word_is_replaced():
    run = world("")
    run.block.append(venue("Golden Hour Bakery", "Bakery", 99, 2, km=0.1))
    notes: list[str] = []
    renamed = concepts.clean_concepts(run, [model_concept("Golden Hour", "Coffee shop", ["Ube latte"])], notes)
    assert renamed[0]["name"] != "Golden Hour"
    assert notes == [f"Golden Hour was renamed {renamed[0]['name']}: it reused the existing place Golden Hour Bakery."]
    first_choice = concepts.invent_name(run, "Coffee shop", set())
    run.block.append(venue(f"Cafe {first_choice.removesuffix(' Coffee')}", "Cafe", 98, 2, km=0.1))
    assert concepts.invent_name(run, "Coffee shop", set()) != first_choice


# ---------- The agent's answer is checked ----------

def test_the_agents_concepts_are_repaired_or_dropped_and_the_payload_says_why():
    submit = [tool_call("c1", "submit_concepts", {"concepts": [
        {"name": "Tide & Table", "genre": "Seafood", "one_liner": "Raw bar", "price_level": 3,
         "signature": ["Oysters", "Fried calamari"]},
        {"name": "Corner Pour", "genre": "Wine Bar", "one_liner": "Natural wine", "signature": ["Orange wine"]},
        {"name": "Breakfast, Test Corner", "genre": "Brunch", "one_liner": "Eggs all day", "signature": ["Croissant"]},
        {"name": "Ghost Kitchen", "genre": "Not A Genre", "one_liner": "?", "signature": []},
    ]})]
    params = {**RUN_PARAMS, "notes": "halal, budget prices"}
    with make_client(llm=scripted_llm([submit])) as client:
        events = sse_events(client.get("/api/run", params=params).text)
    payload = first(events, "concepts")
    assert payload["mode"] == "agent"
    ranked = [c for c in payload["concepts"] if not c.get("wildcard")]
    assert "Wine Bar" not in [c["genre"] for c in ranked] and all(c["price_level"] == 1 for c in ranked)
    notes = payload["notes"]
    assert "Dropped Corner Pour (Wine Bar): your notes rule it out (it serves alcohol)." in notes
    assert "Tide & Table: priced $ for your budget, not $$$." in notes
    assert any(note.startswith("Breakfast, Test Corner was renamed ") for note in notes)
    assert "Dropped Ghost Kitchen: 'Not A Genre' is not a category the survey measured." in notes
    assert not any(c["name"] == "Breakfast, Test Corner" for c in payload["concepts"])


def test_a_submission_sent_as_a_json_string_is_read():
    assert concepts.submitted({"concepts": '[{"name": "A", "genre": "Cafe"}]'}, "concepts") == [{"name": "A", "genre": "Cafe"}]
    assert concepts.submitted({"concepts": "not json"}, "concepts") is None
    assert concepts.submitted(None, "wildcard") is None


# ---------- Design sheets ----------

class DesignLLM:
    """A model that writes a design sheet breaking every rule it can."""

    enabled = True

    def __init__(self, reply: dict) -> None:
        self.reply = reply

    async def complete_json(self, system: str, user: str):
        return dict(self.reply), "test-model"


def test_design_sheets_keep_the_rules_the_model_breaks():
    run = world("vegetarian, budget prices, no extraction hood", size_m2=45, kitchen="light")
    run.concepts = concepts.rule_concepts(run)
    index = next(i for i, c in enumerate(run.concepts) if c["genre"] == "Cocktail bar")
    reply = {
        "name": "Cocktail Bar, Williamsburg", "tagline": "Premium small plates and an upscale cocktail list",
        "interior": {"mood": "moody", "materials": ["brass"], "lighting": "low", "seating": "stools",
                     "layout": "Open kitchen with a wood-fired oven behind the bar"},
        "offer": ["Banana espresso martini", "Truffle pizza", "Crispy potatoes", "Grilled octopus"], "price_level": 3,
        "music": {}, "partners": [], "image_prompt": "A bar with a glowing wood-fired pizza oven and a range hood",
    }
    sheet = asyncio.run(design.design_concept(DesignLLM(reply), FakeImages(enabled=False), run, index))
    assert sheet["name"] == run.concepts[index]["name"]
    assert sheet["offer"][:2] == ["Banana espresso martini", "Deviled eggs"] and "Truffle pizza" not in sheet["offer"]
    assert sheet["price_level"] == 1 and "Budget, as your notes ask: $" in sheet["price_basis"]
    assert sheet["tagline"] == run.concepts[index]["one_liner"]
    assert sheet["interior"]["layout"] == (
        "Long bar along one wall, low tables by the window; behind the counter, a compact ventless oven and a cold-prep "
        "counter"
    )
    assert "wood-fired" not in sheet["shots"][0]["prompt"] and "compact ventless oven" in sheet["shots"][0]["prompt"]
    assert sheet["owner_rules"][0] == "Fits 45 m² (484 ft²): a bar counter and about 20–24 seats at most."
    assert any(note.startswith("Took out of the offer Truffle pizza") for note in sheet["notes"])


def test_a_rules_made_sheet_for_a_unit_without_a_hood_has_no_cooking_line():
    run = world("no hood", size_m2=45)
    run.concepts = concepts.rule_concepts(run)
    sheet = asyncio.run(design.design_concept(LLM("", None, "test-model"), FakeImages(enabled=False), run, 0))
    assert sheet["interior"]["layout"].endswith("behind the counter, a compact ventless oven and a cold-prep counter")
    assert all(constraints.parse("no hood").allows_item(item) for item in sheet["offer"])
    assert design.shows_hood_fixtures("An open grill and a fryer") and not design.shows_hood_fixtures("no hood, no grill")
