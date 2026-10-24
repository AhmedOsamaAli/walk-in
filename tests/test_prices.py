"""Prices: Qloo's levels are dollar signs with no amounts behind them, so nothing shows one. A place's card still links
its own menu or website, where its real prices are."""
from app import scoring
from tests.fakes import place


def bar(name: str, level: int, index: int, **props) -> dict:
    entity = place(name, "Cocktail Bar", 40.0 + index / 1000, -73.0, index)
    entity["properties"].update({"price_level": level, **props})
    return entity


CORNER = bar("Corner Pour", 2, 2)
LOVED = [
    bar("Velvet Room", 3, 0, website="https://velvet.example/"),
    bar("Brass Owl", 3, 1, website="https://owl.example/", menu_url="https://owl.example/menu"),
    CORNER,
    bar("Gin Lab", 3, 3),
]
INSIDE = [bar("Dive One", 1, 4), bar("Dive Two", 1, 5, website="http://divetwo.example/"), CORNER]


def test_no_card_summary_or_dna_carries_a_price_level():
    card = scoring.place_card(LOVED[1])
    assert "price_level" not in card and "$" not in str(card)
    summary = scoring.summarize_block(LOVED + INSIDE)
    assert "price_levels" not in summary and not any("price_level" in c for c in summary["classics"])
    assert "typical_price_level" not in scoring.design_dna(LOVED)


def test_place_cards_link_to_the_menu_and_never_to_a_script():
    assert (scoring.place_card(LOVED[1])["url"], scoring.place_card(LOVED[1])["link"]) == ("https://owl.example/menu", "menu")
    unsafe = bar("Trap", 2, 9, website="javascript:alert(1)")
    assert scoring.place_link(unsafe) == (None, None) and scoring.place_card(unsafe)["url"] is None
