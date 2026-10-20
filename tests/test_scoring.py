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


def test_business_genre_filters_generic_and_cues():
    assert scoring.is_business_genre("Wine Bar")
    assert not scoring.is_business_genre("Restaurant")
    assert not scoring.is_business_genre("Art museum")
    assert scoring.is_taste_cue("Art museum")


def test_gap_score_rewards_demand_leakage_and_low_supply():
    underserved = scoring.gap_score(rank=1, total=8, nearby_count=2, leakage=1.0)
    saturated = scoring.gap_score(rank=1, total=8, nearby_count=45, leakage=1.0)
    low_demand = scoring.gap_score(rank=8, total=8, nearby_count=2, leakage=1.0)
    satisfied_locally = scoring.gap_score(rank=1, total=8, nearby_count=2, leakage=0.0)
    assert underserved > saturated
    assert underserved > low_demand
    assert underserved > satisfied_locally
    assert 0 <= saturated <= underserved <= 100


def test_gap_row_measures_leakage_from_favorite_distances():
    site = (40.7736, -73.9566)
    near_fav = place("Near", lat=40.7740, lon=-73.9560)
    far_fav = place("Far", lat=40.7200, lon=-73.9900)
    row = scoring.gap_row("g", "Wine Bar", 2, 8, [place("Comp")], [near_fav, far_fav], site, 800)
    assert row["favorites_total"] == 2
    assert row["favorites_far"] == 1
    assert row["nearby_count"] == 1
    assert row["median_favorite_km"] is not None


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
