"""Prices: Qloo's four levels made concrete with real places, and the level the walk leaves open."""
from app import scoring
from app.survey.evidence import open_price_note, price_anchors, price_evidence, price_ladder
from tests.fakes import place


def bar(name: str, level: int, index: int, **props) -> dict:
    entity = place(name, "Cocktail Bar", 40.0 + index / 1000, -73.0, index)
    entity["properties"].update({"price_level": level, **props})
    return entity


def row_of(loved: list[dict], inside: list[dict]) -> dict:
    return {
        "genre": "Cocktail Bar", "genre_id": loved[0]["tags"][0]["id"],
        "_favorite_entities": loved, "favorites": [scoring.place_card(e) for e in loved], "_nearby_entities": inside,
    }


CORNER = bar("Corner Pour", 2, 2)
LOVED = [
    bar("Velvet Room", 3, 0, website="https://velvet.example/"),
    bar("Brass Owl", 3, 1, website="https://owl.example/", menu_url="https://owl.example/menu"),
    CORNER,
    bar("Gin Lab", 3, 3),
]
INSIDE = [bar("Dive One", 1, 4), bar("Dive Two", 1, 5, website="http://divetwo.example/"), CORNER]


def test_the_ladder_counts_each_level_for_loved_places_and_the_walk():
    assert price_ladder(row_of(LOVED, INSIDE)) == [
        {"level": 1, "loved": 0, "inside": 2},
        {"level": 2, "loved": 1, "inside": 1},
        {"level": 3, "loved": 3, "inside": 0},
        {"level": 4, "loved": 0, "inside": 0},
    ]


def test_a_level_people_here_love_that_the_walk_lacks_is_called_open():
    row = row_of(LOVED, INSIDE)
    assert open_price_note(row, price_ladder(row)) == (
        "No $$$ cocktail bar inside the walk, while 3 of the 4 cocktail bars people here love are $$$: "
        "that price level is open."
    )
    # With no priced competitor inside the walk, the whole category is the gap, not one price level.
    empty = row_of(LOVED, [])
    assert open_price_note(empty, price_ladder(empty)) is None
    # One loved place at a level is an example, not a pattern.
    single = row_of([LOVED[0], CORNER], INSIDE)
    assert open_price_note(single, price_ladder(single)) is None


def test_anchors_are_real_places_at_the_level_with_their_menu_first():
    row = row_of(LOVED, INSIDE)
    anchors = price_anchors(row, 3)
    assert [(a["name"], a["link"]) for a in anchors] == [("Velvet Room", "site"), ("Brass Owl", "menu"), ("Gin Lab", None)]
    assert anchors[1]["url"] == "https://owl.example/menu" and not any(a["within_walk"] for a in anchors)
    cheap = price_anchors(row, 1)
    assert [(a["name"], a["url"], a["within_walk"]) for a in cheap] == [
        ("Dive Two", "http://divetwo.example/", True), ("Dive One", None, True),
    ]
    assert price_anchors(row, None) == []


def test_price_evidence_carries_the_ladder_the_open_level_and_anchors_for_its_level():
    price = price_evidence(row_of(LOVED, INSIDE))
    assert price["level"] == 3 and len(price["ladder"]) == 4
    assert price["open_note"].startswith("No $$$ cocktail bar")
    assert [a["name"] for a in price["anchors"]] == ["Velvet Room", "Brass Owl", "Gin Lab"]


def test_place_cards_link_to_the_menu_and_never_to_a_script():
    assert (scoring.place_card(LOVED[1])["url"], scoring.place_card(LOVED[1])["link"]) == ("https://owl.example/menu", "menu")
    unsafe = bar("Trap", 2, 9, website="javascript:alert(1)")
    assert scoring.place_link(unsafe) == (None, None) and scoring.place_card(unsafe)["url"] is None
