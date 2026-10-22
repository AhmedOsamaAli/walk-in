"""Views of a run's evidence: what the agent sees, and what each gap says in plain words.

Every sentence here is built from measured values and names real places; when the evidence says nothing (the city's
famous places are everyone's favorites), the sentence is left out rather than padded.
"""
from __future__ import annotations

import re
from collections import Counter
from statistics import median

from .. import scoring, space
from .constraints import ALCOHOL_ITEM, Constraints
from .models import RunState

PRICE_WORDS = {1: "inexpensive", 2: "moderate", 3: "pricey", 4: "high-end"}
# Thresholds the readings share: supply as a share of what a block this dense holds, demand lift, travel share.
UNDER, OVER, STRONGER, TRAVEL = 0.75, 1.35, 0.3, 0.65


def public_gap(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def annotate(run: RunState, row: dict) -> dict:
    """Adds what the owner's unit and notes allow, and the plain-words reading of the row."""
    run.constraints.adopt_unit(run.site.size_m2, run.site.kitchen)
    row["fit"] = space.fit(row["genre"], run.site.size_m2, run.site.kitchen)
    allowed, reason = run.constraints.allows_genre(scoring.genre_title(row["genre"]))
    row["ruled_out"] = None if allowed else reason
    row["reading"] = gap_reading(row)
    row["why"] = gap_evidence(row, run.site.minutes)
    row["price"] = price_evidence(row, run.constraints, block_price(run))
    return row


def fits(row: dict) -> bool:
    """Whether the unit can host the category and the owner's notes allow it."""
    return (row.get("fit") or {}).get("fits", True) and not row.get("ruled_out")


# ---------- Words ----------

# Words that keep their capital inside a sentence: nationalities and cuisines ('Mexican', 'Middle Eastern', 'Tex-Mex').
NATIONAL = re.compile(r"^[A-Z][a-z]+(an|ese|ish|ic|ian|ern)$")
NOT_NATIONAL = {"Vegan", "Organic", "Classic", "Music", "Public", "Electric", "Ethnic", "Exotic", "Comic"}
PROPER_WORDS = {"Greek", "Thai", "French", "Dutch", "Basque", "Creole", "Cajun", "Swiss", "Czech", "Kosher", "Halal"}
QUALIFIERS = {"New", "Latin", "Middle", "South", "North", "East", "West", "Central", "Southern", "Northern"}


def _proper(word: str) -> bool:
    return bool(NATIONAL.match(word)) and word not in NOT_NATIONAL or word in PROPER_WORDS or "-" in word and word[:1].isupper()


def in_sentence(genre: str) -> str:
    """A genre as it reads mid-sentence: 'Wine Bar' -> 'wine bar'; 'Mexican' and 'New American' keep their capitals."""
    words = re.sub(r"\s+restaurant$", "", genre.strip(), flags=re.IGNORECASE).split()
    kept = []
    for index, word in enumerate(words):
        qualifies = word in QUALIFIERS and index + 1 < len(words) and _proper(words[index + 1])
        kept.append(word if _proper(word) or qualifies or word.isupper() else word.lower())
    return " ".join(kept)


def places_word(count: int) -> str:
    return "place" if count == 1 else "places"


# The last word of a genre that names the place itself, and its plural ('coffee shop' -> 'coffee shops').
PLACE_PLURALS = {
    "shop": "shops", "bar": "bars", "venue": "venues", "house": "houses", "bakery": "bakeries", "brewery": "breweries",
    "club": "clubs", "cafe": "cafes", "café": "cafés", "restaurant": "restaurants", "pub": "pubs", "hall": "halls",
    "studio": "studios", "gallery": "galleries", "salon": "salons", "spa": "spas", "gym": "gyms", "store": "stores",
    "kitchen": "kitchens", "lounge": "lounges", "diner": "diners", "deli": "delis", "bistro": "bistros",
    "pizzeria": "pizzerias", "taproom": "taprooms", "boutique": "boutiques", "market": "markets", "parlor": "parlors",
    "parlour": "parlours", "eatery": "eateries", "bookstore": "bookstores", "theater": "theaters", "theatre": "theatres",
    "cafeteria": "cafeterias", "steakhouse": "steakhouses", "roastery": "roasteries", "barbershop": "barbershops",
}


def plural(genre: str) -> str:
    """'Coffee shop' -> 'coffee shops', 'Seafood' -> 'seafood places', 'Bar + Grill' -> 'bar + grill places'."""
    phrase = in_sentence(genre)
    *head, last = phrase.split()
    if last.lower() in PLACE_PLURALS and not {"+", "&"} & set(phrase):
        return " ".join([*head, PLACE_PLURALS[last.lower()]])
    return f"{phrase} places"


def singular(genre: str) -> str:
    """'Coffee shop' -> 'coffee shop', 'Seafood' -> 'seafood place'."""
    phrase = in_sentence(genre)
    last = phrase.split()[-1].lower()
    return phrase if last in PLACE_PLURALS and not {"+", "&"} & set(phrase) else f"{phrase} place"


def count_of(genre: str, count: int, capped: bool = False) -> str:
    """'No coffee shop', '1 coffee shop', '7 coffee shops', '50+ coffee shops'."""
    if count == 0:
        return f"No {singular(genre)}"
    return f"{count}{'+' if capped else ''} {singular(genre) if count == 1 else plural(genre)}"


def dollars(level: int | None) -> str:
    return "$" * level if level else ""


def price_text(level: int | None) -> str:
    return f"{dollars(level)} ({PRICE_WORDS[level]})" if level in PRICE_WORDS else "not listed"


def number(value: float) -> str:
    return f"{value:g}"


# ---------- Places of the genre ----------

def storefront_favorites(row: dict) -> tuple[list[dict], list[dict]]:
    """The favorite places of people here of a genre, without hotels and malls, as (entities, cards), main-genre places
    first."""
    pairs = [
        (entity, card) for entity, card in zip(row["_favorite_entities"], row["favorites"], strict=True)
        if scoring.is_storefront_place(entity)
    ]
    return [entity for entity, _ in pairs], [card for _, card in pairs]


def example_places(row: dict) -> list[dict]:
    """The favorites whose main genre this is, when there are at least two; otherwise every storefront favorite."""
    entities, _ = storefront_favorites(row)
    main = [e for e in entities if scoring.relevance_tier(e, row["genre_id"], row["genre"]) == 1]
    return main if len(main) >= 2 else entities


def competitor_places(row: dict) -> list[dict]:
    """Places of the genre inside the walk that are that kind of business in earnest."""
    return scoring.relevant(row.get("_nearby_entities") or [], row["genre_id"], row["genre"])


def _price(place: dict) -> int | None:
    level = (place.get("properties") or {}).get("price_level")
    return int(level) if isinstance(level, int | float) and 1 <= level <= 4 else None


def _median_level(places: list[dict]) -> tuple[int | None, int]:
    levels = [level for level in (_price(p) for p in places) if level]
    return (round(median(levels)) if levels else None), len(levels)


PRICE_TIERS = (1, 2, 3, 4)


def price_ladder(row: dict) -> list[dict]:
    """How many of the places people here love, and of the places inside the walk, sit at each of Qloo's four price
    levels."""
    loved, inside = example_places(row), competitor_places(row)
    return [
        {"level": tier, "loved": sum(_price(p) == tier for p in loved), "inside": sum(_price(p) == tier for p in inside)}
        for tier in PRICE_TIERS
    ]


def open_price_note(row: dict, ladder: list[dict]) -> str | None:
    """A price level at least two of the places people here love charge that no place inside the walk does; only said
    when the walk has priced places of the kind, so it is a gap in price and not in the category."""
    inside = sum(step["inside"] for step in ladder)
    loved = sum(step["loved"] for step in ladder)
    open_steps = [step for step in ladder if step["loved"] >= 2 and not step["inside"]]
    if not inside or not open_steps:
        return None
    step = max(open_steps, key=lambda s: (s["loved"], s["level"]))
    level = dollars(step["level"])
    priced = "" if loved == len(example_places(row)) else " that list a price"
    return (f"No {level} {singular(row['genre'])} inside the walk, while {step['loved']} of the {loved} "
            f"{plural(row['genre'])} people here love{priced} are {level}: that price level is open.")


def price_anchors(row: dict, level: int | None, limit: int = 3) -> list[dict]:
    """Real places at this price level whose menus an owner can check: the places people here love first, then the
    places inside the walk; places with a menu page or a website first."""
    if not level:
        return []
    inside = competitor_places(row)
    inside_ids = {scoring.item_id(p) for p in inside}
    anchors: list[dict] = []
    seen: set[str] = set()
    for group in (example_places(row), inside):
        for place in sorted((p for p in group if _price(p) == level), key=lambda p: scoring.place_link(p)[0] is None):
            name = place.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            url, link = scoring.place_link(place)
            anchors.append({"name": name, "level": level, "url": url, "link": link,
                            "within_walk": scoring.item_id(place) in inside_ids})
            if len(anchors) >= limit:
                return anchors
    return anchors


def block_price(run: RunState) -> dict | None:
    """The median price level of every place inside the walk that lists one, and how many do."""
    level, count = _median_level(run.block)
    return {"level": level, "places": count} if level else None


def budget_position(row: dict, nearby: int | None, nearby_n: int, block: dict | None) -> dict:
    """Where a budget concept ($) sits against what the block charges: the places of its kind inside the walk when they
    list prices, otherwise every place inside the walk that does. `line` is the short form, `basis` the full sentence."""
    kind = plural(row["genre"])
    if nearby:
        usual, scope, places = nearby, "category", nearby_n
        whose = f" for {kind}"
        source = f"the median of the {nearby_n} inside the walk"
    elif block:
        usual, scope, places = block["level"], "block", block["places"]
        whose = ""
        source = f"the median of the {block['places']} places inside the walk that list a price"
    else:
        return {"level": 1, "usual": None, "scope": None, "places": 0, "below": False,
                "line": "Budget: $, the lowest level Qloo lists.",
                "basis": "Budget, as your notes ask: $, the lowest level; Qloo lists no prices inside the walk to compare with."}
    if usual > 1:
        line = f"Budget: $, below the block's usual {dollars(usual)}{whose}."
        basis = f"Budget, as your notes ask: $, below the block's usual {dollars(usual)}{whose} ({source})."
    else:
        line = f"Budget: $, the lowest level; the block's usual{whose} is $ too, so win on value."
        basis = (f"Budget, as your notes ask: $, the lowest level; the block's usual{whose} is $ too ({source}), so the "
                 f"concept wins on value and speed.")
    return {"level": 1, "usual": usual, "scope": scope, "places": places, "below": usual > 1, "line": line, "basis": basis}


def price_evidence(row: dict, constraints: Constraints | None = None, block: dict | None = None) -> dict:
    """The price level the evidence supports: what the places people here love charge, against the places inside the
    walk. Budget notes set the lowest level and say where it sits against the block (`block`: block_price)."""
    loved, loved_n = _median_level(example_places(row))
    nearby, nearby_n = _median_level(competitor_places(row))
    level = loved or nearby
    parts = []
    if loved:
        parts.append(f"the {plural(row['genre'])} people here love are {dollars(loved)} (median of {loved_n})")
    if nearby:
        verb = "is" if nearby_n == 1 else "are"
        parts.append(f"the {nearby_n} inside the walk {verb} {dollars(nearby)}" if loved else
                     f"{count_of(row['genre'], nearby_n)} inside the walk {verb} {dollars(nearby)} (median)")
    basis = "; ".join(parts)
    basis = basis[:1].upper() + basis[1:] + "." if basis else f"Qloo lists no prices for {plural(row['genre'])} here."
    chosen = constraints.price_level(level) if constraints else level
    if constraints and constraints.price and level is None:
        chosen = constraints.price[0]
    budget = budget_position(row, nearby, nearby_n, block) if constraints and constraints.budget else None
    if budget:
        basis += f" {budget['basis']}"
    elif chosen != level:
        basis += f" Set to {dollars(chosen)} by your notes."
    ladder = price_ladder(row)
    out = {
        "level": chosen, "evidence_level": level, "loved": loved, "nearby": nearby, "basis": basis,
        "ladder": ladder, "open_note": open_price_note(row, ladder), "anchors": price_anchors(row, chosen),
    }
    if budget:
        out["budget"] = budget
    return out


# ---------- Who the places draw ----------

CROWD_TAG = "urn:tag:customer_identity:qloo"
# Nearly every place draws locals and regulars, so those labels say nothing about a kind of business.
CROWD_SKIP = {"locals", "regulars"}


def in_running_text(label: str) -> str:
    """'Groups of friends' -> 'groups of friends'; 'LGBTQ+ community' keeps its capitals."""
    first = label.split()[0] if label.split() else ""
    return label if first.isupper() and len(first) > 1 else label[:1].lower() + label[1:]


def tag_share(places: list[dict], tag_type: str, skip: set[str] = frozenset()) -> list[dict]:
    """Tags of one type that at least half of the places carry (and at least two), most common first, with counts."""
    counts: Counter[str] = Counter()
    for place in places:
        labels = {t.get("name") for t in place.get("tags") or [] if t.get("type") == tag_type and t.get("name")}
        counts.update(label for label in labels if label.lower() not in skip)
    need = max(2, (len(places) + 1) // 2)
    return [{"label": label, "places": n, "of": len(places)} for label, n in counts.most_common() if n >= need]


def crowd_of(row: dict, limit: int = 3) -> list[str]:
    """Who most of the places people here love of this kind draw, from Qloo's customer tags on those places."""
    return [share["label"] for share in tag_share(example_places(row), CROWD_TAG, CROWD_SKIP)][:limit]


# ---------- What to offer ----------

# Where each kind of business finds its signature: dishes for restaurants, drinks and nights for bars, what people
# come to do for venues, what is sold for shops.
OFFER_FAMILIES = {
    "food": ("menu", "offerings"),
    "bar": ("offerings", "menu", "activities"),
    "venue": ("activities", "offerings"),
    "retail": ("offerings",),
    "wellness": ("offerings", "activities", "amenities"),
}
# Review themes that are things to do, so they can headline a bar or a venue.
DOING_THEMES = {"Live music and DJs", "Shows and comedy", "Games and sports", "Speakeasy", "Late night", "Food truck"}
# Diet labels, formats and services many places list: fine to suggest to an owner, but no concept is known for them.
NOT_A_SIGNATURE = {
    "vegetarian meals", "vegan meals", "vegetarian dishes", "vegan dishes", "vegetarian food", "vegan food",
    "gluten free options", "gluten-free options", "gluten free", "organic dishes", "organic food", "healthy food",
    "prepared foods", "small plates", "all you can eat", "private dining room", "private dining", "free water refills",
    "coat check", "music performances", "live music concerts", "live music", "festivals", "event hosting",
    "private event hosting", "shopping", "sightseeing", "live music listening", "food at bar", "friend outings",
    "espresso drinks", "coffee of the day", "filtered coffee", "curated wines", "wine tasting", "beer tasting",
    "hot tea", "iced tea", "tea", "soft drinks", "juice", "water", "sodas", "soda", "fresh baked goods", "baked goods",
    "combo meals", "meals", "snacks", "drinks", "desserts", "sandwiches", "pastries",
}
NOT_AN_OFFER = re.compile(
    r"\b(seating|seats|outdoor|patio|terrace|veranda|ambiance|ambience|atmosphere|decor|interior|setting|vibe|"
    r"music selection|comfortable|inviting|parking|restroom|wi-?fi|showers?|lockers?|this place|"
    # Attributes and services, not things people come for: 'Local ingredients', 'OK to order just coffee'.
    r"ingredients|options|choices|ok to|good for|friendly|accepted|available|reservations?|takeout|take-out|delivery|"
    r"dine-?in|education|learning|braille|wheelchair|accessible|accessibility|high chairs?|changing tables?)\b",
    re.IGNORECASE,
)


def _offer_counts(places: list[dict], kind: str, genre: str = "") -> tuple[Counter, dict[str, str], dict[str, int]]:
    """Each candidate item, counted by how many of the places carry it (a tag or a review topic), its name, and the rank
    of the family it comes from for this kind of business (a restaurant's dishes before its drinks)."""
    families = OFFER_FAMILIES.get(kind, OFFER_FAMILIES["food"])
    menu_rank = families.index("menu") if "menu" in families else len(families)
    doing_rank = families.index("activities") if "activities" in families else len(families)
    genre_words = set(_offer_key(genre).split()) - {"bar", "venue", "club", "place"}
    per_place: list[tuple[dict, dict[str, tuple[str, int]]]] = []
    for place in places:
        found: dict[str, tuple[str, int]] = {}
        for tag in place.get("tags") or []:
            rank = next((i for i, f in enumerate(families) if (tag.get("type") or "").startswith(scoring.DESIGN_FAMILIES[f])), None)
            if rank is not None and tag.get("name"):
                found.setdefault(_offer_key(tag["name"]), (tag["name"], rank))
        groups = scoring.topic_groups([place])
        if kind in ("food", "bar"):
            for group in groups["menu"]:
                found.setdefault(_offer_key(group["label"]), (group["label"][:1].upper() + group["label"][1:], menu_rank))
        if kind in ("bar", "venue"):
            for group in groups["experience"]:
                # 'Live music and DJs' says nothing new about a live music venue.
                if group["label"] in DOING_THEMES and not genre_words & set(_offer_key(group["label"]).split()):
                    found.setdefault(_offer_key(group["label"]), (group["label"], doing_rank))
        per_place.append((place, found))
    # How many places use each word in their items: a dish word ('lobster') is shared, a proper name ('Otway') is not.
    used = Counter(word for _, found in per_place for word in {w for key in found for w in key.split()})
    counts: Counter = Counter()
    names: dict[str, str] = {}
    ranks: dict[str, int] = {}
    for place, found in per_place:
        own = {word for word in _offer_key(place.get("name") or "").split() if len(word) >= 4}
        for key, (name, rank) in found.items():
            # A dish named after its own place ('Otway burger' at Otway) belongs to that place, not to a new concept.
            if not key or any(word in own and used[word] <= 1 for word in key.split()):
                continue
            counts[key] += 1
            ranks[key] = min(rank, ranks.get(key, rank))
            # The plainest wording wins: 'croissant' over 'great croissants'.
            if key not in names or len(name) < len(names[key]):
                names[key] = name[:1].upper() + name[1:]
    return counts, names, ranks


def _offer_key(item: str) -> str:
    return scoring.item_key(item)


def offer_items(row: dict, constraints: Constraints | None = None, limit: int = 4) -> list[dict]:
    """What a concept should be known for, from the places people here love: items none of the places inside the walk
    is known for come first ('new_here'), then the rest by how many favorites carry them. Items the owner's rules
    forbid (alcohol, pork, meat, anything that needs a hood or a kitchen the unit lacks) are left out."""
    kind = scoring.genre_kind(row["genre"])
    loved, names, ranks = _offer_counts(example_places(row), kind, row["genre"])
    nearby_keys = set(_offer_counts(competitor_places(row), kind, row["genre"])[0])
    items: list[dict] = []
    for key, count in sorted(loved.items(), key=lambda item: -item[1]):
        name = names[key]
        if name.lower() in scoring.GENERIC_OFFERINGS or name.lower() in NOT_A_SIGNATURE or NOT_AN_OFFER.search(name):
            continue
        if constraints and not constraints.allows_item(name):
            continue
        new_here = not any(key == other or set(key.split()) <= set(other.split()) for other in nearby_keys)
        items.append({"item": name, "key": key, "places": count, "new_here": new_here, "rank": ranks[key]})
    # A specific item covers its generic form ('Steak' adds nothing next to 'Steak frites').
    items = [i for i in items if not any(i is not j and set(i["key"].split()) < set(j["key"].split()) for j in items)]
    # What the business is known for first (a bar's drinks, then a restaurant's dishes), then what is new to the block.
    drinks_first = kind == "bar"
    items.sort(key=lambda i: (drinks_first and not ALCOHOL_ITEM.search(i["item"]), not i["new_here"], i["rank"], -i["places"]))
    # Variations of one item count once: 'Lagos old fashioned' and 'Tokyo old fashioned' are both an old fashioned.
    distinct: list[dict] = []
    for item in items:
        tail = " ".join(item["key"].split()[-2:])
        if len(item["key"].split()) < 3 or not any(" ".join(d["key"].split()[-2:]) == tail for d in distinct):
            distinct.append(item)
    return [{k: v for k, v in i.items() if k not in ("key", "rank")} for i in distinct[:limit]]


# ---------- Readings ----------

def _shape(row: dict) -> dict:
    expected = row.get("expected_nearby")
    relative = row.get("relative_supply", 1)
    under = expected is not None and (relative <= UNDER or row["nearby_count"] == 0 and expected >= 1)
    over = relative >= OVER and not row.get("around_capped")
    travel = row.get("favorites_kind") == "local" and (row.get("leakage") or 0) >= TRAVEL and row["favorites_far"] >= 3
    stronger = (row.get("lift") or 0) >= STRONGER
    weaker = (row.get("lift") or 0) <= -STRONGER
    return {"under": under, "over": over, "travel": travel, "stronger": stronger, "weaker": weaker}


def gap_reading(row: dict) -> str:
    """The row in two or three words, for a badge. The web app styles the badge by these exact labels."""
    if row.get("evidence") == "thin":
        return "Thin data"
    if row.get("evidence") == "atypical":
        return "Atypical"
    s = _shape(row)
    if s["under"] and (s["travel"] or s["stronger"]):
        return "Clear gap"
    if s["under"]:
        return "Under-supplied"
    if s["travel"]:
        return "Locals travel for it"
    if s["over"]:
        return "Crowded"
    if s["stronger"]:
        return "Loved more here"
    if row["demand_rank"] <= 3:
        return "Top demand"
    return "Steady demand"


def gap_evidence(row: dict, minutes: int = 10) -> list[str]:
    """The row in plain sentences: demand against the areas around, supply against density, where people here
    travel."""
    genre = in_sentence(row["genre"])
    lines = [_demand_line(row, genre)]
    supply = _supply_line(row, minutes)
    if supply:
        lines.append(supply)
    travel = _travel_line(row)
    if travel:
        lines.append(travel)
    if row.get("evidence") == "thin":
        lines.append(f"Thin evidence: Qloo knows at most one {singular(row['genre'])} in the surrounding area.")
    elif row.get("evidence") == "atypical":
        lines.append(f"The {plural(row['genre'])} people here love are mostly in hotels or malls, so the comparison is weak.")
    return lines


def _demand_line(row: dict, genre: str) -> str:
    rank, ref = row["demand_rank"], row.get("ref_rank")
    if rank >= scoring.UNRANKED:
        return f"People here do not rank {genre} among their top 50 place types."
    if rank == 1:
        text = f"{genre[:1].upper() + genre[1:]} is the place type people here engage with most"
    else:
        text = f"People here rank {genre} #{rank} among the place types they engage with"
    if ref is None:
        return text + "."
    ref_text = "outside the top 50" if ref >= scoring.UNRANKED else f"#{round(ref)}"
    if ref - rank >= 3:
        return f"{text}; six same-size areas around rank it {ref_text}, so demand is stronger here."
    if rank - ref >= 3:
        return f"{text}; the areas around rank it higher ({ref_text}), so demand is weaker here."
    return f"{text}, about as high as the areas around ({ref_text})."


def _supply_line(row: dict, minutes: int) -> str | None:
    nearby = row["nearby_count"]
    here = f"{count_of(row['genre'], nearby, row.get('nearby_capped'))} inside the {minutes}-minute walk"
    expected = row.get("expected_nearby")
    if expected is None:
        return f"{here}."
    typical = f"at least {number(expected)}" if row.get("around_capped") else f"about {number(expected)}"
    s = _shape(row)
    if nearby == 0:
        return f"{here}, where a block this dense usually has {typical}."
    if s["under"]:
        return f"Only {here}, where a block this dense usually has {typical}."
    if s["over"]:
        return f"{here}, more than the {typical} a block this dense usually has."
    return f"{here}, about what a block this dense holds ({typical})."


def _travel_line(row: dict) -> str | None:
    """Only places people here love more than the rest of the city does say where they travel; the city's famous places
    say nothing. The distance is the median trip to the favorites outside the walk (median_far_km); rows saved before
    it existed say no distance rather than one diluted by the favorites already close by."""
    total, far, km = row["favorites_total"], row["favorites_far"], row.get("median_far_km")
    if row.get("favorites_kind") != "local" or total < 3:
        return None
    _, cards = storefront_favorites(row)
    outside = [c["name"] for c in cards if c.get("name") and not c.get("within_walk")][:3]
    inside = [c["name"] for c in cards if c.get("name") and c.get("within_walk")][:2]
    loved = f"{plural(row['genre'])} people here love more than the rest of the city does"
    median = f" (median {km} km)" if km else ""
    if far == total:
        away = f", a median {km} km away" if km else ""
        return f"All {total} {loved} are outside the walk{away}: {scoring.natural_list(outside)}."
    if far / total >= TRAVEL:
        return f"{far} of the {total} {loved} are outside the walk{median}: {scoring.natural_list(outside)}."
    if far / total <= 0.4 and inside:
        return f"Most of the {loved} are already inside the walk ({total - far} of {total}), such as {scoring.natural_list(inside)}."
    return f"{far} of the {total} {loved} are outside the walk{median}."


def love_evidence(row: dict) -> tuple[float, str] | None:
    """How clearly people here love a category, with the evidence in words: they travel to its favorites outside the
    walk (3), rank it higher than the areas around do (2.5), or rank it among their top five place types (2). None
    when the evidence is thin, atypical or weaker than that."""
    if row.get("evidence") != "ok":
        return None
    s = _shape(row)
    rank, ref = row["demand_rank"], row.get("ref_rank")
    if s["travel"]:
        km = row.get("median_far_km")
        names = [c["name"] for c in storefront_favorites(row)[1] if c.get("name") and not c.get("within_walk")][:2]
        trip = f" a median {km} km" if km else ""
        like = f", such as {scoring.natural_list(names)}" if names else ""
        return 3.0, f"people here travel{trip} to the {plural(row['genre'])} they love most{like}"
    if s["stronger"] and rank <= 10 and ref is not None:
        return 2.5, (f"people here rank {in_sentence(row['genre'])} #{rank} among place types, higher than the areas "
                     f"around (#{round(ref)})")
    if rank <= 5:
        return 2.0, f"people here rank {in_sentence(row['genre'])} #{rank} among the place types they engage with"
    return None


# What to do about what nearby reviews complain about.
COMPLAINT_MOVES = {
    "Long waits and lines": "take bookings or run a fast counter for walk-ins",
    "Crowding": "lay the room out for comfort, not the most covers",
    "Noise": "treat the acoustics with soft ceilings and fewer hard surfaces",
    "Rude staff": "hire and train for hospitality",
    "Slow service": "design the menu and the line for speed",
    "Prices": "make the value obvious at the price point",
    "Hygiene": "keep cleanliness visible, from the counter to the restrooms",
    "Food quality": "keep a short menu that is cooked the same every time",
    "Small portions": "serve portions people talk about",
    "Parking": "point guests to transit and bike parking",
    "Broken equipment": "budget for maintenance",
    "Touts and tourist traps": "price fairly and skip the street touts",
    "Uncomfortable seats": "invest in comfortable seats",
}


def competition(row: dict, minutes: int, constraints: Constraints | None = None) -> str:
    """Who the concept competes with inside the walk, what their reviews hold against them and how to stand apart."""
    cards = [c for c in row.get("competitors") or [] if c.get("name")]
    # The best-rated rival among the places that are this business in earnest; any tagged place when none is.
    earnest = {p.get("name") for p in competitor_places(row)}
    rivals = [c for c in cards if c["name"] in earnest] or cards
    parts = []
    if not row["nearby_count"]:
        _, favorites = storefront_favorites(row)
        nearest = min((f for f in favorites if f.get("distance_m")), key=lambda f: f["distance_m"], default=None)
        parts.append(f"{count_of(row['genre'], 0)} competes inside the {minutes}-minute walk" + (
            f"; the nearest one people here love is {nearest['name']}, {nearest['distance_m'] / 1000:.1f} km away."
            if nearest else "."
        ))
    elif rivals:
        best = max(rivals, key=lambda c: (c.get("rating") or 0))
        detail = ", ".join(x for x in (f"{best['rating']}★" if best.get("rating") else "", dollars(best.get("price_level"))) if x)
        known = scoring.natural_list((best.get("known_for") or [])[:2])
        lead = (f"{count_of(row['genre'], row['nearby_count'], row.get('nearby_capped'))} inside the walk; "
                f"{'the best rated is' if row['nearby_count'] > 1 else 'it is'} {best['name']}")
        parts.append(lead + (f" ({detail})" if detail else "") + (f", known for {known}." if known else "."))
        themes = Counter(theme for c in cards for theme in c.get("complaints") or [])
        moves = [(theme, COMPLAINT_MOVES.get(theme[:1].upper() + theme[1:])) for theme, _ in themes.most_common(2)]
        moves = [(theme, move) for theme, move in moves if move]
        if moves:
            said = scoring.natural_list([theme for theme, _ in moves])
            parts.append(f"Their reviews complain about {said}: {'; '.join(move for _, move in moves)}.")
    items = [i["item"].lower() for i in offer_items(row, constraints) if i["new_here"]][:3]
    if items:
        parts.append(f"Stand apart with what the {plural(row['genre'])} people here love are known for and none inside the "
                     f"walk is: {scoring.natural_list(items)}.")
    return " ".join(parts)


def risk(row: dict, minutes: int) -> str:
    """The biggest risk the evidence shows, stated with its numbers."""
    genre = in_sentence(row["genre"])
    s = _shape(row)
    nearby = row["nearby_count"]
    if row.get("evidence") == "thin":
        return f"Thin evidence: Qloo knows at most one {singular(row['genre'])} in the surrounding area, so treat this as a hypothesis."
    if row.get("evidence") == "atypical":
        return (f"The {plural(row['genre'])} people here love are mostly in hotels or malls, so a small storefront may not "
                f"draw the same crowd.")
    if s["over"]:
        return (f"{count_of(row['genre'], nearby, row.get('nearby_capped'))} are already inside the walk, more than the block's "
                f"density predicts: you would take share, not fill a gap.")
    if s["weaker"]:
        return (f"People here rank {genre} lower than the areas around do (#{row['demand_rank']} against "
                f"#{round(row['ref_rank'])}).")
    if nearby >= 8:
        return f"{count_of(row['genre'], nearby, row.get('nearby_capped'))} already compete inside the {minutes}-minute walk."
    if row.get("favorites_kind") != "local":
        return (f"No sign that people here travel for {plural(row['genre'])}: their favorites are the city's famous ones, so "
                f"the case rests on the ranking and the supply count.")
    return "Qloo measures taste, not foot traffic: count passers-by at the door on a weekday and a weekend before signing."


# ---------- What the agent sees ----------

def evidence_brief(run: RunState) -> dict:
    """Compact evidence pack handed to the LLM."""
    s = run.summary
    walk = run.catchment
    site = run.site
    brief = {
        "site": {"label": site.label, "focus": site.focus, "owner_notes": site.notes or None},
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
            "what_reviews_mention": {
                "menu": [mention_text(g) for g in s.get("menu", [])[:8]],
                "experience": [mention_text(g) for g in s.get("experience", [])[:8]],
                "complaints": [mention_text(g) for g in s.get("complaints", [])[:6]],
            },
        },
        "gap_table": [gap_summary(g) for g in run.gaps],
        "taste_cues": run.cues,
        "brands_this_area_over_indexes_on": [b["name"] for b in run.taste.get("distinctive_brands", [])],
        "artists_this_area_over_indexes_on": [a["name"] for a in run.taste.get("distinctive_artists", [])],
        "films_and_shows_this_area_over_indexes_on": [
            f"{c['name']} ({c['year']})" if c.get("year") else c["name"]
            for c in run.taste.get("distinctive_movies", [])[:5] + run.taste.get("distinctive_tv", [])[:5]
        ],
        "podcasts_this_area_over_indexes_on": [p["name"] for p in run.taste.get("distinctive_podcasts", [])[:5]],
    }
    rules = run.constraints.as_evidence()
    if rules:
        brief["owner_constraints"] = rules
    unit = space.unit_text(site.size_m2, site.kitchen, site.outdoor)
    if unit:
        brief["unit"] = unit
    verdict = run.verdict
    if verdict and verdict.get("found"):
        row = next((r for r in run.gaps + run.explored if r["genre_id"] == verdict["genre_id"]), None)
        brief["owner_request"] = {
            "genre": verdict["genre"], "verdict": verdict["headline"], "rank_among_gaps": f"#{verdict['position']} of {verdict['of']}",
            "evidence": gap_summary(row) if row else None,
        }
    return brief


def mention_text(group: dict) -> str:
    """A review topic group in words: 'Long waits and lines (6,071 mentions at 75 places)'."""
    mentions, places = group["mentions"], group["places"]
    return f"{group['label']} ({mentions:,} mention{'' if mentions == 1 else 's'} at {places} place{'' if places == 1 else 's'})"


def gap_summary(g: dict) -> dict:
    """One gap row as the agent sees it: comparisons are stated in words, so they cannot be misread."""
    if g["favorites_kind"] == "local" and g["favorites_total"]:
        km = g.get("median_far_km")
        travel = (
            f"{g['favorites_far']} of the {g['favorites_total']} places people here love more than the rest of the city "
            f"does are outside the walk" + (f"; those are a median {km} km away" if km else "")
        )
    else:
        travel = "no evidence: the favorites of people here of this type are just the city's famous places"
    summary = {
        "genre": g["genre"],
        "reading": g.get("reading") or gap_reading(g),
        "people_here_rank_it": g["demand_rank"] if g["demand_rank"] < scoring.UNRANKED else "outside their top 50",
        "median_rank_in_6_same_size_areas_around": g["ref_rank"],
        "demand_compared_with_areas_around": demand_comparison(g),
        "places_within_walk": f"{g['nearby_count']}{'+' if g['nearby_capped'] else ''}",
        "typical_for_a_block_this_dense": (
            f"at least {g['expected_nearby']}" if g.get("around_capped") and g["expected_nearby"] is not None else g["expected_nearby"]
        ),
        "relative_supply": g["relative_supply"],
        "do_people_here_travel_for_it": travel,
        "evidence": g["evidence"],
        "gap_score": g["gap_score"],
    }
    price = g.get("price")
    if price and price.get("evidence_level"):
        summary["price_evidence"] = price["basis"]
    fit = g.get("fit")
    if fit:
        summary["fits_the_unit"] = "yes" if fit["fits"] else f"no: {fit['reason']}"
        if fit.get("capacity_text"):
            summary["unit_capacity"] = fit["capacity_text"]
    if g.get("ruled_out"):
        summary["ruled_out_by_owner_notes"] = g["ruled_out"]
    return summary


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
    # Only places people here love more than the rest of the city does say anything about travel; otherwise they are
    # just the city's famous places, and naming them that way keeps the agent from claiming that people travel to them.
    favorites_key = (
        "places_people_here_love_more_than_the_rest_of_the_city_does" if row.get("favorites_kind") == "local"
        else "the_citys_famous_places_of_this_type"
    )
    offer = offer_items(row, run.constraints, limit=8)
    return {
        "genre": row["genre"],
        "competitors_within_walk": [
            {k: c.get(k) for k in ("name", "rating", "price_level", "known_for", "complaints", "distance_m")}
            for c in row["competitors"][:6]
        ],
        favorites_key: [
            {"name": f["name"], "km_away": round((f.get("distance_m") or 0) / 1000, 1), "price_level": f.get("price_level"),
             "known_for": f.get("known_for"), "inside_walk": f.get("within_walk", False)}
            for f in cards[:8]
        ],
        "do_people_here_travel_for_it": gap_summary(row)["do_people_here_travel_for_it"],
        "menu_gap": [i["item"] for i in offer if i["new_here"]],
        "also_offered_inside_the_walk": [i["item"] for i in offer if not i["new_here"]],
        "price_evidence": (row.get("price") or price_evidence(row, run.constraints, block_price(run)))["basis"],
        "design_dna_of_these_places": scoring.design_dna(entities),
    }


def short_label(label: str) -> str:
    """'Upper East Side, Manhattan' -> 'Upper East Side'; falls back to a neutral word for raw pins."""
    first = (label or "").split(",")[0].strip()
    if not first or first.lower() in {"selected site", "dropped pin"} or any(ch.isdigit() for ch in first[:3]):
        return "Corner"
    return first[:32]
