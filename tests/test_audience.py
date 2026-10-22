"""Who a concept is for: Qloo's customer tags on the places locals love, and a demand rank only when it is a reason."""
from app import scoring
from app.survey.concepts import for_whom
from app.survey.evidence import crowd_of, in_running_text
from tests.fakes import place

CROWD = "urn:tag:customer_identity:qloo"


def bakery(name: str, index: int, *crowd: str) -> dict:
    entity = place(name, "Bakery", 30.26 + index / 1000, -97.72, index)
    entity["tags"] += [{"id": f"urn:tag:customer_identity:qloo:{c.lower()}", "name": c, "type": CROWD} for c in crowd]
    return entity


LOVED = [
    bakery("Crumb", 0, "Families", "Locals", "Couples"),
    bakery("Rise", 1, "Families", "Foodies", "Locals"),
    bakery("Proof", 2, "Families", "Couples"),
    bakery("Knead", 3, "Students"),
]


def row(rank: int, **extra) -> dict:
    return {
        "genre": "Bakery", "genre_id": LOVED[0]["tags"][0]["id"], "demand_rank": rank, "favorites_kind": "citywide",
        "favorites_far": 0, "_favorite_entities": LOVED, "favorites": [scoring.place_card(e) for e in LOVED], **extra,
    }


def test_the_crowd_is_what_most_of_the_loved_places_draw_and_never_just_locals():
    assert crowd_of(row(21)) == ["Families", "Couples"]
    assert in_running_text("Groups of friends") == "groups of friends" and in_running_text("LGBTQ+ community") == "LGBTQ+ community"


def test_a_weak_rank_is_not_sold_as_a_reason_but_the_crowd_is():
    assert for_whom(row(21), 10) == "Neighbors within a 10-minute walk; the bakeries locals love draw families and couples"
    assert for_whom(row(4), 10) == (
        "Neighbors within a 10-minute walk, who rank bakery #4 among the place types they engage with; "
        "the bakeries locals love draw families and couples"
    )


def test_no_crowd_line_when_the_places_share_no_customer_tag():
    lonely = {**row(30), "_favorite_entities": LOVED[3:], "favorites": [scoring.place_card(LOVED[3])]}
    assert crowd_of(lonely) == [] and for_whom(lonely, 10) == "Neighbors within a 10-minute walk"
