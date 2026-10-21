"""Views of a run's evidence: what the agent sees, and what each gap says in plain words."""
from __future__ import annotations

from .. import scoring
from .models import RunState


def public_gap(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def describe_age(demographics: dict | None) -> str | None:
    if not demographics or not demographics.get("age"):
        return None
    labels = {
        "24_and_younger": "under 25", "25_to_29": "25-29", "30_to_34": "30-34",
        "35_to_44": "35-44", "45_to_54": "45-54", "55_and_older": "55+",
    }
    leaning = sorted(demographics["age"].items(), key=lambda kv: -kv[1])
    over = [labels.get(bucket, bucket) for bucket, value in leaning if value > 0.05][:2]
    return f"skews {' and '.join(over)}" if over else "no strong age skew"


def evidence_brief(run: RunState) -> dict:
    """Compact evidence pack handed to the LLM."""
    s = run.summary
    walk = run.catchment
    return {
        "site": {"label": run.site.label, "focus": run.site.focus, "owner_notes": run.site.notes or None},
        "walk_catchment": {
            "minutes": run.site.minutes,
            "shape": walk.source if walk else "circle",
            "area_km2": round(walk.area_m2 / 1e6, 2) if walk else None,
        },
        "block_inside_the_walk": {
            "places_scanned": s.get("place_count"),
            "most_common_genres": s.get("top_genres", [])[:8],
            "average_rating": s.get("avg_rating"),
            "price_levels": s.get("price_levels"),
            "what_reviews_praise": [k for k, _ in s.get("praise", [])[:8]],
            "what_reviews_complain_about": [k for k, _ in s.get("complaints", [])[:6]],
            "rising_places": [name for name, _ in s.get("rising", [])[:4]],
            "fading_places": [name for name, _ in s.get("fading", [])[:4]],
        },
        "gap_table": [gap_summary(g) for g in run.gaps],
        "taste_cues": run.cues,
        "brands_this_area_over_indexes_on": [b["name"] for b in run.taste.get("distinctive_brands", [])],
        "artists_this_area_over_indexes_on": [a["name"] for a in run.taste.get("distinctive_artists", [])],
        "most_popular_brands_here": [b["name"] for b in run.taste.get("brands", [])[:10]],
        "crowd": describe_age(run.demographics),
    }


def gap_summary(g: dict) -> dict:
    """One gap row as the agent sees it: comparisons are stated in words, so they cannot be misread."""
    if g["favorites_kind"] == "local" and g["favorites_total"]:
        travel = (
            f"{g['favorites_far']} of the {g['favorites_total']} places locals love more than the city does are outside "
            f"the walk; median distance {g['median_favorite_km']} km"
        )
    else:
        travel = "no evidence: locals' favorites of this type are just the city's famous places"
    return {
        "genre": g["genre"],
        "locals_rank_here": g["demand_rank"] if g["demand_rank"] < scoring.UNRANKED else "outside their top 50",
        "median_rank_in_6_same_size_areas_around": g["ref_rank"],
        "demand_compared_with_areas_around": demand_comparison(g),
        "places_within_walk": f"{g['nearby_count']}{'+' if g['nearby_capped'] else ''}",
        "typical_for_a_block_this_dense": g["expected_nearby"],
        "relative_supply": g["relative_supply"],
        "do_locals_travel_for_it": travel,
        "evidence": g["evidence"],
        "gap_score": g["gap_score"],
    }


def demand_comparison(g: dict) -> str:
    """Rank 1 is the strongest, so a smaller number here than around means more demand here."""
    local, ref = g["demand_rank"], g.get("ref_rank")
    if ref is None:
        return "no comparison available"
    if local >= scoring.UNRANKED and ref >= scoring.UNRANKED:
        return "outside the top 50 both here and around"
    if ref - local >= 3:
        return "ranked higher here than in the areas around: stronger local demand"
    if local - ref >= 3:
        return "ranked lower here than in the areas around: weaker local demand"
    return "about the same as in the areas around"


def gap_for(run: RunState, genre: str) -> dict | None:
    wanted = (genre or "").strip().lower()
    return next((g for g in run.gaps + run.explored if g["genre"].lower() == wanted), None)


def inspect_payload(run: RunState, row: dict) -> dict:
    entities, cards = storefront_favorites(row)
    # Only places locals love more than the city does say anything about travel; otherwise they are just the
    # city's famous places, and naming them that way keeps the agent from claiming that locals travel to them.
    favorites_key = (
        "places_locals_love_more_than_the_city_does" if row.get("favorites_kind") == "local"
        else "the_citys_famous_places_of_this_type"
    )
    return {
        "genre": row["genre"],
        "competitors_within_walk": [
            {k: c.get(k) for k in ("name", "rating", "price_level", "praise", "complaints", "distance_m")}
            for c in row["competitors"][:6]
        ],
        favorites_key: [
            {"name": f["name"], "km_away": round((f.get("distance_m") or 0) / 1000, 1), "price_level": f.get("price_level"),
             "praise": f.get("praise"), "inside_walk": f.get("within_walk", False)}
            for f in cards[:8]
        ],
        "do_locals_travel_for_it": gap_summary(row)["do_locals_travel_for_it"],
        "design_dna_of_these_places": scoring.design_dna(entities),
    }


def storefront_favorites(row: dict) -> tuple[list[dict], list[dict]]:
    """Locals' favorite places of a genre without hotels and malls, as (entities, cards)."""
    pairs = [
        (entity, card) for entity, card in zip(row["_favorite_entities"], row["favorites"], strict=True) if scoring.is_storefront_place(entity)
    ]
    return [entity for entity, _ in pairs], [card for _, card in pairs]


def short_label(label: str) -> str:
    """'Upper East Side, Manhattan' -> 'Upper East Side'; falls back to a neutral word for raw pins."""
    first = (label or "").split(",")[0].strip()
    if not first or first.lower() in {"selected site", "dropped pin"} or any(ch.isdigit() for ch in first[:3]):
        return "Corner"
    return first[:32]


def gap_evidence(row: dict, minutes: int = 10) -> list[str]:
    genre = row["genre"]
    nearby = f"{row['nearby_count']}{'+' if row['nearby_capped'] else ''}"
    lines = []
    ref = row.get("ref_rank")
    if row["demand_rank"] >= scoring.UNRANKED:
        lines.append(f"Locals do not rank {genre} among their top 50 place types here.")
    elif ref is not None:
        ref_text = "outside the top 50" if ref >= 51 else f"#{ref:g}"
        lines.append(f"Locals rank {genre} #{row['demand_rank']} here, versus a median {ref_text} in same-size areas around.")
    else:
        lines.append(f"Locals rank {genre} #{row['demand_rank']} among place types here.")
    expected = row.get("expected_nearby")
    if expected is not None:
        lines.append(
            f"Qloo lists {nearby} {genre} places inside the {minutes}-minute walk; a block this dense would typically have about {expected:g}."
        )
    if row.get("favorites_kind") == "local" and row["favorites_total"]:
        lines.append(
            f"{row['favorites_far']} of {row['favorites_total']} {genre} places that locals love more than the city does "
            f"are outside the walk (median {row['median_favorite_km']} km away)."
        )
    elif row["favorites_total"]:
        lines.append(f"Locals' favorite {genre} places are the city's famous ones, so where they travel says little here.")
    if row.get("evidence") == "thin":
        lines.append("Thin evidence: Qloo knows at most one such place around here.")
    elif row.get("evidence") == "atypical":
        lines.append("Atypical: locals' favorites of this type are mostly hotels or malls, not storefronts.")
    return lines
