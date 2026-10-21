from app import scoring


def place(name, genres=(), keywords=(), rating=None, price=None, growth=None, lat=None, lon=None, extra_tags=()):
    tags = [{"id": f"urn:tag:genre:place:{g.lower().replace(' ', '_')}", "name": g, "type": "urn:tag:genre:place"} for g in genres]
    tags += [{"id": f"{t}:{n.lower().replace(' ', '_')}", "name": n, "type": t} for t, n in extra_tags]
    entity = {
        "entity_id": name.lower().replace(" ", "-"),
        "name": name,
        "tags": tags,
        "properties": {
            "keywords": [{"name": k, "count": c} for k, c in keywords],
            "business_rating": rating,
            "price_level": price,
        },
        "query": {"measurements": {"audience_growth": growth}},
    }
    if lat is not None:
        entity["location"] = {"lat": lat, "lon": lon}
    return entity


def test_complaint_detection():
    assert scoring.is_complaint("slow service")
    assert scoring.is_complaint("long wait")
    assert scoring.is_complaint("touts")
    assert not scoring.is_complaint("outdoor seating")
    assert not scoring.is_complaint("airlines lounge")


def test_menu_items_with_complaint_words_are_not_complaints():
    assert not scoring.is_complaint("dirty martinis")
    assert not scoring.is_complaint("dirty chai")
    assert not scoring.is_complaint("friendly wait staff")
    assert scoring.is_complaint("dirty tables")


def test_negated_complaints_are_praise():
    assert not scoring.is_complaint("not crowded")
    assert not scoring.is_complaint("no wait")
    assert scoring.is_complaint("crowded")


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
    assert scoring.signature_items("Lounge", dna) == ["Cocktails", "Live music", "Karaoke"]
    assert scoring.signature_items("Spa", dna)[0] == "Cocktails"
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
        "Game day viewing", "Live entertainment", "Cocktails", "Buffalo chicken wings", "Sliders",
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
    from app.agent import demand_comparison, gap_summary

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


def test_summarize_block_counts_genres_keywords_and_growth():
    places = [
        place("Cafe One", ["Coffee shop", "Restaurant"], [("great espresso", 10), ("slow service", 4)], 4.5, 2, 0.3),
        place("Bar Two", ["Wine Bar"], [("natural wine", 7)], 4.1, 3, -0.2),
    ]
    summary = scoring.summarize_block(places)
    assert summary["place_count"] == 2
    assert dict(summary["top_genres"]) == {"Coffee shop": 1, "Wine Bar": 1}
    assert ("slow service", 4) in summary["complaints"]
    assert ("great espresso", 10) in summary["praise"]
    assert summary["rising"][0][0] == "Cafe One"
    assert summary["fading"][0][0] == "Bar Two"
    assert summary["avg_rating"] == 4.3


def test_design_dna_aggregates_tag_families_and_keywords():
    places = [
        place("A", keywords=[("candlelit", 5), ("rude staff", 3)], price=3,
              extra_tags=[("urn:tag:decor:qloo", "Industrial chic"), ("urn:tag:menu_highlight:qloo", "Small plates")]),
        place("B", keywords=[("candlelit", 2)], price=2,
              extra_tags=[("urn:tag:decor:qloo", "Industrial chic")]),
    ]
    dna = scoring.design_dna(places)
    assert dna["decor"] == ["Industrial chic"]
    assert dna["menu"] == ["Small plates"]
    assert dna["keywords"] == ["candlelit"]
    assert dna["typical_price_level"] in (2, 3)


def test_average_demographics():
    rows = [
        {"query": {"age": {"25_to_29": 0.4}, "gender": {"female": 0.2}}},
        {"query": {"age": {"25_to_29": 0.2}, "gender": {"female": 0.0}}},
    ]
    result = scoring.average_demographics(rows)
    assert result == {"age": {"25_to_29": 0.3}, "gender": {"female": 0.1}}
    assert scoring.average_demographics([]) is None


def test_focus_matching():
    assert scoring.matches_focus("Wine Bar", "food_drink")
    assert scoring.matches_focus("New American", "food_drink")
    assert not scoring.matches_focus("Gift shop", "food_drink")
    assert scoring.matches_focus("Gift shop", "retail")
    assert scoring.matches_focus("Yoga studio", "leisure")
    assert not scoring.matches_focus("Barbershop", "food_drink")
    assert scoring.matches_focus("Anything", "any")
