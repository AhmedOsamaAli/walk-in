from app import scoring


def place(name, genres=(), keywords=(), rating=None, price=None, reviews=None, lat=None, lon=None, extra_tags=(),
          michelin=None, hours=None):
    tags = [{"id": f"urn:tag:genre:place:{g.lower().replace(' ', '_')}", "name": g, "type": "urn:tag:genre:place"} for g in genres]
    tags += [{"id": f"{t}:{n.lower().replace(' ', '_')}", "name": n, "type": t} for t, n in extra_tags]
    external = {}
    if reviews is not None:
        external["tripadvisor"] = [{"id": "d1", "rating": 4.5, "rating_count": reviews}]
    if michelin is not None:
        external["michelin"] = [{"id": "m1", "stars": michelin or None}]
    entity = {
        "entity_id": name.lower().replace(" ", "-"),
        "name": name,
        "tags": tags,
        "properties": {
            "keywords": [{"name": k, "count": c} for k, c in keywords],
            "business_rating": rating,
            "price_level": price,
            **({"hours": hours} if hours else {}),
        },
        "external": external,
    }
    if lat is not None:
        entity["location"] = {"lat": lat, "lon": lon}
    return entity


def kind(keyword: str, setting: str = "food") -> str | None:
    found = scoring.topic(keyword, setting)
    return found[0] if found else None


def test_complaint_detection():
    assert scoring.topic("slow service") == ("complaint", "Slow service")
    assert scoring.topic("long wait") == ("complaint", "Long waits and lines")
    assert scoring.topic("touts") == ("complaint", "Touts and tourist traps")
    assert scoring.topic("outdoor seating") == ("experience", "Outdoor seating")
    assert kind("airlines lounge") != "complaint"


def test_review_keywords_that_repeat_the_name_or_address_are_dropped():
    cafe = place("Zamalek Corner Cafe", ["Cafe"], keywords=[("zamalek", 9), ("koshari", 4), ("corner", 2), ("rude waiters", 1),
                                                             ("el zamalek", 3)])
    cafe["properties"]["address"] = "26th of July St, Zamalek, Cairo"
    assert [k["name"] for k in scoring.review_keywords(cafe)] == ["koshari", "rude waiters"]
    card = scoring.place_card(cafe)
    assert card["known_for"] == ["koshari"] and card["complaints"] == ["rude staff"]
    # A keyword is dropped only when it repeats a whole word: "tea" is not in "Steak House".
    steak = place("Steak House", ["Steak house"], keywords=[("tea", 2), ("house", 1)])
    assert [k["name"] for k in scoring.review_keywords(steak)] == ["tea"]


def test_string_keywords_do_not_crash():
    # Movies and shows carry keywords as plain strings, sometimes next to records.
    film = {"entity_id": "f1", "name": "Heist Film", "properties": {"keywords": ["heist", "drama", {"name": "oysters", "count": 2}]}}
    assert scoring.review_keywords(film) == [{"name": "oysters", "count": 2}]
    assert scoring.place_card(film)["known_for"] == []
    assert scoring.summarize_block([film, {"name": "Bare", "properties": {"keywords": ["x", None, 3]}}])["menu"] == []


def test_menu_items_with_complaint_words_are_not_complaints():
    assert kind("dirty martinis") == kind("dirty chai") == "menu"
    assert scoring.topic("friendly wait staff") == ("experience", "Friendly staff")
    assert scoring.topic("dirty tables") == ("complaint", "Hygiene")


def test_negated_complaints_are_not_complaints():
    assert scoring.topic("not crowded") == ("experience", "Spacious")
    assert scoring.topic("no wait") == ("experience", "Short waits")
    assert scoring.topic("crowded") == ("complaint", "Crowding")


def test_the_users_example_collapses_into_four_complaint_themes():
    words = [("long lines", 117), ("wait time", 65), ("crowded", 50), ("loud music", 20), ("on line", 5),
             ("long wait times", 2), ("rude bartender", 2)]
    summary = scoring.summarize_block([place("Busy Bar", ["Bar"], words)])
    assert summary["complaints"] == [
        {"label": "Long waits and lines", "mentions": 189, "places": 1,
         "keywords": ["long lines", "wait time", "on line", "long wait times"]},
        {"label": "Crowding", "mentions": 50, "places": 1, "keywords": ["crowded"]},
        {"label": "Noise", "mentions": 20, "places": 1, "keywords": ["loud music"]},
        {"label": "Rude staff", "mentions": 2, "places": 1, "keywords": ["rude bartender"]},
    ]
    assert summary["menu"] == [] and summary["experience"] == []


def test_complaint_look_alikes_are_never_complaints():
    look_alikes = [
        "short wait time", "short wait times", "quick lines", "fast line", "fast moving lines", "no long lines", "sight lines",
        "clean lines", "line dancing", "line skipping", "ready to wait", "free parking", "valet parking", "pork belly burnt ends",
        "salty honey pie", "burnt butter pecan", "dirty circus", "fixing bad haircuts", "bad bunny theme", "lineup", "slow cooked",
        "gummy worms",
    ]
    assert [word for word in look_alikes if kind(word) == "complaint"] == []
    assert {word: scoring.topic(word) for word in ("short wait time", "quick lines", "no long lines")} == {
        "short wait time": ("experience", "Short waits"), "quick lines": ("experience", "Short waits"),
        "no long lines": ("experience", "Short waits"),
    }
    assert scoring.topic("line dancing") == ("experience", "Live music and DJs")
    assert kind("pork belly burnt ends") == kind("salty honey pie") == kind("burnt butter pecan") == "menu"
    # Free and valet parking are neither a parking complaint nor a dish; plain "parking" is the complaint.
    assert scoring.topic("free parking") is None and scoring.topic("valet parking") is None
    assert scoring.topic("parking") == ("complaint", "Parking")
    assert scoring.topic("limited seating") == ("complaint", "Crowding")
    assert scoring.topic("greasy pizza") == ("complaint", "Food quality") and kind("greasy spoon") != "complaint"


def test_neutral_topics_are_neither_menu_nor_experience():
    neutral = [
        "prices", "price", "cash only", "hotel", "school", "location", "floor", "bathroom", "security", "bouncer", "cashier",
        "service", "selection", "kids", "delivery", "online ordering", "crowd", "space", "party", "bar", "cafe", "restaurant",
        "coffee shop", "wine", "drinks", "food", "brunch", "great food", "michelin star", "portion size", "no reservations",
        "fine dining", "birthday party", "book selection", "cover charge",
    ]
    assert {word: scoring.topic(word) for word in neutral if scoring.topic(word)} == {}
    summary = scoring.summarize_block([place("Everything", ["Restaurant"], [(word, 10) for word in neutral])])
    assert summary["menu"] == summary["experience"] == summary["complaints"] == []


def test_spellings_of_a_dish_merge_under_its_most_mentioned_form():
    places = [
        place("A", ["Bakery"], [("croissants", 30), ("great croissants", 5), ("Crème brûlée", 4)]),
        place("B", ["Cafe"], [("croissant", 12), ("creme brulee", 6), ("egyptian food", 3), ("egyptian", 2)]),
    ]
    menu = scoring.summarize_block(places)["menu"]
    assert menu[0] == {"label": "croissants", "mentions": 47, "places": 2, "keywords": ["croissants", "croissant", "great croissants"]}
    assert menu[1] == {"label": "creme brulee", "mentions": 10, "places": 2, "keywords": ["creme brulee", "crème brûlée"]}
    assert menu[2]["label"] == "egyptian food" and menu[2]["keywords"] == ["egyptian food", "egyptian"]


def test_shops_and_services_have_no_menu_and_no_merchandise_themes():
    store = place("Gadget Store", ["Electronics store", "Shopping"], [("tvs", 40), ("helpful staff", 9), ("laptop", 5),
                                                                       ("mattress selection", 4)])
    barber = place("Sharp Barber", ["Barber shop", "Personal care"], [("fade", 12), ("clean", 3)])
    venue = place("Loud Room", ["Live music venue"], [("live music", 30), ("pierogis", 2)])
    assert scoring.place_card(store)["known_for"] == ["friendly staff"]
    assert scoring.place_card(barber)["known_for"] == ["cleanliness"]
    assert scoring.place_card(venue)["known_for"] == ["live music and DJs"]
    sports_bar = place("Game Bar", ["Sports bar"], [("tvs", 40), ("wings", 9)])
    assert scoring.place_card(sports_bar)["known_for"] == ["wings", "games and sports"]


def test_labels_read_inside_sentences():
    assert scoring.inline_label("Live music and DJs") == "live music and DJs"
    assert scoring.inline_label("DJs") == "DJs" and scoring.inline_label("oysters") == "oysters"
    assert scoring.natural_list(["a"]) == "a" and scoring.natural_list(["a", "b", "c"]) == "a, b and c"


def test_hotels_are_not_storefront_inspiration():
    hotel = place("Grand Hotel", ["Resort hotel"])
    cafe = place("Corner Cafe", ["Cafe"])
    assert not scoring.is_storefront_place(hotel)
    assert scoring.is_storefront_place(cafe)
    assert scoring.storefront_share([hotel, hotel, cafe]) == 1 / 3


def test_nonprofit_brands_are_not_partners():
    nonprofit = {"name": "Advocacy Org", "tags": [{"type": "urn:tag:brand_type:qloo", "name": "Nonprofit Brand"}]}
    shop = {"name": "Cider Co", "tags": [{"type": "urn:tag:brand_type:qloo", "name": "Beverage Brand"}]}
    assert not scoring.is_commercial_brand(nonprofit)
    assert scoring.is_commercial_brand(shop)


def test_signature_items_follow_the_kind_of_business():
    dna = {"menu": ["Ramen"], "offerings": ["Cocktails", "Live music"], "amenities": ["Massage"], "activities": ["Karaoke"]}
    assert scoring.signature_items("Japanese", dna)[0] == "Ramen"
    # Bars lead with offerings and activities; "Cocktails" says nothing about a bar, so specific items come first.
    assert scoring.signature_items("Lounge", dna) == ["Live music", "Karaoke", "Ramen"]
    assert scoring.signature_items("Spa", dna)[0] == "Live music"
    generic_first = {"offerings": ["Alcohol", "Beer", "Craft cider", "Trivia night"]}
    assert scoring.signature_items("Brewery", generic_first) == ["Craft cider", "Trivia night", "Alcohol"]
    assert scoring.genre_title("Fine dining restaurant") == "Fine Dining"
    assert scoring.genre_title("Tex-Mex") == "Tex-Mex"
    assert scoring.genre_title("New American") == "New American"


def test_signature_items_drop_items_contained_in_a_longer_one():
    dna = {"menu": ["Steak frites", "Steak", "steak frites", "Salmon burger", "Burger", "Fries"]}
    assert scoring.signature_items("Brunch", dna, limit=6) == ["Steak frites", "Salmon burger", "Fries"]
    # A generic tag never knocks out a specific item it happens to contain.
    assert scoring.signature_items("Diner", {"menu": ["Vegetarian"], "offerings": ["Vegetarian options"]}) == ["Vegetarian", "Vegetarian options"]


def test_generic_items_only_pad_short_lists():
    short = {"menu": ["Chicken and waffles", "Fries"], "offerings": ["Alcohol", "Wine", "Beer"]}
    assert scoring.signature_items("Brunch", short, limit=6) == ["Chicken and waffles", "Fries", "Alcohol"]
    longer = {"menu": ["Chicken and waffles", "Fries", "Grits", "Biscuits"], "offerings": ["Alcohol"]}
    assert scoring.signature_items("Brunch", longer, limit=6) == ["Chicken and waffles", "Fries", "Grits", "Biscuits"]


def test_venues_lead_with_what_people_go_there_to_do():
    dna = {
        "menu": ["Buffalo chicken wings", "Sliders"],
        "offerings": ["Cocktails", "Ok to order just drinks", "Alcohol"],
        "activities": ["Dining drinking", "Social community", "Nightlife", "Game day viewing", "Live entertainment"],
    }
    assert scoring.signature_items("Sports Bar", dna, limit=6) == [
        "Game day viewing", "Live entertainment", "Buffalo chicken wings", "Sliders",
    ]


def test_partner_brands_fit_the_business():
    def card(name, brand_type):
        return scoring.entity_card({"entity_id": name, "name": name, "tags": [{"type": "urn:tag:brand_type:qloo", "name": brand_type}]})

    brands = [card("Daily News", "Media Brand"), card("City FC", "Entertainment Brand"), card("Big Motors", "Corporate Brand"),
              card("Cider Co", "Product Brand"), card("Corner Books", "Retail Brand")]
    assert [b["kind"] for b in brands] == ["media", "entertainment", "corporate", "product", "retail"]
    assert [b["name"] for b in scoring.partner_brands(brands, "Seafood")] == ["Cider Co", "Corner Books"]
    assert [b["name"] for b in scoring.partner_brands(brands, "Sports Bar")] == ["City FC", "Cider Co", "Corner Books"]
    assert "kind" not in scoring.entity_card({"entity_id": "a", "name": "An Artist"})


def test_leakage_is_shrunk_for_small_samples():
    few = scoring.score_gaps([_row("Few", 3, 5, 4, 12, far=3, total=3)], 1.5e6, 6e6)[0]
    many = scoring.score_gaps([_row("Many", 3, 5, 4, 12, far=9, total=10)], 1.5e6, 6e6)[0]
    assert few["leakage"] == 0.8
    assert 0.8 < many["leakage"] < 0.9


def test_business_genre_filters_generic_and_cues():
    assert scoring.is_business_genre("Wine Bar")
    assert not scoring.is_business_genre("Restaurant")
    assert not scoring.is_business_genre("Art museum")
    assert scoring.is_taste_cue("Art museum")


def _row(name, local, ref, nearby, around, far=9, total=10, kind="local", storefront=1.0):
    return {
        "genre_id": name, "genre": name, "demand_rank": local, "ref_rank": ref,
        "nearby_count": nearby, "nearby_capped": False, "around_count": around, "around_capped": False,
        "favorites_kind": kind, "favorites_total": total, "favorites_far": far, "median_favorite_km": 3.0,
        "storefront_share": storefront,
    }


def test_gap_signals_counts_favorites_outside_the_walk():
    site = (40.7736, -73.9566)
    near_fav = place("Near", lat=40.7740, lon=-73.9560)
    far_fav = place("Far", lat=40.7200, lon=-73.9900)

    def within(lat, lon):
        return abs(lat - site[0]) < 0.005 and abs(lon - site[1]) < 0.005

    row = scoring.gap_signals(
        "g", "Wine Bar", 2, 10.0, [place("Comp")], [place("A"), place("B")], [near_fav, far_fav], "local", 0.9, site, within,
    )
    assert row["favorites_total"] == 2
    assert row["favorites_far"] == 1
    assert row["nearby_count"] == 1
    assert row["around_count"] == 2
    assert row["ref_rank"] == 10.0
    assert row["favorites_kind"] == "local"
    assert row["median_favorite_km"] is not None
    # The trip saved is measured over the far favorite only, not diluted by the one already close by.
    assert row["median_far_km"] == round(scoring.distance_m(*site, 40.7200, -73.9900) / 1000, 1)
    assert row["median_far_km"] > row["median_favorite_km"]


def test_score_gaps_prefers_local_lift_and_relative_undersupply():
    rows = [
        _row("Over-supplied staple", 1, 1, 30, 60),
        _row("Local favorite, few nearby", 3, 20, 1, 12),
        _row("Loved more around than here", 2, 1, 5, 20),
    ]
    scored = scoring.score_gaps(rows, catchment_area_m2=1.5e6, around_area_m2=6e6)
    assert scored[0]["genre"] == "Local favorite, few nearby"
    assert scored[-1]["genre"] == "Over-supplied staple"
    assert scored[0]["lift"] > 0
    assert all(0 <= row["gap_score"] <= 99 for row in scored)
    assert all("_ratio" not in row for row in scored)


def test_missing_reference_rank_is_neutral_not_a_boost():
    scored = scoring.score_gaps([_row("No refs", 3, None, 4, 12)], 1.5e6, 6e6)
    assert scored[0]["lift"] == 0.0


def test_score_gaps_ranks_thin_and_atypical_evidence_last():
    rows = [
        _row("Thin", 1, 30, 0, 1, far=0, total=0),
        _row("Hotel spas", 1, 30, 0, 4, storefront=0.2),
        _row("Solid", 5, 6, 2, 8),
    ]
    scored = scoring.score_gaps(rows, 1.5e6, 6e6)
    assert scored[0]["genre"] == "Solid"
    assert {row["genre"]: row["evidence"] for row in scored} == {"Thin": "thin", "Hotel spas": "atypical", "Solid": "ok"}


def test_citywide_favorites_do_not_count_as_leakage():
    scored = scoring.score_gaps([_row("Famous only", 3, 5, 4, 12, far=10, total=10, kind="citywide")], 1.5e6, 6e6)
    assert scored[0]["leakage"] is None


def test_relative_supply_is_normalised_by_site_baseline():
    # Every genre is 3x denser inside the walk than around it (e.g. the surroundings include a park),
    # so relative supply should come out near 1 for all of them.
    rows = [_row(f"G{i}", i + 1, i + 1, 3 * n, 4 * n) for i, n in enumerate([2, 3, 4, 5])]
    scored = scoring.score_gaps(rows, 1.5e6, 6e6)
    assert all(0.8 <= row["relative_supply"] <= 1.25 for row in scored)
    for row in scored:
        # The density-adjusted expectation should sit close to what is actually there.
        assert abs(row["expected_nearby"] - row["nearby_count"]) <= 0.25 * row["nearby_count"] + 1


def test_a_genre_tested_later_shares_the_table_baseline():
    # Area ratio 1/4: every row expects 2 places; supply ratios 1.0, 5/3 and 7/3, so the table's baseline is 5/3.
    table = scoring.score_gaps([_row("A", 1, 1, 2, 8), _row("B", 2, 2, 4, 8), _row("C", 3, 3, 6, 8)], 1.0, 4.0)
    late = scoring.score_gaps([_row("D", 4, 4, 2, 8)], 1.0, 4.0, baseline_rows=table)[0]
    assert late["relative_supply"] == 0.6
    assert scoring.score_gaps([_row("D", 4, 4, 2, 8)], 1.0, 4.0)[0]["relative_supply"] == 1.0


def test_demand_comparisons_are_stated_in_words_for_the_agent():
    from app.survey.evidence import demand_comparison, gap_summary

    assert demand_comparison({"demand_rank": 2, "ref_rank": 1.0}) == "about the same as in the areas around"
    assert demand_comparison({"demand_rank": 8, "ref_rank": 25.5}).startswith("ranked higher here")
    assert demand_comparison({"demand_rank": 9, "ref_rank": 3.0}).startswith("ranked lower here")
    assert demand_comparison({"demand_rank": 4, "ref_rank": None}) == "no comparison available"
    citywide = gap_summary(_row("Live music", 1, 2.5, 3, 12, far=10, total=10, kind="citywide") | {
        "expected_nearby": 3.9, "relative_supply": 0.82, "evidence": "ok", "gap_score": 63,
    })
    assert citywide["do_locals_travel_for_it"].startswith("no evidence")
    local = gap_summary(_row("Seafood", 7, 7.0, 5, 30, far=7, total=7) | {
        "expected_nearby": 8.1, "relative_supply": 0.66, "evidence": "ok", "gap_score": 55,
    })
    assert local["do_locals_travel_for_it"] == (
        "7 of the 7 places locals love more than the city does are outside the walk; median distance 3.0 km"
    )


def test_free_text_categories_normalize_to_genre_names():
    from app.engine import _normalize_genre

    assert _normalize_genre("Bakeries") == _normalize_genre("bakery")
    assert _normalize_genre("Wine  Bars") == _normalize_genre("Wine Bar")
    assert _normalize_genre("Seafood restaurant") == _normalize_genre("Seafood")
    assert _normalize_genre("Glass") == "glass"
    assert _normalize_genre("Brunches") == "brunch"


def test_find_genre_only_accepts_categories_that_match_the_hunch():
    import asyncio

    from app.engine import find_genre

    class TagSearch:
        def __init__(self, names):
            self.names = names

        async def tags(self, params):
            return {"results": {"tags": [
                {"id": f"urn:tag:genre:place:{name.lower().replace(' ', '_')}", "name": name} for name in self.names
            ]}}

    ranked = [{"id": "urn:tag:genre:place:brunch", "name": "Brunch", "rank": 3, "ref_rank": 2.0}]

    def find(names, query):
        return asyncio.run(find_genre(TagSearch(names), ranked, query))

    assert find([], "brunches")[0]["rank"] == 3  # the locals' own ranking comes first
    genre, _ = find(["Vegan bakery", "Bakery"], "bakery")
    assert genre["name"] == "Bakery" and genre["rank"] == 51 and genre["ref_rank"] is None
    assert find(["Vegan bakery"], "bakery")[0]["name"] == "Vegan bakery"
    assert find(["Wine shop", "Wine bar"], "natural wine bar")[0]["name"] == "Wine bar"
    genre, why = find(["Aboriginal art gallery", "Art gallery"], "art gallery")
    assert genre is None and "taste cue" in why
    genre, why = find(["Clothing store"], "concept store")
    assert genre is None and "no storefront category" in why
    genre, why = find(["Store", "Clothing store"], "concept store")
    assert genre is None and "only the generic Store" in why


def test_reference_rank_uses_median_and_counts_missing_as_low():
    assert scoring.reference_rank([2, 4, 30]) == 4.0
    assert scoring.reference_rank([1, None, None]) == 51.0
    assert scoring.reference_rank([]) is None


def test_split_favorites_prefers_places_locals_love_more_than_the_city():
    local = [{"entity_id": x} for x in "abcdefg"]
    city = [{"entity_id": x} for x in "abc"]
    kind, favorites = scoring.split_favorites(local, city)
    assert kind == "local"
    assert [f["entity_id"] for f in favorites] == ["d", "e", "f", "g"]
    kind, favorites = scoring.split_favorites(local[:6], city)
    assert kind == "citywide"
    assert len(favorites) == 6


def test_distinctive_by_rank_skips_items_popular_everywhere():
    everywhere = {"entity_id": "airbnb", "name": "Airbnb"}
    local_gem = {"entity_id": "gem", "name": "Local Gem"}
    local = [everywhere, local_gem]
    references = [[everywhere, *({"entity_id": f"x{i}", "name": f"X{i}"} for i in range(9))] for _ in range(3)]
    assert [e["name"] for e in scoring.distinctive_by_rank(local, references)] == ["Local Gem"]
    assert scoring.distinctive_by_rank(local, []) == []


def test_storefront_filter_drops_malls_and_hotels():
    assert not scoring.is_business_genre("Shopping mall")
    assert not scoring.is_business_genre("Resort hotel")
    assert scoring.is_business_genre("Fashion accessories store")


def test_distinctive_keeps_local_only_entities():
    local = [{"entity_id": "a", "name": "A"}, {"entity_id": "b", "name": "B"}, {"entity_id": "c", "name": "C"}]
    metro = [{"entity_id": "a", "name": "A"}]
    assert [e["entity_id"] for e in scoring.distinctive(local, metro)] == ["b", "c"]


def test_offensive_names_are_filtered():
    assert scoring.is_safe_name("Tyler, the Creator")
    assert not scoring.is_safe_name("Young N1gga")
    assert not scoring.is_safe_name(None)
    local = [{"entity_id": "x", "name": "Young Nigga"}, {"entity_id": "y", "name": "Solange"}]
    assert [e["name"] for e in scoring.distinctive(local, [])] == ["Solange"]


def test_summarize_block_counts_genres_keywords_and_classics():
    places = [
        place("Cafe One", ["Coffee shop", "Restaurant"], [("great espresso", 10), ("slow service", 4)], 4.5, 2, reviews=900),
        place("Bar Two", ["Wine Bar"], [("natural wine", 7)], 4.1, 3, reviews=40),
        place("Chez Three", ["French"], [("tasting menu", 3)], 4.8, 4, reviews=120, michelin=1),
    ]
    summary = scoring.summarize_block(places)
    assert summary["place_count"] == 3
    assert dict(summary["top_genres"]) == {"Coffee shop": 1, "Wine Bar": 1, "French": 1}
    assert summary["complaints"] == [{"label": "Slow service", "mentions": 4, "places": 1, "keywords": ["slow service"]}]
    assert [(g["label"], g["mentions"]) for g in summary["menu"]] == [("great espresso", 10), ("natural wine", 7), ("tasting menu", 3)]
    assert summary["experience"] == [] and "praise" not in summary
    assert summary["avg_rating"] == 4.47
    # Michelin first, then review history; a place with few reviews is not called established (and never "new").
    assert [c["name"] for c in summary["classics"]] == ["Chez Three", "Cafe One"]
    assert summary["classics"][0]["michelin"] == "1 star"
    assert summary["classics"][1] == {
        "id": "cafe-one", "name": "Cafe One", "genre": "Coffee Shop", "price_level": 2, "reviews": 900,
        "known_for": ["great espresso"],
    }


def test_classics_use_the_primary_genre_and_skip_hotels():
    egyptian = place("Abou Test", ["Izakaya restaurant", "Egyptian restaurant"], [("michelin star", 3), ("okra", 2)], reviews=1500)
    egyptian["properties"]["primary_genre"] = {"id": "urn:tag:genre:place:restaurant:egyptian", "name": "Egyptian restaurant"}
    generic = place("Plain Test", ["Pizza takeout"], reviews=600)
    generic["properties"]["primary_genre"] = {"id": "urn:tag:genre:place:restaurant", "name": "Restaurant"}
    hotel = place("Grand Test Hotel", ["Extended stay hotel", "Hotel"], reviews=2000)
    classics = scoring.summarize_block([egyptian, generic, hotel])["classics"]
    assert [(c["name"], c["genre"]) for c in classics] == [("Abou Test", "Egyptian"), ("Plain Test", "Pizza Takeout")]
    assert classics[0]["known_for"] == ["okra"]


def test_standing_needs_michelin_or_a_long_review_history():
    assert scoring.standing(place("A", reviews=250)) == {"reviews": 250}
    assert scoring.standing(place("B", reviews=249)) is None
    assert scoring.standing(place("C")) is None
    assert scoring.standing(place("D", michelin=0)) == {"reviews": None, "michelin": "listed"}
    assert scoring.standing(place("E", reviews=10, michelin=2)) == {"reviews": 10, "michelin": "2 stars"}


def week(opens, closes, weekend_closes=None, closed=()):
    days = {}
    for day in scoring.DAYS:
        late = weekend_closes if weekend_closes and day in ("friday", "saturday") else closes
        days[day] = [{"opens": opens, "closes": late, "closed": day in closed}]
    return days


def test_day_span_handles_split_shifts_and_closing_after_midnight():
    assert scoring.day_span([{"opens": "T11:00:00", "closes": "T15:00:00"}, {"opens": "T17:30:00", "closes": "T22:00:00"}]) == (11, 22)
    assert scoring.day_span([{"opens": "T18:00:00", "closes": "T02:00:00"}]) == (18, 26)
    assert scoring.day_span([{"opens": "T18:00:00", "closes": "", "closed": False}]) is None
    assert scoring.day_span([{"opens": "T09:00:00", "closes": "T17:00:00", "closed": True}]) is None
    assert scoring.day_span(None) is None


def test_typical_hours_takes_medians_per_day_group():
    places = [
        place("A", hours=week("T08:00:00", "T22:00:00", "T00:00:00")),
        place("B", hours=week("T09:00:00", "T22:00:00", "T01:00:00")),
        place("C", hours=week("T08:00:00", "T21:30:00", "T00:00:00", closed=("sunday",))),
        place("D"),  # no listed hours
    ]
    hours = scoring.typical_hours(places)
    assert hours == {"text": "Mon–Thu 8 am–10 pm · Fri–Sat 8 am–midnight · Sun 8:30 am–10 pm", "sample": 3}
    assert scoring.typical_hours(places[:2]) is None  # too few places to call it typical


def test_typical_hours_merges_equal_days_and_reports_closed_days():
    same = [place(n, hours=week("T07:00:00", "T15:30:00")) for n in "ABC"]
    assert scoring.typical_hours(same)["text"] == "Daily 7 am–3:30 pm"
    sundays_off = [place(n, hours=week("T10:00:00", "T19:00:00", closed=("sunday",))) for n in "ABC"]
    assert scoring.typical_hours(sundays_off)["text"] == "Mon–Sat 10 am–7 pm · Sun closed"


def test_places_listed_as_closed_every_day_have_unknown_hours():
    # Qloo lists some busy places (chains, cinemas) as closed all week: their hours are unknown, not closed.
    never_open = [place(n, hours={day: [{"opens": None, "closes": None, "closed": True}] for day in scoring.DAYS}) for n in "XYZ"]
    assert scoring.typical_hours(never_open) is None
    open_ones = [place(n, hours=week("T08:00:00", "T20:00:00")) for n in "ABC"]
    assert scoring.typical_hours(never_open + open_ones) == {"text": "Daily 8 am–8 pm", "sample": 3}


def test_design_dna_aggregates_tag_families_and_keywords():
    places = [
        place("A", keywords=[("candlelit", 5), ("rude staff", 3), ("small plates", 4), ("prices", 9)], price=3,
              extra_tags=[("urn:tag:decor:qloo", "Industrial chic"), ("urn:tag:menu_highlight:qloo", "Small plates")]),
        place("B", keywords=[("candlelit", 2)], price=2,
              extra_tags=[("urn:tag:decor:qloo", "Industrial chic")]),
    ]
    dna = scoring.design_dna(places)
    assert dna["decor"] == ["Industrial chic"]
    assert dna["menu"] == ["Small plates"]
    # Grouped menu and experience topics, most mentioned first; complaints and neutral topics never appear.
    assert dna["keywords"] == ["Atmosphere", "small plates"]
    assert dna["typical_price_level"] in (2, 3)


def test_focus_matching():
    assert scoring.matches_focus("Wine Bar", "food_drink")
    assert scoring.matches_focus("New American", "food_drink")
    assert not scoring.matches_focus("Gift shop", "food_drink")
    assert scoring.matches_focus("Gift shop", "retail")
    assert scoring.matches_focus("Yoga studio", "leisure")
    assert not scoring.matches_focus("Barbershop", "food_drink")
    assert scoring.matches_focus("Anything", "any")
    # Shops where people eat or drink on the spot are food and drink, never retail; shops selling bottles are retail.
    for genre in ("Coffee shop", "Ice cream shop", "Dessert shop", "Sandwich shop"):
        assert not scoring.matches_focus(genre, "retail"), genre
    assert scoring.matches_focus("Wine shop", "retail") and scoring.matches_focus("Book store", "retail")
    assert scoring.genre_kind("Coffee shop") == "food" and scoring.genre_kind("Gift shop") == "retail"


def place_with(primary: tuple[str, str] | None, tags: list[tuple[str, str]]) -> dict:
    props = {"primary_genre": {"id": primary[0], "name": primary[1]}} if primary else {}
    return {"entity_id": "p", "name": "P", "properties": props,
            "tags": [{"id": i, "name": n, "type": "urn:tag:genre:place"} for i, n in tags]}


def test_relevance_tiers_keep_places_that_are_the_business_in_earnest():
    cocktail = ("urn:tag:genre:place:cocktail_bar", "Cocktail bar")
    museum = place_with(("urn:tag:genre:place:tourist_attraction", "Tourist attraction"), [cocktail])
    bar = place_with(("urn:tag:genre:place:bar", "Bar"), [cocktail])
    real = place_with(cocktail, [cocktail])
    assert [scoring.relevance_tier(p, *cocktail) for p in (real, bar, museum)] == [1, 2, 3]
    assert scoring.relevant([museum, bar, real], *cocktail) == [bar, real]
    assert scoring.best_examples([museum, bar, real], *cocktail) == [real, bar, museum]
    # A seafood restaurant is the genre 'Seafood'; without a primary genre, the first genre tag decides.
    seafood = place_with(("urn:tag:genre:place:x", "Seafood restaurant"), [])
    assert scoring.relevance_tier(seafood, "urn:tag:genre:place:seafood", "Seafood") == 1
    assert scoring.relevance_tier(place_with(None, [("urn:tag:genre:place:seafood", "Seafood")]), "urn:tag:genre:place:seafood", "Seafood") == 1
    assert scoring.genre_key("Café") == scoring.genre_key("Cafe") and scoring.genre_key("Steak house") == "steakhouse"


def test_global_stars_are_not_distinctive_of_a_neighborhood():
    star = {"entity_id": "star", "name": "Global Star", "popularity": 0.9999}
    homegrown = {"entity_id": "home", "name": "Homegrown Star", "popularity": 0.9999}
    local = [star, homegrown, {"entity_id": "gem", "name": "Local Gem", "popularity": 0.6}]
    filler = [{"entity_id": f"x{i}", "name": f"X{i}"} for i in range(20)]
    # The global star sits low in one comparison list (rank noise); the homegrown star is in none of them.
    references = [filler[:12] + ([star] if i == 0 else []) for i in range(3)]
    assert [e["name"] for e in scoring.distinctive_by_rank(local, references)] == ["Homegrown Star", "Local Gem"]
