"""What the owner asked for: a verdict on the business they want to open, or how to improve the place they run.

Both reuse the survey's own measurements: a category the gap table does not cover is measured live the same way, so a
verdict compares like with like, and an existing place is compared with the places locals love in its category.
"""
from __future__ import annotations

import re
from collections import Counter
from statistics import median

from .. import engine, scoring
from ..qloo import QlooClient
from . import experience
from .evidence import fits, gap_evidence, gap_for, public_gap, storefront_favorites, with_fit
from .models import RunState

# Tag families an owner can act on, and how many of them to suggest.
OFFER_FAMILIES = {"menu": 2, "offerings": 2, "amenities": 1, "activities": 1}
# A tag most peers share: at least this share of them, and at least two places.
COMMON_SHARE = 0.4
# Amenities that come with the building, not with the business, and offerings every place of a kind has.
BUILDING_BOUND = re.compile(
    r"\b(drive|parking|valet|rooftop|roof|garden|terrace|patio|pool|beach|views?|waterfront|outdoor|balcony|elevator)\b",
    re.IGNORECASE,
)
TRIVIAL_OFFERINGS = {"hot tea", "iced tea", "tea", "soft drinks", "juice", "water", "sodas", "soda"}


async def measured_row(q: QlooClient, run: RunState, genre: dict, source: str) -> dict:
    """The gap row for a genre: from the table when it is there, otherwise measured live on the same baseline.

    Matched by tag id first: a place's primary genre can be named differently ('Seafood restaurant') than the ranking.
    """
    row = next((r for r in run.gaps + run.explored if r["genre_id"] == genre["id"]), None) or gap_for(run, genre["name"])
    if row:
        return row
    known = next((g for g in run.genres if g["id"] == genre["id"]), None)
    genre = {"rank": scoring.UNRANKED, "ref_rank": None, **(known or {}), **genre}
    row = with_fit(run, await engine.probe_genre(q, run.catchment, genre, run.gaps))
    row["source"] = source
    run.explored.append(row)
    return row


def weakness(row: dict) -> str:
    """The main reason a category scores low here (the score gives no credit for a local rank beyond about #15)."""
    if row["demand_rank"] >= scoring.UNRANKED:
        return "locals do not rank it among their top 50 place types"
    if row["demand_rank"] > 15:
        return f"locals rank it only #{row['demand_rank']} among place types"
    if row["relative_supply"] >= 1.2:
        return "the block already has more of it than its density predicts"
    if row.get("lift", 0) <= -0.3:
        return "locals rank it lower than the areas around do"
    return "demand and supply here are close to what the areas around show"


async def verdict(q: QlooClient, run: RunState) -> dict:
    """How the business the owner wants to open ranks among this site's gaps, and whether the unit can host it."""
    query = run.site.business.strip()
    genre, why_not = await engine.find_genre(q, run.genres, query)
    if not genre:
        return {"query": query, "found": False, "level": "unknown", "headline": why_not, "evidence": []}
    row = await measured_row(q, run, genre, "owner")
    ranked = sorted([r for r in run.gaps if r["genre_id"] != row["genre_id"]] + [row], key=lambda r: -r["gap_score"])
    position, total = ranked.index(row) + 1, len(ranked)
    title = scoring.genre_title(row["genre"])
    if not fits(row):
        level, headline = "misfit", f"{title} does not fit this unit: it {row['fit']['reason']}."
    elif row["evidence"] == "thin":
        level, headline = "thin", f"Qloo knows too few {title} places around here to judge it."
    elif row["evidence"] == "atypical":
        level, headline = "thin", f"Locals' favorite {title} places are mostly hotels or malls, so the comparison is weak."
    elif position <= max(1, round(total / 3)):
        level, headline = "strong", f"{title} is one of the strongest gaps here: #{position} of {total} categories measured."
    elif position <= round(2 * total / 3):
        level, headline = "possible", f"{title} is a middling gap here (#{position} of {total}): {weakness(row)}."
    else:
        level, headline = "weak", f"{title} is a weak gap here (#{position} of {total}): {weakness(row)}."
    return {
        "query": query, "found": True, "genre": row["genre"], "genre_id": row["genre_id"], "level": level,
        "headline": headline, "position": position, "of": total, "gap_score": row["gap_score"],
        "evidence": gap_evidence(row, run.site.minutes), "row": public_gap(row),
    }


def requested_row(run: RunState) -> dict | None:
    """The gap row of the business the owner asked for, when Qloo knows it and the unit can host it."""
    found = run.verdict if run.verdict and run.verdict.get("found") else None
    if not found:
        return None
    row = next((r for r in run.gaps + run.explored if r["genre_id"] == found["genre_id"]), None)
    return row if row and fits(row) else None


async def improve(q: QlooClient, run: RunState) -> dict | None:
    """The owner's place against the places locals love in its category, and the moves that follow."""
    place = run.place or {}
    tag = scoring.primary_genre_tag(place) or next(
        ((tag_id, name) for tag_id, name in scoring.genre_tags(place) if scoring.is_business_genre(name)), None,
    )
    if not tag:
        return None
    row = await measured_row(q, run, {"id": tag[0], "name": tag[1]}, "owner")
    comparison = compare(place, row)
    plan = experience.plan(run, row["genre"])
    changes = moves(place.get("name") or "Your place", row, comparison, plan)
    hours = comparison["hours"]
    hours.pop("_place"), hours.pop("_peers")
    return {
        "place": scoring.place_card(place, (run.site.lat, run.site.lon)),
        "genre": row["genre"],
        "comparison": comparison,
        "moves": changes,
        "experience": plan,
        "row": public_gap(row),
    }


def peers_of(place: dict, row: dict) -> tuple[list[dict], str]:
    """Places locals love in the category at a similar price (within one level), without the place itself.

    An upscale place is not compared with fast-casual favorites; when too few share its price, all favorites count, and
    when too few are favorites at all, nearby competitors fill in. The label says which comparison was made.
    """
    own = scoring.item_id(place)
    favorites = [e for e in storefront_favorites(row)[0] if scoring.item_id(e) != own]
    price = (place.get("properties") or {}).get("price_level")
    if price:
        similar = [e for e in favorites if abs(((e.get("properties") or {}).get("price_level") or price) - price) <= 1]
        if len(similar) >= 3:
            return similar, "places locals love at a similar price"
    if len(favorites) >= 3:
        return favorites, "places locals love"
    ids = {scoring.item_id(e) for e in favorites}
    nearby = [e for e in row.get("_nearby_entities") or [] if scoring.item_id(e) not in ids | {own}]
    return favorites + nearby, "places locals love or that are nearby"


def suggestible(name: str, family: str) -> bool:
    lowered = name.lower()
    if lowered in scoring.GENERIC_OFFERINGS or lowered in TRIVIAL_OFFERINGS:
        return False
    return family != "amenities" or not BUILDING_BOUND.search(name)


def tag_names(entity: dict, family: str) -> set[str]:
    prefix = scoring.DESIGN_FAMILIES[family]
    return {t["name"] for t in entity.get("tags") or [] if (t.get("type") or "").startswith(prefix) and t.get("name")}


def keywords(entity: dict) -> list[str]:
    return [k["name"] for k in scoring.review_keywords(entity)]


def compare(place: dict, row: dict) -> dict:
    peers, peers_label = peers_of(place, row)
    props = place.get("properties") or {}
    offer = {}
    for family, limit in OFFER_FAMILIES.items():
        counts = Counter(name for peer in peers for name in tag_names(peer, family))
        own = tag_names(place, family)
        common = [
            (name, n) for name, n in counts.most_common()
            if n >= 2 and n / max(1, len(peers)) >= COMMON_SHARE and suggestible(name, family)
        ]
        offer[family] = {
            "missing": [{"name": name, "places": n} for name, n in common if name not in own][:limit],
            "shared": [name for name, _ in common if name in own][:4],
            "own": sorted(name for name in own if counts[name] <= max(1, len(peers) // 10))[:3],
        }
    peer_ratings = [float(r) for p in peers if (r := (p.get("properties") or {}).get("business_rating"))]
    peer_prices = [int(v) for p in peers if (v := (p.get("properties") or {}).get("price_level"))]
    own_words = {word.lower() for word in keywords(place)}
    peer_praise = Counter(
        word for p in peers for word in keywords(p) if not scoring.is_complaint(word) and word.lower() not in own_words
    )
    place_hours = scoring.hours_by_group([place], minimum=1)
    peer_hours = scoring.hours_by_group(peers)
    rating = props.get("business_rating")
    return {
        "peers": len(peers),
        "peers_label": peers_label,
        # Suggestions only transfer between places at a similar price; otherwise only the position is reported.
        "comparable": "similar price" in peers_label or not props.get("price_level"),
        "peer_names": [p.get("name") for p in peers[:6] if p.get("name")],
        "rating": {"place": round(float(rating), 1) if rating else None, "peers": round(median(peer_ratings), 1) if peer_ratings else None},
        "price": {"place": props.get("price_level"), "peers": round(median(peer_prices)) if peer_prices else None},
        "hours": {
            "place": {label: scoring.span_text(span) for label, span in place_hours[0].items()} if place_hours else None,
            "peers": {label: scoring.span_text(span) for label, span in peer_hours[0].items()} if peer_hours else None,
            "_place": place_hours[0] if place_hours else {},
            "_peers": peer_hours[0] if peer_hours else {},
        },
        "offer": offer,
        "praise": [word for word in keywords(place) if not scoring.is_complaint(word)][:5],
        "complaints": [word for word in keywords(place) if scoring.is_complaint(word)][:4],
        "peers_praise": [word for word, _ in peer_praise.most_common(5)],
        "standing": scoring.standing(place),
    }


def moves(name: str, row: dict, comparison: dict, plan: dict | None) -> list[dict]:
    """Concrete changes, most urgent first, each with the evidence behind it.

    Offer, hours and rating suggestions only come from places at a similar price: an upscale place learns nothing from
    taquerias' opening hours. A place priced unlike the favorites gets its position instead.
    """
    genre = scoring.genre_title(row["genre"])
    peers = f"{genre} {comparison['peers_label']}"
    count = comparison["peers"]
    rating, price = comparison["rating"], comparison["price"]
    out: list[dict] = []
    if comparison["complaints"]:
        out.append({"title": "Fix what reviews flag", "why": f"Reviews of {name} mention {', '.join(comparison['complaints'])}."})
    if comparison["comparable"]:
        for family in OFFER_FAMILIES:
            for item in comparison["offer"][family]["missing"]:
                out.append({
                    "title": f"Consider {item['name'].lower()}",
                    "why": f"{item['places']} of the {count} {peers} are known for it; {name} is not.",
                })
        out += hour_moves(name, peers, comparison["hours"]["_place"], comparison["hours"]["_peers"])
        if rating["place"] and rating["peers"] and rating["place"] < rating["peers"] - 0.2:
            out.append({"title": "Close the rating gap", "why": f"{name} is rated {rating['place']} against a median {rating['peers']} at the {peers}."})
    elif price["place"] and price["peers"] and price["place"] != price["peers"]:
        position = "above" if price["place"] > price["peers"] else "below"
        out.append({"title": f"Own the {'high' if position == 'above' else 'low'} end", "why": (
            f"Few of the {genre} places locals love are priced like {name} ({'$' * price['place']}); most are "
            f"{'$' * price['peers']}. {name} is the {'upscale' if position == 'above' else 'budget'} option, so their offer "
            "and hours are no guide."
        )})
    if row.get("favorites_kind") == "local" and row["favorites_far"] >= 3 and (row.get("leakage") or 0) >= 0.6:
        praise = f"; what people praise there: {', '.join(comparison['peers_praise'][:3])}" if comparison["peers_praise"] else ""
        out.append({"title": "Win back the trips", "why": (
            f"{row['favorites_far']} of the {row['favorites_total']} {genre} places locals love more than the city does are "
            f"outside the walk, a median {row['median_favorite_km']} km away{praise}."
        )})
    if plan and plan.get("soundtrack"):
        names = ", ".join(item["name"] for item in plan["soundtrack"][:3])
        out.append({"title": "Program for the neighborhood", "why": f"People within 1.5 km over-index on {names}; see the plan below."})
    return out[:8]


def hour_moves(name: str, peers: str, own: dict, others: dict) -> list[dict]:
    """At most two hour changes, the biggest difference first."""
    found: list[tuple[float, dict]] = []
    for label, span in others.items():
        mine = own.get(label)
        if span == "closed" or mine is None:
            continue
        if mine == "closed":
            found.append((24, {"title": f"Open on {label}", "why": f"Most of the {peers} are open {scoring.span_text(span)}; {name} is closed."}))
            continue
        if span[1] - mine[1] >= 1:
            found.append((span[1] - mine[1], {"title": f"Stay open later {label}", "why": (
                f"The {peers} close around {scoring.clock_text(span[1])}; {name} closes at {scoring.clock_text(mine[1])}."
            )}))
        elif mine[0] - span[0] >= 1.5:
            found.append((mine[0] - span[0], {"title": f"Open earlier {label}", "why": (
                f"The {peers} open around {scoring.clock_text(span[0])}; {name} opens at {scoring.clock_text(mine[0])}."
            )}))
    return [move for _, move in sorted(found, key=lambda item: -item[0])[:2]]
