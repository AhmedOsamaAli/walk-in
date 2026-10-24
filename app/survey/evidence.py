"""Views of a run's evidence: what the agent sees, and what each gap says in plain words.

Every sentence here is built from measured values and names real places; when the evidence says nothing (the city's
famous places are everyone's favorites), the sentence is left out rather than padded.
"""
from __future__ import annotations

import re
from collections import Counter

from .. import scoring, space
from ..catchment import area_text
from ..demographics import ages_label
from .constraints import ALCOHOL_ITEM, Constraints
from .models import RunState

# The tag families that say what a place offers, as against how it looks or feels (decor, setting, ambience).
OFFER_TAG_FAMILIES = ("menu", "offerings", "cuisine", "amenities", "activities", "keywords")
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
    row["why"] = gap_evidence(row, run.site.area, run.site.ages)
    return row


# ---------- The area and whose taste ----------

# Every sentence takes the survey's area as `area`: its label ('10-minute walk', '30-minute drive', '25 km drive', from
# Site.area) or, from callers written before drives existed, a walk's minutes (catchment.area_text).

def is_walk(area: str | int) -> bool:
    return area_text(area).endswith(" walk")


def area_noun(area: str | int = 10) -> str:
    """The area after 'inside the' or 'outside the': 'walk' for a walk, as the evidence has always said it, else the
    whole label ('inside the 30-minute drive', 'outside the 25 km drive')."""
    return "walk" if is_walk(area) else area_text(area)


def aged(ages: str | None) -> str:
    """' aged 25–34' after the people an age focus leans the rankings and favorites toward; '' for everyone."""
    label = ages_label(ages)
    return f" aged {label[:1].lower() + label[1:]}" if label else ""


def people_here(ages: str | None = None) -> str:
    """Whose rankings and favorites the evidence reads: 'people here', or 'people here aged 25–34' with an age focus.
    Only demand and favorites lean toward the focus: supply is every place, whoever goes there."""
    return f"people here{aged(ages)}"


def capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def fits(row: dict) -> bool:
    """Whether the unit can host the category and the owner's notes allow it."""
    return (row.get("fit") or {}).get("fits", True) and not row.get("ruled_out")


# ---------- OpenStreetMap ----------

def osm_extra(row: dict) -> list[dict]:
    """The places of the kind OpenStreetMap shows inside the walk that Qloo does not list there (row['osm'])."""
    return (row.get("osm") or {}).get("extra") or []


def supply(row: dict) -> int:
    """Places of the kind inside the walk, Qloo's and OpenStreetMap's extras: what the gap is scored on."""
    return scoring.supply_count(row)


def osm_names(row: dict, limit: int = 4) -> str:
    """'Joe's Bakery & Coffee Shop and Insomnia Cookies'; past `limit` names, how many more."""
    names = [place["name"] for place in osm_extra(row)]
    if len(names) > limit:
        return f"{', '.join(names[:limit])} and {len(names) - limit} more"
    return scoring.natural_list(names)


def osm_count_text(row: dict) -> str:
    """'2 more bakeries' (beyond Qloo's), or '2 bakeries' when Qloo lists none."""
    n = len(osm_extra(row))
    kind = singular(row["genre"]) if n == 1 else plural(row["genre"])
    return f"{n} {'more ' if row['nearby_count'] else ''}{kind}"


def osm_line(row: dict, area: str | int = 10) -> str | None:
    """'OpenStreetMap shows 2 more bakeries inside the walk that Qloo doesn't list: Joe's Bakery & Coffee Shop and
    Insomnia Cookies.'"""
    if not osm_extra(row):
        return None
    return f"OpenStreetMap shows {osm_count_text(row)} inside the {area_noun(area)} that Qloo doesn't list: {osm_names(row)}."


def unchecked_line(row: dict) -> str | None:
    """Why a count of Qloo's alone was not cross-checked; None when it was, or when the cross-check is off."""
    osm = row.get("osm") or {}
    if osm.get("checked") or osm.get("reason") in (None, "off"):
        return None
    if osm["reason"] == "unmapped":
        return (f"Not cross-checked: no OpenStreetMap tag reliably marks {plural(row['genre'])}, so this count is "
                f"Qloo's alone.")
    if osm["reason"] == "too_big":
        return "Not cross-checked: the area is too large for OpenStreetMap's free servers, so this count is Qloo's alone."
    return "Not cross-checked: OpenStreetMap did not answer in time, so this count is Qloo's alone."


def osm_caution(row: dict, whose: str, unknown: str, area: str | int = 10) -> str | None:
    """'Reviews are Qloo's: OpenStreetMap shows 2 more bakeries inside the walk that Qloo doesn't list, and what they are
    known for is not known.' None when OpenStreetMap adds no place: a claim about the places Qloo lists inside the walk
    stands as stated, with this caution when there are others."""
    if not osm_extra(row):
        return None
    return (f"{whose}: OpenStreetMap shows {osm_count_text(row)} inside the {area_noun(area)} that Qloo doesn't list, "
            f"and {unknown} not known.")


def osm_check_text(row: dict, area: str | int = 10) -> str | None:
    """The cross-check in words for the agent, so it knows what the count of places inside the area holds."""
    osm = row.get("osm") or {}
    if not osm or osm.get("reason") == "off":
        return None
    if not osm.get("checked"):
        return unchecked_line(row) or osm.get("note")
    noun = area_noun(area)
    if osm_extra(row):
        return (f"the places within the {noun} are {row['nearby_count']} Qloo lists and {len(osm_extra(row))} only "
                f"OpenStreetMap shows ({osm_names(row, limit=6)}); nothing is known of those places' ratings or reviews")
    if osm.get("note"):
        return osm["note"]
    if not osm.get("count"):
        return f"OpenStreetMap shows no {singular(row['genre'])} inside the {noun} either"
    return f"OpenStreetMap shows {osm['count']} inside the {noun}, all of them places Qloo lists"


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


def _offer_counts(
    places: list[dict], kind: str, genre: str = "",
) -> tuple[Counter, dict[str, str], dict[str, int], set[str]]:
    """Each candidate item, counted by how many of the places carry it (a tag or a review topic), its name, the rank
    of the family it comes from for this kind of business (a restaurant's dishes before its drinks), and the items
    with too little evidence to be known for: one word that one place's reviews mention once or twice ('individual',
    'medicine' at a café), and no tag."""
    families = OFFER_FAMILIES.get(kind, OFFER_FAMILIES["food"])
    menu_rank = families.index("menu") if "menu" in families else len(families)
    doing_rank = families.index("activities") if "activities" in families else len(families)
    genre_words = set(_offer_key(genre).split()) - {"bar", "venue", "club", "place"}
    per_place: list[tuple[dict, dict[str, tuple[str, int]], dict[str, int]]] = []
    for place in places:
        found: dict[str, tuple[str, int]] = {}
        heard: dict[str, int] = {}  # review mentions of the items only reviews name at this place
        for tag in place.get("tags") or []:
            rank = next((i for i, f in enumerate(families) if (tag.get("type") or "").startswith(scoring.DESIGN_FAMILIES[f])), None)
            if rank is not None and tag.get("name"):
                found.setdefault(_offer_key(tag["name"]), (tag["name"], rank))
        tagged = set(found)
        groups = scoring.topic_groups([place])
        if kind in ("food", "bar"):
            for group in groups["menu"]:
                key = _offer_key(group["label"])
                found.setdefault(key, (group["label"][:1].upper() + group["label"][1:], menu_rank))
                if key not in tagged:
                    heard[key] = heard.get(key, 0) + int(group.get("mentions") or 1)
        if kind in ("bar", "venue"):
            for group in groups["experience"]:
                # 'Live music and DJs' says nothing new about a live music venue.
                if group["label"] in DOING_THEMES and not genre_words & set(_offer_key(group["label"]).split()):
                    found.setdefault(_offer_key(group["label"]), (group["label"], doing_rank))
        per_place.append((place, found, heard))
    # How many places use each word in their items: a dish word ('lobster') is shared, a proper name ('Otway') is not.
    used = Counter(word for _, found, _ in per_place for word in {w for key in found for w in key.split()})
    counts: Counter = Counter()
    names: dict[str, str] = {}
    ranks: dict[str, int] = {}
    mentions: Counter = Counter()
    from_tags: set[str] = set()
    for place, found, heard in per_place:
        own = {word for word in _offer_key(place.get("name") or "").split() if len(word) >= 4}
        for key, (name, rank) in found.items():
            # A dish named after its own place ('Otway burger' at Otway) belongs to that place, not to a new concept.
            if not key or any(word in own and used[word] <= 1 for word in key.split()):
                continue
            counts[key] += 1
            ranks[key] = min(rank, ranks.get(key, rank))
            if key in heard:
                mentions[key] += heard[key]
            else:
                from_tags.add(key)
            # The plainest wording wins: 'croissant' over 'great croissants'.
            if key not in names or len(name) < len(names[key]):
                names[key] = name[:1].upper() + name[1:]
    weak = {
        key for key, count in counts.items()
        if count == 1 and key not in from_tags and len(key.split()) == 1 and mentions[key] < 3
    }
    return counts, names, ranks, weak


def _offer_key(item: str) -> str:
    return scoring.item_key(item)


def offer_items(row: dict, constraints: Constraints | None = None, limit: int = 4) -> list[dict]:
    """What a concept should be known for, from the places people here love: items none of the places inside the walk
    is known for come first ('new_here'), then the rest by how many favorites carry them. Items the owner's rules
    forbid (alcohol, pork, meat, anything that needs a hood or a kitchen the unit lacks) are left out."""
    kind = scoring.genre_kind(row["genre"])
    loved, names, ranks, weak = _offer_counts(example_places(row), kind, row["genre"])
    nearby_keys = set(_offer_counts(competitor_places(row), kind, row["genre"])[0])
    items: list[dict] = []
    for key, count in sorted(loved.items(), key=lambda item: -item[1]):
        name = names[key]
        if key in weak or name.lower() in scoring.GENERIC_OFFERINGS or name.lower() in NOT_A_SIGNATURE or NOT_AN_OFFER.search(name):
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
    under = expected is not None and (relative <= UNDER or supply(row) == 0 and expected >= 1)
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
        return "People here travel for it"
    if s["over"]:
        return "Crowded"
    if s["stronger"]:
        return "Loved more here"
    if row["demand_rank"] <= 3:
        return "Top demand"
    return "Steady demand"


def gap_evidence(row: dict, area: str | int = 10, ages: str | None = None) -> list[str]:
    """The row in plain sentences: demand against the areas around, supply against density (with the places only
    OpenStreetMap shows inside the area), where people here travel. `area` is the survey's (Site.area), `ages` its age
    focus, which the demand and favorites lean toward."""
    genre = in_sentence(row["genre"])
    lines = [_demand_line(row, genre, ages)]
    supply_line = _supply_line(row, area)
    if supply_line:
        lines.append(supply_line)
    extra = osm_line(row, area)
    if extra:
        lines.append(extra)
    travel = _travel_line(row, area, ages)
    if travel:
        lines.append(travel)
    if row.get("evidence") == "thin":
        lines.append(f"Thin evidence: Qloo knows at most one {singular(row['genre'])} in the surrounding area.")
    elif row.get("evidence") == "atypical":
        lines.append(f"The {plural(row['genre'])} {people_here(ages)} love are mostly in hotels or malls, so the comparison "
                     f"is weak.")
    # A count that says the kind is missing or short, when OpenStreetMap could not confirm it.
    unchecked = unchecked_line(row) if _shape(row)["under"] else None
    if unchecked:
        lines.append(unchecked)
    return lines


AREA_WORDS = {3: "three", 4: "four", 5: "five", 6: "six"}


def areas_text(row: dict) -> str:
    """'six same-size areas', or fewer when some fell in open water; rows saved before the count say no number."""
    count = row.get("ref_areas")
    return f"{AREA_WORDS.get(count, count)} same-size areas" if count else "same-size areas"


def _demand_line(row: dict, genre: str, ages: str | None = None) -> str:
    rank, ref = row["demand_rank"], row.get("ref_rank")
    people = people_here(ages)
    if rank >= scoring.UNRANKED:
        return f"{capitalized(people)} do not rank {genre} among their top 50 place types."
    if rank == 1:
        text = f"{capitalized(genre)} is the place type {people} engage with most"
    else:
        text = f"{capitalized(people)} rank {genre} #{rank} among the place types they engage with"
    if ref is None:
        return text + "."
    ref_text = "outside the top 50" if ref >= scoring.UNRANKED else f"#{round(ref)}"
    if ref - rank >= 3:
        return f"{text}; {areas_text(row)} around rank it {ref_text}, so demand is stronger here."
    if rank - ref >= 3:
        return f"{text}; the areas around rank it higher ({ref_text}), so demand is weaker here."
    return f"{text}, about as high as the areas around ({ref_text})."


def _supply_line(row: dict, area: str | int) -> str | None:
    """Places of the kind inside the area against what a block this dense holds; with OpenStreetMap's extras, the count
    is both maps' and says how it splits."""
    nearby, total, capped = row["nearby_count"], supply(row), bool(row.get("nearby_capped"))
    here = f"{count_of(row['genre'], total, capped)} inside the {area_text(area)}"
    if total > nearby:
        qloo = f"{nearby}{'+' if capped else ''} on Qloo" if nearby else "none on Qloo"
        here += f" ({qloo}, {total - nearby} {'more ' if nearby else ''}on OpenStreetMap)"
    expected = row.get("expected_nearby")
    if expected is None:
        return f"{here}."
    typical = f"at least {number(expected)}" if row.get("around_capped") else f"about {number(expected)}"
    s = _shape(row)
    if total == 0:
        return f"{here}, where a block this dense usually has {typical}."
    if s["under"]:
        return f"Only {here}, where a block this dense usually has {typical}."
    if s["over"]:
        return f"{here}, more than the {typical} a block this dense usually has."
    return f"{here}, about what a block this dense holds ({typical})."


def _travel_line(row: dict, area: str | int = 10, ages: str | None = None) -> str | None:
    """Only places people here love more than the rest of the city does say where they travel; the city's famous places
    say nothing. The distance is the median trip to the favorites outside the area (median_far_km); rows saved before
    it existed say no distance rather than one diluted by the favorites already close by."""
    total, far, km = row["favorites_total"], row["favorites_far"], row.get("median_far_km")
    if row.get("favorites_kind") != "local" or total < 3:
        return None
    _, cards = storefront_favorites(row)
    outside = [c["name"] for c in cards if c.get("name") and not c.get("within_walk")][:3]
    inside = [c["name"] for c in cards if c.get("name") and c.get("within_walk")][:2]
    loved = f"{plural(row['genre'])} {people_here(ages)} love more than the rest of the city does"
    noun = area_noun(area)
    median = f" (median {km} km)" if km else ""
    if far == total:
        away = f", a median {km} km away" if km else ""
        return f"All {total} {loved} are outside the {noun}{away}: {scoring.natural_list(outside)}."
    if far / total >= TRAVEL:
        return f"{far} of the {total} {loved} are outside the {noun}{median}: {scoring.natural_list(outside)}."
    if far / total <= 0.4 and inside:
        return (f"Most of the {loved} are already inside the {noun} ({total - far} of {total}), such as "
                f"{scoring.natural_list(inside)}.")
    return f"{far} of the {total} {loved} are outside the {noun}{median}."


def love_evidence(row: dict, ages: str | None = None) -> tuple[float, str] | None:
    """How clearly people here love a category, with the evidence in words: they travel to its favorites outside the
    area (3), rank it higher than the areas around do (2.5), or rank it among their top five place types (2). None
    when the evidence is thin, atypical or weaker than that."""
    if row.get("evidence") != "ok":
        return None
    s = _shape(row)
    rank, ref = row["demand_rank"], row.get("ref_rank")
    people = people_here(ages)
    if s["travel"]:
        km = row.get("median_far_km")
        names = [c["name"] for c in storefront_favorites(row)[1] if c.get("name") and not c.get("within_walk")][:2]
        trip = f" a median {km} km" if km else ""
        like = f", such as {scoring.natural_list(names)}" if names else ""
        return 3.0, f"{people} travel{trip} to the {plural(row['genre'])} they love most{like}"
    if s["stronger"] and rank <= 10 and ref is not None:
        return 2.5, (f"{people} rank {in_sentence(row['genre'])} #{rank} among place types, higher than the areas "
                     f"around (#{round(ref)})")
    if rank <= 5:
        return 2.0, f"{people} rank {in_sentence(row['genre'])} #{rank} among the place types they engage with"
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


def competition(row: dict, area: str | int, constraints: Constraints | None = None, ages: str | None = None) -> str:
    """Who the concept competes with inside the area, what their reviews hold against them and how to stand apart."""
    cards = [c for c in row.get("competitors") or [] if c.get("name")]
    # The best-rated rival among the places that are this business in earnest; any tagged place when none is.
    earnest = {p.get("name") for p in competitor_places(row)}
    rivals = [c for c in cards if c["name"] in earnest] or cards
    parts = []
    total = supply(row)
    label, noun = area_text(area), area_noun(area)
    if not total:
        _, favorites = storefront_favorites(row)
        nearest = min((f for f in favorites if f.get("distance_m")), key=lambda f: f["distance_m"], default=None)
        parts.append(f"{count_of(row['genre'], 0)} competes inside the {label}" + (
            f"; the nearest one {people_here(ages)} love is {nearest['name']}, {nearest['distance_m'] / 1000:.1f} km away."
            if nearest else "."
        ))
    elif not row["nearby_count"]:
        # Only OpenStreetMap shows the competition: its names, and nothing about ratings or reviews.
        parts.append(f"{count_of(row['genre'], 0)} Qloo lists competes inside the {label}, but OpenStreetMap "
                     f"shows {osm_count_text(row)} there: {osm_names(row)}.")
    elif rivals:
        best = max(rivals, key=lambda c: (c.get("rating") or 0))
        detail = f"{best['rating']}★" if best.get("rating") else ""
        known = scoring.natural_list((best.get("known_for") or [])[:2])
        also = f", {len(osm_extra(row))} of them only on OpenStreetMap" if osm_extra(row) else ""
        if osm_extra(row):
            who = "the best rated on Qloo is" if row["nearby_count"] > 1 else "the one on Qloo is"
        else:
            who = "the best rated is" if total > 1 else "it is"
        lead = f"{count_of(row['genre'], total, row.get('nearby_capped'))} inside the {noun}{also}; {who} {best['name']}"
        parts.append(lead + (f" ({detail})" if detail else "") + (f", known for {known}." if known else "."))
        themes = Counter(theme for c in cards for theme in c.get("complaints") or [])
        moves = [(theme, COMPLAINT_MOVES.get(theme[:1].upper() + theme[1:])) for theme, _ in themes.most_common(2)]
        moves = [(theme, move) for theme, move in moves if move]
        if moves:
            said = scoring.natural_list([theme for theme, _ in moves])
            parts.append(f"Their reviews complain about {said}: {'; '.join(move for _, move in moves)}.")
    items = [i["item"].lower() for i in offer_items(row, constraints) if i["new_here"]][:3]
    if items:
        # Only Qloo's places carry reviews, so the claim is about the ones it lists.
        listed = " that Qloo lists" if osm_extra(row) else ""
        parts.append(f"Stand apart with what the {plural(row['genre'])} {people_here(ages)} love are known for and none "
                     f"inside the {noun}{listed} is: {scoring.natural_list(items)}.")
    return " ".join(parts)


def risk(row: dict, area: str | int, ages: str | None = None) -> str:
    """The biggest risk the evidence shows, stated with its numbers."""
    genre = in_sentence(row["genre"])
    s = _shape(row)
    nearby = supply(row)
    people = people_here(ages)
    if row.get("evidence") == "thin":
        return f"Thin evidence: Qloo knows at most one {singular(row['genre'])} in the surrounding area, so treat this as a hypothesis."
    if row.get("evidence") == "atypical":
        return (f"The {plural(row['genre'])} {people} love are mostly in hotels or malls, so a small storefront may not "
                f"draw the same crowd.")
    if s["over"]:
        return (f"{count_of(row['genre'], nearby, row.get('nearby_capped'))} are already inside the {area_noun(area)}, more "
                f"than the block's density predicts: you would take share, not fill a gap.")
    if s["weaker"]:
        return (f"{capitalized(people)} rank {genre} lower than the areas around do (#{row['demand_rank']} against "
                f"#{round(row['ref_rank'])}).")
    if nearby >= 8:
        return f"{count_of(row['genre'], nearby, row.get('nearby_capped'))} already compete inside the {area_text(area)}."
    if row.get("favorites_kind") != "local":
        return (f"No sign that {people} travel for {plural(row['genre'])}: their favorites are the city's famous ones, so "
                f"the case rests on the ranking and the supply count.")
    return "Qloo measures taste, not foot traffic: count passers-by at the door on a weekday and a weekend before signing."


# ---------- What the agent sees ----------

def evidence_brief(run: RunState) -> dict:
    """Compact evidence pack handed to the LLM. The area is the survey's (a walk, a drive or a road distance): its label
    says which, and every field says 'area' rather than assume a walk."""
    s = run.summary
    walk = run.catchment
    site = run.site
    area, ages = site.area, site.ages
    brief = {
        "site": {"label": site.label, "focus": site.focus, "owner_notes": site.notes or None},
        "catchment": {
            "area": area,
            "shape": walk.source if walk else "circle",
            "area_km2": round(walk.area_m2 / 1e6, 2) if walk else None,
        },
        "block_inside_the_area": {
            "places_scanned": s.get("place_count"),
            "most_common_genres": s.get("top_genres", [])[:8],
            "average_rating": s.get("avg_rating"),
            "what_reviews_mention": {
                "menu": [mention_text(g) for g in s.get("menu", [])[:8]],
                "experience": [mention_text(g) for g in s.get("experience", [])[:8]],
                "complaints": [mention_text(g) for g in s.get("complaints", [])[:6]],
            },
        },
        "gap_table": [gap_summary(g, area, ages) for g in run.gaps],
        "taste_cues": run.cues,
        "brands_this_area_over_indexes_on": [b["name"] for b in run.taste.get("distinctive_brands", [])],
        "artists_this_area_over_indexes_on": [a["name"] for a in run.taste.get("distinctive_artists", [])],
        "films_and_shows_this_area_over_indexes_on": [
            f"{c['name']} ({c['year']})" if c.get("year") else c["name"]
            for c in run.taste.get("distinctive_movies", [])[:5] + run.taste.get("distinctive_tv", [])[:5]
        ],
        "podcasts_this_area_over_indexes_on": [p["name"] for p in run.taste.get("distinctive_podcasts", [])[:5]],
    }
    focus = ages_label(ages)
    if focus:
        # Rankings, favorites and taste all lean toward the owner's age group (Qloo's demographic signal).
        brief["site"]["age_focus"] = focus
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
            "evidence": gap_summary(row, area, ages) if row else None,
        }
    return brief


def mention_text(group: dict) -> str:
    """A review topic group in words: 'Long waits and lines (6,071 mentions at 75 places)'."""
    mentions, places = group["mentions"], group["places"]
    return f"{group['label']} ({mentions:,} mention{'' if mentions == 1 else 's'} at {places} place{'' if places == 1 else 's'})"


def gap_summary(g: dict, area: str | int = 10, ages: str | None = None) -> dict:
    """One gap row as the agent sees it: comparisons are stated in words, so they cannot be misread."""
    people = people_here(ages)
    if g["favorites_kind"] == "local" and g["favorites_total"]:
        km = g.get("median_far_km")
        travel = (
            f"{g['favorites_far']} of the {g['favorites_total']} places {people} love more than the rest of the city "
            f"does are outside the {area_noun(area)}" + (f"; those are a median {km} km away" if km else "")
        )
    else:
        travel = f"no evidence: the favorites of {people} of this type are just the city's famous places"
    summary = {
        "genre": g["genre"],
        "reading": g.get("reading") or gap_reading(g),
        "people_here_rank_it": g["demand_rank"] if g["demand_rank"] < scoring.UNRANKED else "outside their top 50",
        "median_rank_in_6_same_size_areas_around": g["ref_rank"],
        "demand_compared_with_areas_around": demand_comparison(g),
        "places_inside_the_area": f"{supply(g)}{'+' if g['nearby_capped'] else ''}",
        "typical_for_a_block_this_dense": (
            f"at least {g['expected_nearby']}" if g.get("around_capped") and g["expected_nearby"] is not None else g["expected_nearby"]
        ),
        "relative_supply": g["relative_supply"],
        "do_people_here_travel_for_it": travel,
        "evidence": g["evidence"],
        "gap_score": g["gap_score"],
    }
    cross = osm_check_text(g, area)
    if cross:
        summary["openstreetmap_cross_check"] = cross
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
    area, ages = run.site.area, run.site.ages
    payload = {
        "genre": row["genre"],
        "competitors_inside_the_area": [
            {k: c.get(k) for k in ("name", "rating", "known_for", "complaints", "distance_m")}
            for c in row["competitors"][:6]
        ],
        favorites_key: [
            {"name": f["name"], "km_away": round((f.get("distance_m") or 0) / 1000, 1),
             "known_for": f.get("known_for"), "inside_the_area": f.get("within_walk", False)}
            for f in cards[:8]
        ],
        "do_people_here_travel_for_it": gap_summary(row, area, ages)["do_people_here_travel_for_it"],
        "menu_gap": [i["item"] for i in offer if i["new_here"]],
        "also_offered_inside_the_area": [i["item"] for i in offer if not i["new_here"]],
        # Only what the places offer: their decor, setting and ambience tags read as filler ('lively', 'cozy') and
        # said the same of every block.
        "what_these_places_offer": {
            family: names for family, names in scoring.design_dna(entities).items()
            if family in OFFER_TAG_FAMILIES and names
        },
    }
    if osm_extra(row):
        payload["competitors_only_openstreetmap_shows_inside_the_area"] = [
            {"name": p["name"], "distance_m": p.get("distance_m")} for p in osm_extra(row)[:8]
        ]
    return payload


def short_label(label: str) -> str:
    """'Upper East Side, Manhattan' -> 'Upper East Side'; falls back to a neutral word for raw pins."""
    first = (label or "").split(",")[0].strip()
    if not first or first.lower() in {"selected site", "dropped pin"} or any(ch.isdigit() for ch in first[:3]):
        return "Corner"
    return first[:32]
