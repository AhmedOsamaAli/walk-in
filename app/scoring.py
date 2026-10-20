"""Pure scoring and summarizing logic over Qloo responses (no network calls)."""
from __future__ import annotations

import re
from collections import Counter
from statistics import mean, median
from typing import Iterable

from .geo import distance_m

GENRE_TYPE = "urn:tag:genre:place"

# Too broad to describe a business concept.
GENERIC_GENRES = {
    "place", "restaurant", "tourist attraction", "hotel", "shopping", "landmark", "event venue",
    "wedding venue", "bar", "park", "lodging", "food", "store", "point of interest", "american",
}

# Strong local interests that are not a storefront business, used as taste cues for the design instead.
TASTE_CUE_GENRES = {
    "museum", "art museum", "history museum", "art gallery", "garden", "library", "theater",
    "performing arts theater", "stadium", "zoo", "aquarium", "church", "mosque", "temple",
    "university", "school", "hospital", "cemetery", "monument", "historical landmark", "beach",
    "concert hall", "opera house", "national park", "state park",
}

COMPLAINT_PATTERN = re.compile(
    r"\b(slow|rude|expensive|overpriced|pricey|dirty|noisy|loud|noise|crowded|wait(ing)?|queue|lines?|"
    r"cramped|tight|small portions?|bland|salty|smell|smelly|broken|disappoint\w*|mediocre|poor|bad|worst|"
    r"unfriendly|parking|no seating|hygiene|stale|burnt|greasy|touts?|cold food|unhelpful)\b",
    re.IGNORECASE,
)

# Menu items and names that contain complaint words but are not complaints.
NOT_COMPLAINT_PATTERN = re.compile(
    r"\bdirty (martinis?|chai|rice|fries|soda|horchata)\b|\bwait ?staff\b|\bbad bunny\b|\bline ?cooks?\b|"
    r"\bpoor man'?s\b|\bloud(er)? than words\b",
    re.IGNORECASE,
)

DESIGN_FAMILIES = {
    "decor": "urn:tag:decor",
    "setting": "urn:tag:setting",
    "ambience": "urn:tag:ambience",
    "menu": "urn:tag:menu_highlight",
    "offerings": "urn:tag:offerings",
    "cuisine": "urn:tag:cuisine",
    "amenities": "urn:tag:amenity",
    "activities": "urn:tag:activity_type",
    "interests": "urn:tag:interests",
}

# Qloo returns raw catalog names; keep slurs out of the UI.
OFFENSIVE_PATTERN = re.compile(r"n[i1!]gg(a|ah|as|az|er|ers)\b|f[a@]gg?[o0]ts?\b|r[e3]t[a@]rd", re.IGNORECASE)


def is_safe_name(name: str | None) -> bool:
    return bool(name) and not OFFENSIVE_PATTERN.search(name)


FOCUS_KEYWORDS = {
    "food_drink": (
        "restaurant", "cafe", "café", "coffee", "bar", "brunch", "bakery", "pub", "lounge", "wine", "cocktail",
        "tea", "juice", "dessert", "ice cream", "pizza", "burger", "sushi", "ramen", "diner", "deli", "grill",
        "steak", "seafood", "kitchen", "bistro", "brasserie", "taco", "noodle", "food", "dining", "american",
        "italian", "french", "mexican", "japanese", "thai", "chinese", "korean", "indian", "mediterranean",
        "middle eastern", "lebanese", "egyptian", "greek", "spanish", "vegan", "vegetarian", "fast food",
        "takeout", "caterer", "patisserie", "donut", "brewery", "koshari", "shawarma", "falafel",
    ),
    "retail": (
        "shop", "store", "boutique", "market", "mall", "florist", "bookstore", "book store", "clothing",
        "jewelry", "jewellery", "furniture", "gift", "record", "pharmacy", "grocery", "supermarket", "outlet",
    ),
    "leisure": (
        "gym", "fitness", "yoga", "pilates", "studio", "spa", "salon", "club", "venue", "cinema", "movie",
        "bowling", "climbing", "karaoke", "comedy", "music", "dance", "arcade", "game", "sports", "lounge",
    ),
}


def matches_focus(genre_name: str, focus: str) -> bool:
    keywords = FOCUS_KEYWORDS.get(focus)
    if not keywords:
        return True
    lowered = genre_name.lower()
    return any(re.search(rf"\b{re.escape(word)}(s|es)?\b", lowered) for word in keywords)


def entities(data: dict) -> list[dict]:
    results = data.get("results")
    return (results.get("entities") or []) if isinstance(results, dict) else []


def tags(data: dict) -> list[dict]:
    results = data.get("results")
    return (results.get("tags") or []) if isinstance(results, dict) else []


def item_id(item: dict) -> str | None:
    return item.get("entity_id") or item.get("tag_id") or item.get("id")


def tag_id(tag: dict) -> str | None:
    return tag.get("id") or tag.get("tag_id")


def genre_tags(entity: dict) -> list[tuple[str, str]]:
    return [
        (tag_id(t), t["name"])
        for t in entity.get("tags") or []
        if t.get("type") == GENRE_TYPE and t.get("name") and tag_id(t)
    ]


def is_business_genre(name: str) -> bool:
    lowered = name.strip().lower()
    return lowered not in GENERIC_GENRES and lowered not in TASTE_CUE_GENRES


def is_taste_cue(name: str) -> bool:
    return name.strip().lower() in TASTE_CUE_GENRES


def is_complaint(keyword: str) -> bool:
    keyword = keyword or ""
    return bool(COMPLAINT_PATTERN.search(NOT_COMPLAINT_PATTERN.sub("", keyword)))


def place_location(entity: dict) -> tuple[float, float] | None:
    location = entity.get("location") or {}
    lat, lon = location.get("lat"), location.get("lon")
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def audience_growth(entity: dict) -> float | None:
    return ((entity.get("query") or {}).get("measurements") or {}).get("audience_growth")


def place_card(entity: dict, site: tuple[float, float] | None = None) -> dict:
    """Compact, UI-friendly view of a place entity."""
    props = entity.get("properties") or {}
    keywords = props.get("keywords") or []
    location = place_location(entity)
    card = {
        "id": item_id(entity),
        "name": entity.get("name"),
        "address": props.get("address"),
        "rating": props.get("business_rating"),
        "price_level": props.get("price_level"),
        "genres": [name for _, name in genre_tags(entity) if is_business_genre(name)][:3],
        "praise": [k["name"] for k in keywords if k.get("name") and not is_complaint(k["name"])][:4],
        "complaints": [k["name"] for k in keywords if k.get("name") and is_complaint(k["name"])][:3],
        "growth": audience_growth(entity),
        "lat": location[0] if location else None,
        "lon": location[1] if location else None,
        "image": (props.get("image") or {}).get("url"),
    }
    if site and location:
        card["distance_m"] = round(distance_m(site[0], site[1], *location))
    return card


def summarize_block(places: Iterable[dict]) -> dict:
    places = list(places)
    genres: Counter = Counter()
    praise: Counter = Counter()
    complaints: Counter = Counter()
    prices: Counter = Counter()
    ratings: list[float] = []
    rising: list[tuple[str, float]] = []
    fading: list[tuple[str, float]] = []
    for place in places:
        props = place.get("properties") or {}
        for _, name in genre_tags(place):
            if is_business_genre(name):
                genres[name] += 1
        if props.get("business_rating"):
            ratings.append(float(props["business_rating"]))
        if props.get("price_level"):
            prices[int(props["price_level"])] += 1
        for keyword in props.get("keywords") or []:
            name = keyword.get("name")
            if not name:
                continue
            (complaints if is_complaint(name) else praise)[name] += int(keyword.get("count") or 0)
        growth = audience_growth(place)
        if growth:
            (rising if growth > 0 else fading).append((place.get("name"), round(growth, 2)))
    return {
        "place_count": len(places),
        "top_genres": genres.most_common(12),
        "avg_rating": round(mean(ratings), 2) if ratings else None,
        "price_levels": {str(level): count for level, count in sorted(prices.items())},
        "praise": praise.most_common(12),
        "complaints": complaints.most_common(10),
        "rising": sorted(rising, key=lambda item: -item[1])[:6],
        "fading": sorted(fading, key=lambda item: item[1])[:6],
    }


def gap_score(rank: int, total: int, nearby_count: int, leakage: float) -> int:
    """0-100. High when locals rank the genre highly, few exist nearby, and their favorites are far away."""
    demand = 1 - (rank - 1) / total if total else 0.0
    saturation = nearby_count / (nearby_count + 10)
    return round(100 * demand * (0.5 + 0.5 * leakage) * (1 - saturation))


def gap_row(
    genre_id: str,
    genre_name: str,
    rank: int,
    total: int,
    nearby: list[dict],
    favorites: list[dict],
    site: tuple[float, float],
    walk_radius_m: int,
) -> dict:
    distances = [distance_m(site[0], site[1], *loc) for loc in (place_location(f) for f in favorites) if loc]
    far = [d for d in distances if d > walk_radius_m]
    leakage = len(far) / len(distances) if distances else 0.5
    return {
        "genre_id": genre_id,
        "genre": genre_name,
        "demand_rank": rank,
        "nearby_count": len(nearby),
        "nearby_capped": len(nearby) >= 50,
        "favorites_total": len(distances),
        "favorites_far": len(far),
        "median_favorite_km": round(median(distances) / 1000, 1) if distances else None,
        "gap_score": gap_score(rank, total, len(nearby), leakage),
    }


def distinctive(local: list[dict], baseline: list[dict], limit: int = 8) -> list[dict]:
    """Entities that rank for the neighborhood but not for the wider metro baseline."""
    baseline_ids = {item_id(e) for e in baseline}
    return [e for e in local if item_id(e) not in baseline_ids and is_safe_name(e.get("name"))][:limit]


def design_dna(places: Iterable[dict], per_family: int = 6) -> dict:
    """Most common design-relevant tags and praise keywords across a set of places."""
    places = list(places)
    dna: dict[str, list[str]] = {}
    for family, prefix in DESIGN_FAMILIES.items():
        counts = Counter(
            t["name"]
            for place in places
            for t in place.get("tags") or []
            if (t.get("type") or "").startswith(prefix) and t.get("name")
        )
        dna[family] = [name for name, _ in counts.most_common(per_family)]
    keywords: Counter = Counter()
    price_levels: list[int] = []
    for place in places:
        props = place.get("properties") or {}
        for keyword in props.get("keywords") or []:
            if keyword.get("name") and not is_complaint(keyword["name"]):
                keywords[keyword["name"]] += int(keyword.get("count") or 0)
        if props.get("price_level"):
            price_levels.append(int(props["price_level"]))
    dna["keywords"] = [name for name, _ in keywords.most_common(10)]
    dna["typical_price_level"] = round(median(price_levels)) if price_levels else None
    return dna


def average_demographics(rows: list[dict]) -> dict | None:
    """Average Qloo age/gender skews across several demographic rows."""
    ages: dict[str, list[float]] = {}
    genders: dict[str, list[float]] = {}
    for row in rows:
        query = row.get("query") or {}
        for bucket, value in (query.get("age") or {}).items():
            ages.setdefault(bucket, []).append(float(value))
        for bucket, value in (query.get("gender") or {}).items():
            genders.setdefault(bucket, []).append(float(value))
    if not ages and not genders:
        return None
    return {
        "age": {bucket: round(mean(values), 2) for bucket, values in ages.items()},
        "gender": {bucket: round(mean(values), 2) for bucket, values in genders.items()},
    }


def entity_card(entity: dict) -> dict:
    props = entity.get("properties") or {}
    return {
        "id": item_id(entity),
        "name": entity.get("name"),
        "image": (props.get("image") or {}).get("url"),
        "popularity": round(entity.get("popularity") or 0, 3),
    }
