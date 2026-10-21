from app.survey import intents


def place(name, price=None, rating=None, tags=(), keywords=(), hours=None):
    return {
        "entity_id": name.lower().replace(" ", "-"),
        "name": name,
        "tags": [{"type": t, "name": n} for t, n in tags],
        "properties": {
            "price_level": price, "business_rating": rating, "keywords": [{"name": k, "count": 1} for k in keywords],
            **({"hours": hours} if hours else {}),
        },
    }


AMENITY = "urn:tag:amenity:qloo"
OFFERING = "urn:tag:offerings:qloo"


def row_with(favorites, nearby=()):
    return {
        "genre": "Mexican", "genre_id": "g", "favorites_kind": "local", "favorites_far": 1, "favorites_total": 4,
        "leakage": 0.3, "median_favorite_km": 2.0, "_favorite_entities": list(favorites), "_nearby_entities": list(nearby),
        "favorites": [{"name": f["name"]} for f in favorites],
    }


def casual(name):
    return place(name, price=1, rating=4.5, tags=[(AMENITY, "Drive through"), (AMENITY, "Live music"), (OFFERING, "Hot tea"),
                                                   (OFFERING, "Vegan meals")])


def test_an_upscale_place_is_not_told_to_copy_fast_casual_favorites():
    upscale = place("Fine Mex", price=4, rating=4.6)
    row = row_with([casual(f"Taco {i}") for i in range(4)])
    comparison = intents.compare(upscale, row)
    # Too few favorites share its price, so all count, the label says so, and they are not a guide.
    assert comparison["peers_label"] == "places locals love" and comparison["peers"] == 4
    assert comparison["comparable"] is False
    # Building-bound amenities and trivial offerings are never listed.
    assert [i["name"] for i in comparison["offer"]["amenities"]["missing"]] == ["Live music"]
    assert [i["name"] for i in comparison["offer"]["offerings"]["missing"]] == ["Vegan meals"]
    titles = {m["title"]: m["why"] for m in intents.moves("Fine Mex", row, comparison, None)}
    assert titles == {"Own the high end": (
        "Few of the Mexican places locals love are priced like Fine Mex ($$$$); most are $. Fine Mex is the upscale "
        "option, so their offer and hours are no guide."
    )}


def test_a_comparable_place_gets_offer_and_rating_suggestions():
    taco = place("Corner Taco", price=1, rating=3.9, keywords=["al pastor", "slow service", "corner"])
    row = row_with([casual(f"Taco {i}") for i in range(4)])
    comparison = intents.compare(taco, row)
    assert comparison["comparable"] is True and comparison["known_for"] == ["al pastor"]  # "corner" repeats its name
    assert [g["label"] for g in comparison["complaints"]] == ["Slow service"]
    moves = intents.moves("Corner Taco", row, comparison, None)
    assert [m["title"] for m in moves] == ["Fix what reviews flag", "Consider vegan meals", "Consider live music", "Close the rating gap"]
    assert moves[0]["why"] == "Reviews of Corner Taco flag slow service."


def test_complaint_moves_name_each_theme_with_examples():
    themes = [
        {"label": "Long waits and lines", "mentions": 189, "places": 1, "keywords": ["long lines", "wait time", "on line"]},
        {"label": "Noise", "mentions": 20, "places": 1, "keywords": ["loud music"]},
    ]
    assert intents.flagged(themes) == "long waits and lines (long lines, wait time) and noise (loud music)"


def test_peers_at_a_similar_price_are_preferred():
    mid = place("Mid Mex", price=2)
    favorites = [casual("Taco 1"), place("Cantina 2", price=2), place("Cantina 3", price=3), place("Cantina 4", price=2)]
    peers, label = intents.peers_of(mid, row_with(favorites))
    assert label == "places locals love at a similar price" and len(peers) == 4  # $ to $$$ are all within one level
    peers, label = intents.peers_of(place("Top Mex", price=4), row_with(favorites))
    assert label == "places locals love" and len(peers) == 4


def test_weakness_names_the_main_reason():
    base = {"demand_rank": 5, "relative_supply": 0.9, "lift": 0.0}
    assert intents.weakness({**base, "demand_rank": 51}) == "locals do not rank it among their top 50 place types"
    assert intents.weakness({**base, "demand_rank": 25}) == "locals rank it only #25 among place types"
    assert intents.weakness({**base, "relative_supply": 1.5}) == "the block already has more of it than its density predicts"
    assert intents.weakness({**base, "lift": -0.5}) == "locals rank it lower than the areas around do"
    assert intents.weakness(base) == "demand and supply here are close to what the areas around show"
