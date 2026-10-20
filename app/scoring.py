"""Pure scoring and summarizing logic over Qloo responses (no network calls)."""
from __future__ import annotations

import re
from collections import Counter
from statistics import mean, median
from typing import Callable, Iterable

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

# Real place types that cannot fit in a vacant storefront.
NOT_STOREFRONT_GENRES = {
    "shopping mall", "resort hotel", "hotel", "motel", "hostel", "inn", "casino", "amusement park",
    "theme park", "water park", "golf course", "arena", "airport", "train station", "marina",
    "campground", "ski resort", "convention center", "department store", "supermarket", "hypermarket",
    "stadium", "amphitheater", "amphitheatre", "banquet hall",
}

# Offerings so common they say nothing about a concept; used only when nothing more specific exists.
GENERIC_OFFERINGS = {
    "alcohol", "hard liquor", "beer", "wine", "coffee", "food", "drinks", "corporate events", "wedding services",
    "marketplace", "private events", "event space", "catering", "parking", "restroom", "vegetarian options",
    "vegan options", "quick bite", "comfort food", "healthy options", "kids menu", "late-night food", "late night food", "dine-in",
    "takeout", "delivery", "seating", "outdoor seating", "wi fi", "wifi", "bar", "full bar", "restaurant",
    # Activity and attribute tags that describe nearly every bar or restaurant.
    "dining drinking", "social community", "nightlife", "entertainment", "ok to order just drinks",
    "sports recreation", "culture arts", "nature outdoors", "tours", "celebrations",
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
# "not crowded", "no wait": a complaint word that is negated reads as praise.
NEGATED_PATTERN = re.compile(r"^\s*(not|never|no longer|hardly)\s+|\bno (wait|waiting|lines?|queues?|crowds?)\b", re.IGNORECASE)
NON_COMMERCIAL_BRAND = re.compile(r"nonprofit|non-profit|political|government|religious|advocacy", re.IGNORECASE)
# Makers, shops and designers can co-brand with a small storefront; media groups and corporations cannot.
# Teams (Qloo's "entertainment" brands) are added for sports concepts only.
PARTNER_BRAND_KINDS = {"product", "retail", "personal"}

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
        "restaurant", "cafe", "café", "coffee", "bar", "brunch", "breakfast", "bakery", "pub", "lounge", "wine",
        "cocktail", "tea", "juice", "dessert", "ice cream", "pizza", "burger", "hamburger", "sandwich", "sushi",
        "ramen", "diner", "deli", "grill", "steak", "steak house", "seafood", "kitchen", "bistro", "brasserie",
        "taco", "tex-mex", "noodle", "food", "dining", "american", "italian", "french", "mexican", "japanese",
        "thai", "chinese", "korean", "indian", "mediterranean", "middle eastern", "lebanese", "egyptian", "greek",
        "spanish", "tapas", "vegan", "vegetarian", "fast food", "takeout", "caterer", "patisserie", "donut",
        "brewery", "barbecue", "bbq", "gastropub", "koshari", "shawarma", "falafel", "kebab", "shisha", "hookah",
    ),
    "retail": (
        "shop", "store", "boutique", "market", "florist", "bookstore", "book store", "clothing", "fashion",
        "accessories", "jewelry", "jewellery", "furniture", "gift", "record", "pharmacy", "grocery", "outlet",
        "shoe", "cosmetics", "electronics", "toy", "pet", "bike", "optician", "hardware", "thrift", "vintage",
    ),
    "leisure": (
        "gym", "fitness", "yoga", "pilates", "studio", "spa", "salon", "barber", "nail", "beauty", "massage",
        "wellness", "personal care", "tattoo", "club", "venue", "cinema", "movie", "bowling", "climbing",
        "karaoke", "comedy", "music", "dance", "arcade", "game", "sports", "lounge", "coworking",
    ),
}


def matches_focus(genre_name: str, focus: str) -> bool:
    keywords = FOCUS_KEYWORDS.get(focus)
    if not keywords:
        return True
    lowered = genre_name.lower()
    return any(re.search(rf"\b{re.escape(word)}(s|es)?\b", lowered) for word in keywords)


VENUE_WORDS = ("bar", "lounge", "pub", "brewery", "taproom", "club", "venue", "music", "karaoke", "comedy", "cinema", "bowling", "arcade")
WELLNESS_WORDS = ("spa", "salon", "personal care", "barber", "nail", "beauty", "massage", "gym", "fitness", "yoga", "pilates", "wellness", "tattoo")


def _has_word(text: str, words: Iterable[str]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}s?\b", text) for word in words)


def genre_kind(genre: str) -> str:
    lowered = genre.lower()
    if _has_word(lowered, WELLNESS_WORDS):
        return "wellness"
    if _has_word(lowered, VENUE_WORDS):
        return "venue"
    if matches_focus(genre, "retail") and not matches_focus(genre, "food_drink"):
        return "retail"
    return "food"


def signature_items(genre: str, dna: dict, limit: int = 3) -> list[str]:
    """What a concept of this genre should be known for: menus for restaurants, offerings for venues and shops."""
    kind = genre_kind(genre)
    if kind == "food":
        items = (dna.get("menu") or []) + (dna.get("offerings") or [])
    elif kind == "venue":
        # What people go there to do comes first: game day viewing, concerts, brewery tours.
        items = (dna.get("activities") or []) + (dna.get("offerings") or []) + (dna.get("menu") or [])
    else:
        items = (dna.get("offerings") or []) + (dna.get("amenities") or []) + (dna.get("activities") or [])
    unique: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item.lower() not in seen:
            seen.add(item.lower())
            unique.append(item)
    specific = [item for item in unique if item.lower() not in GENERIC_OFFERINGS]
    generic = [item for item in unique if item.lower() in GENERIC_OFFERINGS]
    # "Steak" adds nothing next to "Steak frites"; only specific items can cover others.
    covering = [_words(item) for item in specific]
    specific = [item for item in specific if not any(_words(item) < other for other in covering)]
    generic = [item for item in generic if not any(_words(item) < other for other in covering)]
    # Generic items only pad a short list; they never trail specific ones.
    if len(specific) >= min(limit, 3):
        return specific[:limit]
    return (specific + generic)[: min(limit, 3)]


def _words(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", text.lower()))


def genre_title(name: str) -> str:
    """'Fine dining restaurant' -> 'Fine Dining'; keeps 'Tex-Mex', 'New American' and 'Bar + Grill' intact."""
    base = re.sub(r"\s+restaurant$", "", name.strip(), flags=re.IGNORECASE) or name.strip()
    keep = {"and", "or", "of", "the", "+", "&"}
    words = [w if w.lower() in keep or "-" in w or any(c.isupper() for c in w[1:]) else w[:1].upper() + w[1:] for w in base.split()]
    return " ".join(words)


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
    return lowered not in GENERIC_GENRES and lowered not in TASTE_CUE_GENRES and lowered not in NOT_STOREFRONT_GENRES


def is_taste_cue(name: str) -> bool:
    return name.strip().lower() in TASTE_CUE_GENRES


def is_complaint(keyword: str) -> bool:
    keyword = keyword or ""
    if NEGATED_PATTERN.search(keyword):
        return False
    return bool(COMPLAINT_PATTERN.search(NOT_COMPLAINT_PATTERN.sub("", keyword)))


def is_storefront_place(entity: dict) -> bool:
    """False for hotels, malls and other places whose design cannot inspire a small storefront."""
    return not any(name.lower() in NOT_STOREFRONT_GENRES for _, name in genre_tags(entity))


def is_commercial_brand(entity: dict) -> bool:
    for tag in entity.get("tags") or []:
        if tag.get("type") in ("urn:tag:brand_type:qloo", "urn:tag:business_model:qloo") and NON_COMMERCIAL_BRAND.search(tag.get("name") or ""):
            return False
    return True


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


def reference_rank(ranks: list[int | None], missing: int = 51) -> float | None:
    """Median rank of a genre across same-size reference areas; absent genres count as rank `missing`."""
    if not ranks:
        return None
    return float(median([rank if rank is not None else missing for rank in ranks]))


def split_favorites(local: list[dict], city: list[dict], minimum: int = 4) -> tuple[str, list[dict]]:
    """Places locals love more than the city does ('local'), or, if too few, the shared list ('citywide')."""
    city_ids = {item_id(e) for e in city}
    own = [e for e in local if item_id(e) not in city_ids]
    if len(own) >= minimum:
        return "local", own[:10]
    return "citywide", local[:10]


def storefront_share(places: list[dict]) -> float:
    return sum(1 for p in places if is_storefront_place(p)) / len(places) if places else 1.0


def gap_signals(
    genre_id: str,
    genre_name: str,
    local_rank: int,
    ref_rank: float | None,
    nearby: list[dict],
    around: list[dict],
    favorites: list[dict],
    favorites_kind: str,
    storefront: float,
    site: tuple[float, float],
    within: Callable[[float, float], bool],
) -> dict:
    """Raw evidence for one genre. `within(lat, lon)` says whether a point is inside the walking catchment."""
    locations = [loc for loc in (place_location(f) for f in favorites) if loc]
    distances = [distance_m(site[0], site[1], *loc) for loc in locations]
    far = [loc for loc in locations if not within(*loc)]
    return {
        "genre_id": genre_id,
        "genre": genre_name,
        "demand_rank": local_rank,
        "ref_rank": ref_rank,
        "nearby_count": len(nearby),
        "nearby_capped": len(nearby) >= 50,
        "around_count": len(around),
        "around_capped": len(around) >= 50,
        "favorites_kind": favorites_kind,
        "favorites_total": len(locations),
        "favorites_far": len(far),
        "median_favorite_km": round(median(distances) / 1000, 1) if distances else None,
        "storefront_share": round(storefront, 2),
    }


def score_gaps(rows: list[dict], catchment_area_m2: float, around_area_m2: float) -> list[dict]:
    """Score every genre against same-size areas around the site (demand) and its own surroundings (supply).

    - demand: how highly locals rank the genre, plus how much higher they rank it than six same-size
      areas around the site do (comparing against the whole city inflates genres that rank high at any
      small scale);
    - supply: places within the walk versus what the surrounding density predicts, divided by the site's
      median ratio so parks, rivers and highways in the surroundings do not bias every genre;
    - leakage: share of the places locals love more than the city does that lie outside the walk. The
      city's famous places are excluded because every neighborhood's favorites include them.
    """
    if not rows:
        return []
    area_ratio = catchment_area_m2 / around_area_m2 if around_area_m2 else 0.25
    for row in rows:
        row["expected_raw"] = round(row["around_count"] * area_ratio, 2)
        # One pseudo-count on both sides: finding none where the surroundings predict 0.25 is not evidence of a gap.
        row["_ratio"] = (row["nearby_count"] + 1) / (row["expected_raw"] + 1)
    informative = [row["_ratio"] for row in rows if row["around_count"] >= 3]
    baseline = median(informative) if informative else 1.0
    baseline = baseline if baseline > 0 else 1.0
    for row in rows:
        local = row["demand_rank"]
        ref = row.get("ref_rank")
        lift = 0.0 if ref is None else max(-1.0, min(1.0, (ref - local) / 10))
        demand = 0.55 * max(0.0, 1 - (local - 1) / 15) + 0.45 * (lift + 1) / 2
        relative = row.pop("_ratio") / baseline
        undersupply = 0.8 / (1 + relative) + 0.2 * (1 - row["nearby_count"] / (row["nearby_count"] + 6))
        total = row["favorites_total"]
        leakage = None
        if row.get("favorites_kind") == "local" and total >= 3:
            # Shrink small samples toward "no information" (0.5).
            leakage = (row["favorites_far"] + 1) / (total + 2)
        if row["around_count"] < 2:
            evidence = "thin"
        elif row.get("storefront_share", 1.0) < 0.5:
            evidence = "atypical"
        else:
            evidence = "ok"
        raw = demand * undersupply * (0.55 + 0.45 * (0.5 if leakage is None else leakage))
        raw *= 1.0 if evidence == "ok" else 0.55
        row.update({
            "lift": round(lift, 2),
            "relative_supply": round(relative, 2),
            # What a block this dense would typically hold, consistent with relative_supply.
            "expected_nearby": round(max(0.0, (row["expected_raw"] + 1) * baseline - 1), 1),
            "leakage": None if leakage is None else round(leakage, 2),
            "evidence": evidence,
            "gap_score": min(99, round(raw * 175)),
        })
    return sorted(rows, key=lambda row: (row["evidence"] != "ok", -row["gap_score"]))


def distinctive(local: list[dict], baseline: list[dict], limit: int = 8) -> list[dict]:
    """Entities that rank for the neighborhood but not for the wider metro baseline."""
    baseline_ids = {item_id(e) for e in baseline}
    return [e for e in local if item_id(e) not in baseline_ids and is_safe_name(e.get("name"))][:limit]


def distinctive_by_rank(
    local: list[dict], references: list[list[dict]], limit: int = 8, min_lift: float = 5, max_local_rank: int = 20,
) -> list[dict]:
    """Entities that rank much higher here than in same-size reference areas (median rank, absent = list end + 1)."""
    references = [ref for ref in references if ref]
    if not references:
        return []
    rank_maps = [({item_id(e): i for i, e in enumerate(ref, 1)}, len(ref) + 1) for ref in references]
    scored = []
    for rank, entity in enumerate(local[:max_local_rank], 1):
        eid = item_id(entity)
        if not eid or not is_safe_name(entity.get("name")):
            continue
        ref_rank = median([ranks.get(eid, missing) for ranks, missing in rank_maps])
        if ref_rank - rank >= min_lift:
            scored.append((-(ref_rank - rank), rank, entity))
    return [entity for _, _, entity in sorted(scored, key=lambda item: (item[0], item[1]))][:limit]


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
    card = {
        "id": item_id(entity),
        "name": entity.get("name"),
        "image": (props.get("image") or {}).get("url"),
        "popularity": round(entity.get("popularity") or 0, 3),
    }
    kind = brand_kind(entity)
    if kind:
        card["kind"] = kind
    return card


def brand_kind(entity: dict) -> str | None:
    """Qloo's brand type in short form: 'Product Brand' -> 'product'."""
    for tag in entity.get("tags") or []:
        if tag.get("type") == "urn:tag:brand_type:qloo" and tag.get("name"):
            return re.sub(r"\s*brand$", "", tag["name"].strip(), flags=re.IGNORECASE).lower() or None
    return None


def partner_brands(brands: list[dict], genre: str) -> list[dict]:
    """Brand cards a small storefront of this genre could realistically collaborate with."""
    kinds = PARTNER_BRAND_KINDS | ({"entertainment"} if re.search(r"sport", genre, re.IGNORECASE) else set())
    return [brand for brand in brands if brand.get("kind") in kinds]
