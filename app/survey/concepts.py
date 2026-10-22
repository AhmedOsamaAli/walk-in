"""Business concepts for a site: the agent with live Qloo tools, the evidence rules behind it, and the
grounding that keeps both to what the evidence says.

The owner's rules are hard rules for both: a budget means the lowest price level, a unit without a hood means nothing
that needs one, a size means every concept fits it, and every concept says how it meets each rule (owner_rules). The
agent is told the rules, and its answer is checked after it answers: what breaks a rule is repaired once (items taken
out and replaced from the evidence, the price set, a real name given) and a concept that still breaks one is dropped,
with the reason in the payload's notes. A wildcard may follow the ranked concepts: two things people here love, combined
into a business no place inside the walk is.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from itertools import combinations

from .. import engine, scoring, space
from ..answers import AnswerCache, fingerprint
from ..llm import LLM, LLMUnavailable
from ..qloo import QlooClient, QlooError
from .constraints import UPSCALE
from .evidence import (
    annotate,
    block_price,
    competition,
    count_of,
    crowd_of,
    dollars,
    evidence_brief,
    fits,
    gap_evidence,
    gap_for,
    gap_summary,
    in_running_text,
    in_sentence,
    inspect_payload,
    love_evidence,
    offer_items,
    plural,
    price_anchors,
    price_evidence,
    public_gap,
    risk,
    short_label,
    singular,
    storefront_favorites,
)
from .experience import fans_of
from .intents import requested_row
from .models import Emit, RunState, Site

log = logging.getLogger("walkin")


def ground_names(names: list[str] | None, allowed: set[str]) -> list[str]:
    allowed_lower = {a.lower(): a for a in allowed}
    return [allowed_lower[n.lower()] for n in names or [] if isinstance(n, str) and n.lower() in allowed_lower]


def clean_concepts(run: RunState, concepts: list[dict], notes: list[str] | None = None) -> list[dict]:
    """Keep only concepts whose genre exists in the evidence and that the unit and the owner's notes allow, one per kind
    of business, citing real places under original names, priced and stocked as the evidence and the notes say.

    The model contributes the creative parts (name, positioning, signature items). Every factual line (why here, who
    for, the competition, the price, the risk) is rebuilt from the measured evidence, so a misread number never reaches
    the owner. What breaks the owner's rules is repaired once; a concept that still breaks one is dropped. Repairs and
    drops are added to `notes`, in plain words.
    """
    notes = notes if notes is not None else []
    cleaned: list[dict] = []
    known_places = place_names(run)
    minutes = run.site.minutes
    for concept in concepts or []:
        if not isinstance(concept, dict):
            continue
        row = gap_for(run, str(concept.get("genre") or ""))
        if not row or scoring.genre_key(row["genre"]) in TOO_BROAD:
            label = " ".join(str(concept.get("name") or "A concept").split())[:60]
            why = (f"{concept.get('genre')!r} is not a category the survey measured" if not row
                   else f"{row['genre']} is too broad to open as one business")
            notes.append(f"Dropped {label}: {why}.")
            continue
        proposed = " ".join(str(concept.get("name") or "").split())[:60]
        label = f"{proposed or 'A concept'} ({scoring.genre_title(row['genre'])})"
        if not fits(row):
            notes.append(f"Dropped {label}: {misfit(row)}.")
            continue
        if any(same_business(c["genre"], row["genre"]) for c in cleaned):
            continue
        favorites = {card["name"] for card in storefront_favorites(row)[1] if card.get("name")}
        concept["genre"] = row["genre"]
        concept["genre_id"] = row["genre_id"]
        concept["gap_score"] = row["gap_score"]
        concept["inspired_by"] = ground_names(concept.get("inspired_by"), favorites)[:4] or [
            card["name"] for card in storefront_favorites(row)[1][:3] if card.get("name")
        ]
        concept["name"] = concept_name(run, row, proposed, {c["name"] for c in cleaned}, known_places, notes)
        concept["one_liner"] = ruled_line(run, row, str(concept.get("one_liner") or ""), concept["name"], notes)
        level = concept.get("price_level")
        concept["price_level"], concept["price_basis"] = grounded_price(run, row, level)
        if run.constraints.budget and isinstance(level, int) and level > 1:
            notes.append(f"{concept['name']}: priced $ for your budget, not {dollars(min(level, 4))}.")
        concept["price_anchors"] = price_anchors(row, concept["price_level"])
        signature, removed = ruled_signature(concept.get("signature"), row, run)
        if removed:
            notes.append(f"{concept['name']}: took out {removed_text(removed)}.")
        if removed and not signature:
            notes.append(f"Dropped {concept['name']} ({scoring.genre_title(row['genre'])}): nothing on its menu works "
                         f"under your rules, and the places people here love offer nothing that does.")
            continue
        concept["signature"] = signature
        concept["for_whom"] = for_whom(row, minutes)
        concept["why_here"] = gap_evidence(row, minutes)
        concept["beat_competitors"] = competition(row, minutes, run.constraints)
        concept["risk"] = concept_risk(run, row, concept["price_level"])
        concept["evidence"] = concept["why_here"]
        concept["owner_rules"] = owner_rule_lines(run, row, concept)
        problems = rule_problems(run, row, concept)
        if problems:
            notes.append(f"Dropped {concept['name']} ({scoring.genre_title(row['genre'])}): {'; '.join(problems)}.")
            continue
        cleaned.append(concept)
    return cleaned[:3]


def misfit(row: dict) -> str:
    """Why a category cannot be proposed here, after 'Dropped X:'."""
    if row.get("ruled_out"):
        return f"your notes rule it out (it {row['ruled_out']})"
    return f"the unit cannot host it (it {(row.get('fit') or {}).get('reason')})"


def removed_text(removed: list[tuple[str, str]]) -> str:
    """'Crispy potatoes (it needs a deep fryer under an extraction hood) and Truffle pizza (it needs a pizza oven …)'."""
    return scoring.natural_list([f"{item} (it {why})" for item, why in removed])


def ruled_line(run: RunState, row: dict, text: str, name: str, notes: list[str]) -> str:
    """The model's positioning, grounded (grounded_line), unless it describes something the owner's rules forbid (fried
    chicken in a unit without a hood, 'upscale' on a budget); then the evidence's own line."""
    line = grounded_line(text, row, run.site)
    clash = run.constraints.item_clash(line)
    if clash:
        notes.append(f"{name}: its one-liner mentioned '{clash[0]}', which {clash[1]}; the evidence's own line "
                     f"replaces it.")
    elif run.constraints.budget and UPSCALE.search(line):
        notes.append(f"{name}: its one-liner called it upscale, and your notes ask for budget prices; the evidence's own "
                     f"line replaces it.")
    else:
        return line
    return one_liner(row, run.site.minutes)


# A count of seats or guests, or a floor area: facts about a unit the model has never seen.
UNIT_CLAIM = re.compile(
    r"\b(\d[\d,.]*)\s*-?\s*(seats?|seater|covers?|guests?|people|m2|m²|sq\.?\s?ft|square\s(?:feet|foot|met(?:er|re)s?))\b",
    re.IGNORECASE,
)
# Competitors are measured inside the walk, never placed next to the unit.
NEXT_DOOR = re.compile(r"\b(?:next door|across the (?:street|road|block))\b", re.IGNORECASE)


def grounded_line(text: str, row: dict, site: Site) -> str:
    """The model's positioning, unless it states a capacity or floor area the unit does not have (then the evidence's
    own line); competitors it places next door are only known to be nearby."""
    text = " ".join(text.split())
    if not text or any(not unit_supports(match, row, site) for match in UNIT_CLAIM.finditer(text)):
        return one_liner(row, site.minutes)
    return NEXT_DOOR.sub("nearby", text)


def unit_supports(claim: re.Match, row: dict, site: Site) -> bool:
    """Whether a stated floor area is the owner's own, or a stated capacity is within what the unit holds."""
    try:
        number = float(claim.group(1).replace(",", ""))
    except ValueError:
        return False
    unit = claim.group(2).lower()
    if unit.startswith(("m2", "m²", "sq", "square")):
        if not site.size_m2:
            return False
        metric = unit.startswith(("m2", "m²")) or "met" in unit
        stated = number if metric else number * space.SQ_FT_M2
        return abs(stated - site.size_m2) <= 0.1 * site.size_m2
    capacity = (row.get("fit") or {}).get("capacity")
    return bool(capacity) and capacity["low"] * 0.8 <= number <= capacity["high"]


def concept_risk(run: RunState, row: dict, level: int | None) -> str:
    """The evidence's biggest risk, or the price gap when the owner's range sets the concept below what people here
    pay."""
    price = row.get("price") or price_evidence(row, run.constraints, block_price(run))
    loved = price.get("loved")
    if loved and level and loved - level >= 1:
        return (f"The {plural(row['genre'])} people here love are {'$' * loved}; at {'$' * level} the concept has to win "
                f"on value and speed, not on the same experience.")
    return risk(row, run.site.minutes)


# Below this gap score a category is not a recommendation when stronger ones fit; the owner's own request always is.
WEAK_GAP = 30


def strong_enough(run: RunState, concepts: list[dict], notes: list[str] | None = None) -> list[dict]:
    """Replaces concepts built on weak gaps with the strongest fitting gaps the evidence rules can design, so the agent's
    hunches never outrank what the measurements say; the owner's requested business keeps its place. When no fitting
    gap is strong, nothing is dropped: the survey says so instead (caution). Replacements are added to `notes`."""
    if not any(row["gap_score"] >= WEAK_GAP for row in concept_rows(run)):
        return concepts
    wanted = requested_row(run)
    keep = [c for c in concepts if c["gap_score"] >= WEAK_GAP or wanted and c["genre_id"] == wanted["genre_id"]]
    dropped = [c for c in concepts if c not in keep]
    if dropped:
        log.info("Dropped concepts on weak gaps: %s", ", ".join(c["genre"] for c in dropped))
        if notes is not None:
            notes += [f"Replaced {c['name']} ({scoring.genre_title(c['genre'])}): its gap scores {c['gap_score']} of 100 "
                      f"while stronger gaps fit." for c in dropped]
    for row in concept_rows(run):
        if len(keep) >= 3:
            break
        if row["gap_score"] >= WEAK_GAP and not any(same_business(c["genre"], row["genre"]) for c in keep):
            keep.append(rule_concept(run, row, {c["name"] for c in keep}))
    return keep


def caution(run: RunState, concepts: list[dict]) -> str | None:
    """A plain warning when even the best concept rests on a weak gap. The wildcard is never ranked, so it never counts."""
    scores = [c["gap_score"] for c in concepts if not c.get("wildcard") and c.get("gap_score") is not None]
    if not scores or max(scores) >= WEAK_GAP:
        return None
    return (f"No strong gap here: the best category scores {max(scores)} of 100, so demand and supply are close to "
            f"typical. Treat these as options to test, not as gaps waiting to be filled.")


def grounded_price(run: RunState, row: dict, proposed: object) -> tuple[int | None, str]:
    """The agent's price level when the evidence supports it (within one level of what the places people here love
    charge), otherwise the evidence's own; the owner's price range always applies, and a budget is always $."""
    evidence = row.get("price") or price_evidence(row, run.constraints, block_price(run))
    try:
        level = max(1, min(4, int(proposed))) if proposed is not None else None
    except (TypeError, ValueError):
        level = None
    supported = evidence["evidence_level"]
    if level is None or supported is not None and abs(level - supported) > 1:
        level = supported
    level = run.constraints.price_level(level) if level else evidence["level"]
    return level, evidence["basis"]


# Signature items are what people come for; the room, the seats and the mood belong to the design sheet.
NOT_A_SIGNATURE = re.compile(
    r"\b(seating|seats|outdoor|patio|terrace|veranda|ambiance|ambience|atmosphere|decor|interior|setting|vibe|"
    r"music selection|comfortable|inviting)\b",
    re.IGNORECASE,
)


def signature_of(items: object, row: dict, run: RunState) -> list[str]:
    """The agent's signature items, short, specific and allowed by the owner's notes; else the evidence's own."""
    return ruled_signature(items, row, run)[0]


def ruled_signature(items: object, row: dict, run: RunState) -> tuple[list[str], list[tuple[str, str]]]:
    """The agent's signature items (short and specific) that the owner's rules allow, and the ones taken out with why.

    Items taken out are replaced by what the places people here love are known for, within the rules, so a concept
    keeps as many items as it was given; with none given, the evidence's own items. An empty list after items were
    taken out means the concept lost its signature."""
    return ruled_items(items, [i["item"] for i in offer_items(row, run.constraints, limit=6)], run)


def ruled_items(
    items: object, evidence: list[str], run: RunState, fallback: int = 3,
) -> tuple[list[str], list[tuple[str, str]]]:
    """ruled_signature with the evidence's items given: (kept, [(item taken out, why)]); with nothing kept, the first
    `fallback` evidence items."""
    candidates = [
        item.strip().rstrip(".") for item in (items if isinstance(items, list) else [])
        if isinstance(item, str) and item.strip() and len(item.split()) <= 8 and not NOT_A_SIGNATURE.search(item)
    ]
    removed = [(item, why) for item in candidates if (why := run.constraints.item_problem(item))]
    kept = [item for item in candidates if not run.constraints.item_problem(item)][:4]
    if not kept:
        return evidence[:fallback], removed
    wanted = min(4, len(candidates))
    for item in evidence:
        if len(kept) >= wanted or not removed:
            break
        if not any(same_item(item, k) for k in kept):
            kept.append(item)
    return kept, removed


def same_item(first: str, second: str) -> bool:
    """Whether two items are one: 'Wine flights' is already in 'Wine flight tasting'."""
    a, b = set(scoring.item_key(first).split()), set(scoring.item_key(second).split())
    return bool(a and b) and (a <= b or b <= a)


# Genres that are one business under different names; concepts never offer two of them.
NEAR_DUPLICATES = (
    {"brunch", "breakfast", "breakfastandbrunch", "brunchspot"},
    {"cafe", "coffeeshop", "espressobar", "cafeteria", "coffeehouse", "coffeeroaster", "teahouse", "tearoom"},
    {"fastfood", "takeout", "snackbar", "quickbite", "hamburger", "burger", "burgerjoint"},
    {"icecreamshop", "dessertshop", "gelatoshop", "frozenyogurtshop", "dessert"},
    {"nightclub", "danceclub", "club"},
    {"pub", "bar", "beerbar", "tavern", "irishpub"},
    {"cocktailbar", "lounge", "loungebar", "speakeasy", "hotelbar"},
)


def same_business(first: str, second: str) -> bool:
    a, b = scoring.genre_key(first), scoring.genre_key(second)
    return a == b or any(a in family and b in family for family in NEAR_DUPLICATES)


# Category words that are names of real places somewhere ("Diner", "Bakery") but are free for anyone to use.
COMMON_NAME_WORDS = {
    "bar", "cafe", "café", "coffee", "diner", "bakery", "deli", "grill", "kitchen", "tavern", "pub", "market",
    "wine", "tea", "bistro", "brasserie", "lounge", "club", "studio", "shop", "store", "gallery", "pizza",
    "pizzeria", "trattoria", "cantina", "taqueria", "restaurant", "eatery", "canteen", "corner", "local",
}
# Words that say what kind of business a place is rather than which one: 'Golden Hour Bakery', 'Cafe Golden Hour' and
# 'The Golden Hour Co.' all go by the name 'Golden Hour'.
CATEGORY_NAME_WORDS = (COMMON_NAME_WORDS - {"corner", "local"}) | {
    "bakehouse", "bakeshop", "patisserie", "boulangerie", "espresso", "roasters", "roastery", "coffeehouse", "teahouse",
    "caffe", "brewery", "brewing", "taproom", "winery", "osteria", "ristorante", "boutique", "salon", "spa", "gym", "co",
    "company", "inc", "llc", "ltd",
}


def place_names(run: RunState) -> set[str]:
    names = {p.get("name") for p in run.block}
    for row in run.gaps + run.explored:
        names |= {c.get("name") for c in row.get("competitors", [])}
        names |= {f.get("name") for f in row.get("favorites", [])}
        names |= set(row.get("city_favorites", []))
    return {name for name in names if isinstance(name, str) and name.strip()}


def _name_words(text: str) -> list[str]:
    return [word for word in scoring.topic_text(text).split() if word != "the"]


def name_core(name: str) -> list[str]:
    """A name's own words, without the ones that only say what kind of business it is: 'Cafe Golden Hour' -> golden,
    hour."""
    return [word for word in _name_words(name) if word not in CATEGORY_NAME_WORDS and word != "and"]


def taken_name(name: str, places: set[str]) -> str | None:
    """The existing place a concept name reuses, if any: 'Otis & Main' reuses the restaurant 'Otis', and 'Golden Hour'
    a 'Golden Hour Bakery' or a 'Cafe Golden Hour' (the same name give or take the words that only say what kind of
    business it is). A shorter name is another name ('Golden'), and one of category words alone ('The Bakery') anyone's."""
    text = f" {' '.join(_name_words(name))} "
    core = name_core(name)
    own = len("".join(core)) >= 3 and not set(core) <= COMMON_NAME_WORDS | FILLER_NAME_WORDS
    for place in sorted(places):
        words = _name_words(place)
        if not words or len("".join(words)) < 3 or (len(words) == 1 and words[0] in COMMON_NAME_WORDS):
            continue
        if f" {' '.join(words)} " in text or (own and name_core(place) == core):
            return place
    return None


# Words that say nothing a sign would: a name made only of them, the category and the neighborhood is a placeholder.
FILLER_NAME_WORDS = {"and", "co", "company", "place", "spot", "new", "neighborhood", "neighbourhood", "concept", "joint",
                     "house", "room", "s"}


def placeholder_name(name: str, genre: str, label: str) -> bool:
    """Whether a name is only the category and the place ('Breakfast, Zamalek', 'Zamalek Cafe', 'The Wine Bar'): every
    word is the category's, the place's or a word any business uses, or it ends with ', <the place>'."""
    if "," in name and name.rsplit(",", 1)[1].strip().lower() in {short_label(label).lower(), label.strip().lower()}:
        return True
    generic = set(_name_words(genre)) | set(_name_words(label)) | COMMON_NAME_WORDS | FILLER_NAME_WORDS
    return all(word in generic or word.rstrip("s") in generic for word in _name_words(name))


# Words for the names the evidence rules give: warm, plain, and free of any dish, drink or place a rule could forbid.
NAME_WORDS = (
    "Linden", "Marigold", "Saffron", "Copper", "Lantern", "Daybreak", "Morrow", "Willow", "Orchard", "Meadow", "Cedar",
    "Indigo", "Sparrow", "Wren", "Clover", "Hazel", "Sesame", "Tamarind", "Fig Tree", "Olive Branch", "Blue Door",
    "Green Door", "Open Window", "Half Moon", "North Star", "Paper Kite", "Bluebell", "Poppy",
)
# What the sign calls the place, by its category; the first that matches.
NAME_NOUNS = (
    (re.compile(r"\b(coffee|espresso)", re.IGNORECASE), "Coffee", "Coffee"),
    (re.compile(r"\btea\b|\btea ?(house|room)\b", re.IGNORECASE), "Tea House", "Tea"),
    (re.compile(r"\bcaf[eé]\b", re.IGNORECASE), "Café", "Café"),
    (re.compile(r"\b(breakfast|brunch)", re.IGNORECASE), "Table", "Breakfast"),
    (re.compile(r"\b(bakery|patisserie|pastry|bagel)", re.IGNORECASE), "Bakehouse", "Bakery"),
    (re.compile(r"\b(ice cream|gelato|frozen yogurt)", re.IGNORECASE), "Parlour", "Ice Cream"),
    (re.compile(r"\b(dessert|chocolate|candy|sweets?)\b", re.IGNORECASE), "Parlour", "Sweets"),
    (re.compile(r"\b(juice|smoothie|acai|açaí)", re.IGNORECASE), "Juice Bar", "Juice"),
    (re.compile(r"\bwine", re.IGNORECASE), "Wine Room", "Wine"),
    (re.compile(r"\b(cocktail|speakeasy)", re.IGNORECASE), "Bar", "Cocktails"),
    (re.compile(r"\b(beer|brew\w*|taproom|tap room|pub|gastropub)\b", re.IGNORECASE), "Taproom", "Beer"),
    (re.compile(r"\b(lounge|hookah|shisha)", re.IGNORECASE), "Lounge", "Lounge"),
    (re.compile(r"\b(music|concert|jazz)", re.IGNORECASE), "Hall", "Music"),
    (re.compile(r"\b(comedy|karaoke|club|venue)", re.IGNORECASE), "Hall", "Stage"),
    (re.compile(r"\b(\w*burger|fast food|sandwich|deli|shawarma|falafel|taco|chicken|kebab)", re.IGNORECASE), "Counter",
     "Street Food"),
    (re.compile(r"\bbook", re.IGNORECASE), "Books", "Books"),
    (re.compile(r"\b(record|vinyl)", re.IGNORECASE), "Records", "Records"),
    (re.compile(r"\b(flower|florist)", re.IGNORECASE), "Flowers", "Flowers"),
    (re.compile(r"\b(spa|massage|sauna)\b", re.IGNORECASE), "Spa", "Spa"),
    (re.compile(r"\b(gym|fitness|yoga|pilates|dance|climbing|boxing|salon|barber|nail|beauty|hair)", re.IGNORECASE),
     "Studio", "Studio"),
)
KIND_NOUNS = {"food": "Kitchen", "bar": "Bar", "venue": "Hall", "retail": "Shop", "wellness": "Studio"}


def name_noun(genre: str, side: bool = False) -> str:
    """What a sign calls a place of this category ('Coffee', 'Table'); `side` gives the word for the second half of a
    combined name ('… Coffee & Music')."""
    for pattern, noun, word in NAME_NOUNS:
        if pattern.search(genre):
            return word if side else noun
    return scoring.genre_title(genre) if side else KIND_NOUNS.get(scoring.genre_kind(genre), "Kitchen")


def invent_name(run: RunState, genre: str, taken: set[str], second: str | None = None) -> str:
    """A real business name for a concept the model did not name well ('Linden Coffee', 'Daybreak Table'), chosen the
    same way for the same site and category, never one an existing place or another concept here has."""
    noun = name_noun(genre) if not second else f"{name_noun(genre, side=True)} & {name_noun(second, side=True)}"
    places = place_names(run)
    used = {word for name in taken for word in _name_words(name)}
    seed = zlib.crc32(f"{run.site.label}|{genre}|{second or ''}".encode())
    names = [f"{NAME_WORDS[(seed + i) % len(NAME_WORDS)]} {noun}" for i in range(len(NAME_WORDS))]
    for name in names:
        first = _name_words(name.removesuffix(noun))
        if set(first) & used or taken_name(name, places) or run.constraints.item_problem(name):
            continue
        return name
    return names[0]


def concept_name(run: RunState, row: dict, proposed: str, taken: set[str], places: set[str], notes: list[str]) -> str:
    """The model's name, unless it is empty, a placeholder, an existing place's or another concept's, or names something
    the owner's rules forbid; then one the rules invent."""
    reused = taken_name(proposed, places) if proposed else None
    clash = run.constraints.item_clash(proposed) if proposed else None
    why = (
        "it had none" if not proposed
        else f"it reused the existing place {reused}" if reused
        else "it was only the category and the place" if placeholder_name(proposed, row["genre"], run.site.label)
        else "another concept has it" if proposed.lower() in {name.lower() for name in taken}
        else f"'{clash[0]}' {clash[1]}" if clash
        else None
    )
    if not why:
        return proposed
    name = invent_name(run, row["genre"], taken)
    if proposed:
        log.info("Concept name %r renamed %r: %s", proposed, name, why)
        notes.append(f"{proposed} was renamed {name}: {why}.")
    return name


def one_liner(row: dict, minutes: int) -> str:
    """The case for the concept in one sentence, led by its strongest evidence. Trips are measured to the favorites
    outside the walk (median_far_km); without that measure, no distance is given."""
    title = scoring.genre_title(row["genre"])
    places = plural(row["genre"])
    nearby, expected, km = row["nearby_count"], row.get("expected_nearby"), row.get("median_far_km")
    leakage = row.get("leakage")
    travels = row.get("favorites_kind") == "local" and leakage is not None and leakage >= 0.65 and row["favorites_far"] >= 3
    under = expected is not None and (row.get("relative_supply", 1) <= 0.75 or nearby == 0 and expected >= 1)
    if travels and nearby == 0:
        away = f", their favorites a median {km} km away" if km else ""
        return f"The {places} people here now cross town for: none inside the {minutes}-minute walk{away}."
    if travels and under:
        trip = f" {km} km" if km else ""
        return (f"{title} close to home: {nearby} inside the walk where a block this dense has about {expected:g}, and "
                f"people here travel{trip} for their favorites.")
    if travels:
        trip = f" a median {km} km" if km else ""
        return f"{title} close to home: people here travel{trip} for the {places} they love most."
    if under:
        return f"{title} for a block with {nearby} where its density predicts about {expected:g}."
    ref = row.get("ref_rank")
    if ref is not None and ref - row["demand_rank"] >= 3:
        return f"{title} for neighbors who rank it #{row['demand_rank']}, against #{round(ref)} in the areas around."
    if row["demand_rank"] <= 3:
        return f"{title} for the neighborhood's #{row['demand_rank']} interest, better than the {nearby} already inside the walk."
    return f"{title} for neighbors who rank it #{row['demand_rank']} among the place types they engage with."


# Genres too broad to open as a business ('Personal care' is salons, barbers, spas and gyms at once): they stay in the
# gap table as evidence, but a concept is always a business someone can open.
TOO_BROAD = {"personalcare", "healthandbeauty", "beauty", "wellness", "shopping", "services", "entertainment"}


def concept_rows(run: RunState) -> list[dict]:
    """The rows concepts are built on: the strongest gaps the unit and the owner's notes allow, one per kind of
    business, the owner's requested business first. A category whose every loved item the owner's rules forbid is left
    out: its concept would have nothing to sell."""
    fitting = [
        row for row in run.gaps
        if fits(row) and scoring.genre_key(row["genre"]) not in TOO_BROAD and not loses_signature(run, row)
    ]
    solid = [row for row in fitting if row.get("evidence") == "ok"]
    rows: list[dict] = []
    for row in solid or fitting:
        if not any(same_business(row["genre"], kept["genre"]) for kept in rows):
            rows.append(row)
    rows = rows[:3]
    wanted = requested_row(run)
    if wanted:
        rows = [wanted] + [row for row in rows if not same_business(row["genre"], wanted["genre"])][:2]
    return rows


def loses_signature(run: RunState, row: dict) -> bool:
    """Whether the owner's rules forbid everything the places people here love of this kind are known for."""
    return bool(offer_items(row, None, limit=1)) and not offer_items(row, run.constraints, limit=1)


# Demand ranks are a reason to open only near the top; lower down, "who rank it #21" reads as a weakness.
TOP_DEMAND = 10


def for_whom(row: dict, minutes: int) -> str:
    """Who the evidence points to. Qloo's age and gender skews describe visitors inconsistently, so none are guessed;
    who the places people here love of this kind draw comes from Qloo's tags on those places. The trip is measured to
    the favorites outside the walk (median_far_km), and left out when that measure is missing."""
    neighbors = f"Neighbors within a {minutes}-minute walk"
    crowd = [in_running_text(label) for label in crowd_of(row)]
    draws = f"; the {plural(row['genre'])} people here love draw {scoring.natural_list(crowd)}" if crowd else ""
    if row.get("favorites_kind") == "local" and row["favorites_far"] >= 3:
        names = [c["name"] for c in storefront_favorites(row)[1] if c.get("name") and not c.get("within_walk")][:2]
        like = f" such as {scoring.natural_list(names)}" if names else ""
        km = row.get("median_far_km")
        trip = f"travel a median {km} km to" if km else "travel to"
        return f"{neighbors} who now {trip} {plural(row['genre'])}{like}{draws}"
    if row["demand_rank"] <= TOP_DEMAND:
        rank = f"{neighbors}, who rank {in_sentence(row['genre'])} #{row['demand_rank']} among the place types they engage with"
        return rank + draws
    return neighbors + draws


def rule_concepts(run: RunState) -> list[dict]:
    """The evidence rules' concepts: the strongest rows the unit and the notes allow, then the wildcard, if any."""
    concepts: list[dict] = []
    for row in concept_rows(run):
        concepts.append(rule_concept(run, row, {c["name"] for c in concepts}))
    return with_wildcard(run, concepts)


def rule_concept(run: RunState, row: dict, taken: set[str] | None = None) -> dict:
    """A concept built from the evidence alone, within the owner's rules; `taken` holds names other concepts have."""
    minutes = run.site.minutes
    _, cards = storefront_favorites(row)
    price = row.get("price") or price_evidence(row, run.constraints, block_price(run))
    concept = {
        "name": invent_name(run, row["genre"], set(taken or ())),
        "genre": row["genre"],
        "genre_id": row["genre_id"],
        "gap_score": row["gap_score"],
        "one_liner": one_liner(row, minutes),
        "for_whom": for_whom(row, minutes),
        "price_level": price["level"],
        "price_basis": price["basis"],
        "price_anchors": price["anchors"],
        "why_here": gap_evidence(row, minutes),
        "beat_competitors": competition(row, minutes, run.constraints),
        "signature": [i["item"] for i in offer_items(row, run.constraints, limit=3)],
        "inspired_by": [card["name"] for card in cards[:3] if card.get("name")],
        "risk": concept_risk(run, row, price["level"]),
        "evidence": gap_evidence(row, minutes),
    }
    concept["owner_rules"] = owner_rule_lines(run, row, concept)
    return concept


def requested_first(run: RunState, concepts: list[dict]) -> list[dict]:
    """The owner's requested business leads the concepts; the evidence rules design it when the agent did not."""
    wanted = requested_row(run)
    if not wanted or not concepts:
        return concepts
    mine = next((c for c in concepts if c["genre_id"] == wanted["genre_id"]), None) or rule_concept(
        run, wanted, {c["name"] for c in concepts},
    )
    return [mine] + [c for c in concepts if not same_business(c["genre"], wanted["genre"])][:2]


# ---------- How each concept meets the owner's rules ----------

# Food a ventless oven finishes; anything else on a no-hood menu is assembled cold.
BAKED_ITEM = re.compile(
    r"\b(bak(e|ed|es|ery)|breads?|buns?|rolls?|muffins?|croissants?|pastr(y|ies)|cakes?|cookies?|brownies?|tarts?|"
    r"pies?|scones?|focaccia|flatbreads?|toasts?|toasties|quiches?|galettes?|kolaches?|danish|biscuits?|bagels?|"
    r"loaf|loaves|pretzels?|gratin|lasagn[ae]|roast(ed)?|feteer|fatayer|man[a']?(kish|oushe)|pitas?|sourdough|"
    r"crumble|cobbler|brul[eé]e|souffl[eé]|madeleines?|cinnamon|knafeh|kunafa|basbousa|baklava)\b",
    re.IGNORECASE,
)
DRINK_ITEM = re.compile(
    r"\b(lattes?|coffee|espresso|cappuccino|americano|macchiato|mocha|cold brew|teas?|matcha|chai|juices?|smoothies?|"
    r"shakes?|milkshakes?|lemonade|sodas?|tonic|wines?|cocktails?|martinis?|beers?|cider|spritz|kombucha|cocoa|"
    r"hot chocolate|sahlab|horchata|drinks?|mocktails?|sake|whiske?y|mead|flights?|floats?|egg creams?)\b",
    re.IGNORECASE,
)


def unit_line(run: RunState, genre: str) -> str | None:
    """How a concept of this kind fits the unit, when the owner gave its size: 'Fits 45 m² (484 ft²): a bar counter
    and about 20–24 seats at most.' Capacity is the building-code estimate the design sheet uses."""
    size = run.site.size_m2 or run.constraints.size_m2
    if not size:
        return None
    area = space.size_text(size)
    cap = space.capacity(size, genre)
    kind = scoring.genre_kind(genre)
    if cap:
        count = f"{cap['low']}" if cap["low"] == cap["high"] else f"{cap['low']}–{cap['high']}"
        if cap["mode"] == "standing":
            return f"Fits {area}: a bar along one wall and room for about {count} standing guests at most."
        counter = "a bar counter" if kind == "bar" else "a counter"
        return f"Fits {area}: {counter} and about {count} seats at most."
    if kind == "retail":
        return f"Fits {area}: a shop floor with a counter."
    return f"Fits {area}: a front desk and a studio or treatment room."


def kitchen_line(run: RunState, genre: str, items: list[str]) -> str | None:
    """How a concept works without an extraction hood (or a kitchen), when the unit has none: the method for its menu."""
    rules = run.constraints
    if not rules.hood_free:
        return None
    kind = scoring.genre_kind(genre)
    if kind in ("retail", "wellness"):
        return "Needs no kitchen: nothing is cooked." if rules.no_cooking else "Needs no hood: nothing is cooked."
    counter = "the bar" if kind in ("bar", "venue") else "the counter"
    if rules.no_cooking:
        return (f"Needs no kitchen: nothing is cooked on site; drinks are made at {counter} and the food comes in ready to "
                f"serve or is assembled cold.")
    food = [item for item in items if not DRINK_ITEM.search(item)]
    drinks = kind in ("bar", "venue") or any(DRINK_ITEM.search(item) for item in items)
    if kind == "venue" and not any(BAKED_ITEM.search(item) for item in food):
        made = "drinks come from the bar and snacks are assembled cold"
    elif not food:
        made = f"drinks are made at {counter} and any food is assembled cold or comes in ready to serve"
    else:
        ways = [way for way, used in (
            ("baked in a ventless oven", any(BAKED_ITEM.search(item) for item in food)),
            ("assembled cold", any(not BAKED_ITEM.search(item) for item in food)),
        ) if used]
        made = (f"drinks are made at {counter} and " if drinks else "") + f"the food is {' or '.join(ways)}"
    return f"No hood needed: {made}; nothing is fried, grilled or cooked on a flat-top."


def price_line(run: RunState, row: dict | None, level: int | None) -> str | None:
    """Where the concept's price sits, when the owner's notes set a price range."""
    rules = run.constraints
    if rules.budget:
        price = (row or {}).get("price") or {}
        budget = price.get("budget") or (price_evidence(row, rules, block_price(run)).get("budget") if row else None)
        return budget["line"] if budget else "Budget: $, the lowest level."
    if rules.price and level:
        label = "Mid-range" if rules.price == (2, 2) else "Upscale" if rules.price[0] >= 3 else "Priced"
        return f"{label}: {dollars(level)}, as your notes ask."
    return None


def owner_rule_lines(run: RunState, row: dict | None, concept: dict) -> list[str]:
    """How the concept meets each rule the owner gave, in plain words: the unit's size, the kitchen, the price, the
    diet and who it is for."""
    rules = run.constraints
    genre = concept.get("genre") or (row or {}).get("genre") or ""
    items = [item for item in concept.get("signature") or [] if isinstance(item, str)]
    lines = [unit_line(run, genre), kitchen_line(run, genre, items), price_line(run, row, concept.get("price_level"))]
    if rules.vegetarian:
        lines.append("Vegetarian: no meat or fish on the menu.")
    if rules.halal:
        lines.append("Halal: no pork and no alcohol.")
    elif rules.no_alcohol:
        lines.append("No alcohol on the menu.")
    if rules.family:
        lines.append("Family friendly: no bar and no nightlife.")
    return [line for line in lines if line]


def rule_problems(run: RunState, row: dict, concept: dict) -> list[str]:
    """What still breaks the owner's rules after the repair, each as a phrase; empty when the concept keeps them all."""
    rules = run.constraints
    problems = [] if fits(row) else [misfit(row)]
    level = concept.get("price_level")
    if rules.price and level is not None and not rules.price[0] <= level <= rules.price[1]:
        problems.append(f"it is priced {dollars(level)}, outside the prices your notes allow")
    problems += [f"{item} {why}" for item in concept.get("signature") or [] if (why := rules.item_problem(item))]
    for key, label in (("name", "name"), ("one_liner", "one-liner")):
        why = rules.item_problem(str(concept.get(key) or ""))
        if why:
            problems.append(f"its {label} names something that {why}")
    if rules.budget and UPSCALE.search(str(concept.get("one_liner") or "")):
        problems.append("it is described as upscale on a budget")
    if placeholder_name(str(concept.get("name") or ""), concept["genre"], run.site.label):
        problems.append("it has no real name")
    said = " ".join(concept.get("owner_rules") or [])
    if (run.site.size_m2 or rules.size_m2) and "Fits " not in said:
        problems.append("it does not say how it fits the unit")
    if rules.hood_free and not re.search(r"\b(hood|kitchen)\b", said):
        problems.append("it does not say how it works without a hood")
    if rules.budget and "Budget" not in said:
        problems.append("it does not say where its price sits")
    return problems


# ---------- The wildcard ----------

WILDCARD_CAUTION = (
    "Untested: nothing like this exists nearby, so there is no direct proof people would come; it rests on two separate "
    "loves."
)
# Kinds of business one storefront can be at once.
COMBINABLE = {frozenset(pair) for pair in (
    ("food", "bar"), ("food", "venue"), ("food", "retail"), ("food", "wellness"), ("bar", "venue"), ("bar", "retail"),
    ("venue", "retail"), ("retail", "wellness"),
)}
# Food formats that sit beside a meal; two food categories combine when exactly one of them is such a format.
LIGHT_FORMAT = re.compile(
    r"\b(coffee|caf[eé]|espresso|tea|juice|smoothie|dessert|ice cream|gelato|frozen yogurt|chocolate|bakery|patisserie|"
    r"pastry|donut)\b",
    re.IGNORECASE,
)


def combinable(first: str, second: str) -> bool:
    """Whether one storefront can be both kinds of business: a café and a music venue, not a wine bar and a pub."""
    a, b = scoring.genre_kind(first), scoring.genre_kind(second)
    if a != b:
        return frozenset((a, b)) in COMBINABLE
    if a == "food":
        return bool(LIGHT_FORMAT.search(first)) != bool(LIGHT_FORMAT.search(second))
    return a == "retail"


def carries(place: dict, row: dict) -> bool:
    """Whether a place is (also) this row's kind of business."""
    return any(tag == row["genre_id"] or same_business(name, row["genre"]) for tag, name in scoring.genre_tags(place))


def combined_inside(run: RunState, first: dict, second: dict) -> bool:
    """Whether a place inside the walk is already both kinds of business."""
    places = [*run.block, *(first.get("_nearby_entities") or []), *(second.get("_nearby_entities") or [])]
    return any(carries(place, first) and carries(place, second) for place in places)


def wildcard_pair(run: RunState) -> tuple[dict, str, dict, str] | None:
    """The two categories people here demonstrably love (love_evidence) that combine into the business no place inside
    the walk already is, both allowed by the unit and the owner's notes: (first, its evidence, second, its evidence),
    the stronger love first. None when no pair qualifies."""
    loved = []
    for row in run.gaps:
        if not fits(row) or scoring.genre_key(row["genre"]) in TOO_BROAD or not scoring.strict_kind(row["genre"]):
            continue
        love = love_evidence(row)
        if love and not loses_signature(run, row):
            loved.append((row, love))
    best = None
    for (a, (score_a, why_a)), (b, (score_b, why_b)) in combinations(loved, 2):
        if same_business(a["genre"], b["genre"]) or not combinable(a["genre"], b["genre"]) or combined_inside(run, a, b):
            continue
        mixed = 0.5 if scoring.genre_kind(a["genre"]) != scoring.genre_kind(b["genre"]) else 0.0
        key = (score_a + score_b + mixed, a["gap_score"] + b["gap_score"])
        if best is None or key > best[0]:
            pair = [(score_a, a["gap_score"], a, why_a), (score_b, b["gap_score"], b, why_b)]
            pair.sort(key=lambda side: (side[0], side[1]), reverse=True)
            best = (key, pair)
    if not best:
        return None
    (_, _, first, why_first), (_, _, second, why_second) = best[1]
    return first, why_first, second, why_second


def article(phrase: str) -> str:
    return f"{'an' if phrase[:1].lower() in 'aeiou' else 'a'} {phrase}"


def wildcard_line(first: dict, second: dict, minutes: int) -> str:
    """The wildcard's positioning when the model gave none: what it combines, and that the walk has nothing like it."""
    for day, night in ((first, second), (second, first)):
        if LIGHT_FORMAT.search(day["genre"]) and scoring.genre_kind(night["genre"]) in ("bar", "venue"):
            return (f"{article(singular(day['genre'])).capitalize()} by day and {article(singular(night['genre']))} by "
                    f"night, under one roof: two things people here love, and nothing inside the {minutes}-minute walk "
                    f"is both.")
    return (f"{article(singular(first['genre'])).capitalize()} and {article(singular(second['genre']))} in one: two "
            f"things people here love, and nothing inside the {minutes}-minute walk is both.")


def wildcard_items(run: RunState, first: dict, second: dict) -> list[str]:
    """What the places people here love of both kinds are known for, within the owner's rules: the first kind's two
    leading items, and the second's when it sells food or drink."""
    items = [i["item"] for i in offer_items(first, run.constraints, limit=4)][:2]
    if scoring.genre_kind(second["genre"]) in ("food", "bar"):
        items += [i["item"] for i in offer_items(second, run.constraints, limit=4)][:2]
    seen: set[str] = set()
    return [item for item in items if not (scoring.item_key(item) in seen or seen.add(scoring.item_key(item)))][:4]


def wildcard_concept(run: RunState, ranked: list[dict], proposed: object = None, notes: list[str] | None = None) -> dict | None:
    """At most one concept after the ranked ones, when the evidence supports it: two things people here love, combined
    into a business no place inside the walk is. It keeps the owner's rules like any concept, carries `wildcard`,
    `combines` and a plain caution, and is never ranked (no gap score). `proposed` is the model's name, one-liner and
    signature for it, kept where they pass the same checks."""
    notes = notes if notes is not None else []
    pair = wildcard_pair(run) if ranked else None
    if not pair:
        return None
    first, why_first, second, why_second = pair
    minutes = run.site.minutes
    proposal = proposed if isinstance(proposed, dict) else {}
    taken = {c["name"] for c in ranked}
    places = place_names(run)
    name = " ".join(str(proposal.get("name") or "").split())[:60]
    if not name or taken_name(name, places) or placeholder_name(name, first["genre"], run.site.label) \
            or name.lower() in {t.lower() for t in taken} or run.constraints.item_problem(name):
        name = invent_name(run, first["genre"], taken, second=second["genre"])
    line = " ".join(str(proposal.get("one_liner") or "").split())
    if not line or UNIT_CLAIM.search(line) or run.constraints.item_problem(line) or (
            run.constraints.budget and UPSCALE.search(line)):
        line = wildcard_line(first, second, minutes)
    signature, removed = ruled_items(proposal.get("signature"), wildcard_items(run, first, second), run, fallback=4)
    if removed:
        notes.append(f"{name}: took out {removed_text(removed)}.")
    level, basis = grounded_price(run, first, proposal.get("price_level"))
    cards = [card for row in (first, second) for card in storefront_favorites(row)[1][:2] if card.get("name")]
    both = f"{article(singular(first['genre']))} and {article(singular(second['genre']))}"
    halves = [count_of(row["genre"], row["nearby_count"], row.get("nearby_capped"))
              for row in (first, second) if row["nearby_count"]]
    beat = (f"No place inside the walk is both; the nearest competition is the {' and the '.join(halves)} inside the "
            f"walk, each doing one half." if halves else "No place inside the walk is either.")
    concept = {
        "name": name,
        "genre": first["genre"],
        "genre_id": first["genre_id"],
        "gap_score": None,
        "wildcard": True,
        "combines": [
            {"item": plural(row["genre"]), "genre": row["genre"], "source": f"{why[:1].upper() + why[1:]} (Qloo)."}
            for row, why in ((first, why_first), (second, why_second))
        ],
        "caution": WILDCARD_CAUTION,
        "one_liner": NEXT_DOOR.sub("nearby", line),
        "for_whom": f"Neighbors within a {minutes}-minute walk who love both {plural(first['genre'])} and "
                    f"{plural(second['genre'])}",
        "price_level": level,
        "price_basis": basis,
        "price_anchors": price_anchors(first, level),
        "why_here": [
            f"{why_first[:1].upper() + why_first[1:]}.",
            f"{why_second[:1].upper() + why_second[1:]}.",
            f"No place inside the {minutes}-minute walk is both {both}.",
        ],
        "beat_competitors": beat,
        "signature": signature,
        "inspired_by": list(dict.fromkeys(card["name"] for card in cards))[:4],
        "risk": WILDCARD_CAUTION,
    }
    concept["evidence"] = concept["why_here"]
    concept["owner_rules"] = owner_rule_lines(run, first, concept)
    problems = rule_problems(run, first, concept) + ([] if fits(second) else [misfit(second)])
    if problems:
        notes.append(f"Dropped the wildcard {name}: {'; '.join(problems)}.")
        return None
    return concept


def with_wildcard(run: RunState, ranked: list[dict], proposed: object = None, notes: list[str] | None = None) -> list[dict]:
    """The ranked concepts, then the wildcard when the evidence supports one."""
    wildcard = wildcard_concept(run, ranked, proposed, notes)
    return [*ranked, wildcard] if wildcard else ranked


def wildcard_brief(run: RunState) -> dict | None:
    """The wildcard the evidence supports, as the agent sees it: the two loves it combines and what they are known for."""
    pair = wildcard_pair(run)
    if not pair:
        return None
    first, why_first, second, why_second = pair
    return {
        "combines": [{"genre": first["genre"], "evidence": why_first}, {"genre": second["genre"], "evidence": why_second}],
        "inside_the_walk": "no place is both",
        "loved_items": wildcard_items(run, first, second),
    }


def agent_brief(run: RunState) -> dict:
    """The evidence pack the agent reads, with the wildcard candidate when there is one."""
    brief = evidence_brief(run)
    candidate = wildcard_brief(run)
    if candidate:
        brief["wildcard_candidate"] = candidate
    return brief


CONCEPT_SYSTEM = """You are a retail and hospitality strategist who designs businesses for empty storefronts.
You only reason from Qloo evidence about the people inside the site's walking catchment: residents, workers and visitors
alike, so call them "people here", never "locals".
Demand is compared with six same-size areas around the site, not the whole city; supply is compared with what a block
this dense would typically hold. Only claim that people here travel for something when the evidence says so; when it
says their favorites are just the city's famous places, there is no travel evidence. Distances are medians, not
averages.
Work like an analyst, in as few turns as possible. Tools called in the same turn run in parallel, so batch them:
1. First turn: test_category for up to 3 hunches the gap table does not cover, drawn from the brands, artists, films,
   shows and taste cues this area over-indexes on (sports teams suggest a sports bar; design brands suggest a concept
   store); in the same turn, inspect_gap and fan_taste for the 2 or 3 strongest gaps. Fan taste is the category's
   audience at large, not only people here: only its overlap with the area's signature taste is evidence of fit.
2. Second turn, only if needed: inspect_gap or fan_taste for a tested category you now want to build on.
3. Then call submit_concepts with exactly 3 concepts, each on a different genre from the gap table or your tests.
   Build on the strongest gaps: a category with a gap score under 30 is not a recommendation while stronger ones fit
   (a weak test result is a finding, not a concept), unless it is the owner's request.
Give every tool call a one-sentence reason that names the evidence behind it.
Your job in submit_concepts is to choose, name and position. The server writes every factual line itself from the
measured evidence (why here, who it is for, the competition, the price basis, the risk and how each concept meets the
owner's rules), so do not restate numbers.
Hard rules. The server checks every concept against them after you answer: what breaks one is repaired once and a
concept that still breaks one is dropped, so keep them exactly.
- owner_constraints and the unit: never a category ruled_out_by_owner_notes or whose fits_the_unit starts with "no"
  (test categories that fit instead), and nothing in the offer they forbid.
- Budget (owner_constraints.budget): price_level 1 ($), below what the block charges; $$ is never budget, and a
  budget concept is never described as upscale or premium.
- No hood (owner_constraints.no_hood, or a light kitchen): no signature item that needs a deep fryer, a griddle or
  flat-top, a grill or charcoal, a wok or a pizza oven (no fries, crispy potatoes, tempura, katsu, karaage, falafel or
  taameya, donuts, churros, burgers, kebabs or kofta, steaks, fried chicken or pizza, and no one_liner that promises
  them); everything is baked in a ventless oven or assembled cold. No kitchen (owner_constraints.no_kitchen): nothing
  is cooked at all.
- Vegetarian: no meat or fish in any item. Halal: no pork and no alcohol. Family friendly: no bars or nightlife.
- Names are original business names ("Ube & Oak"), never a category plus the neighborhood ("Breakfast, Zamalek"), and
  never reuse or echo the name of an existing place.
Other rules: never invent places, brands or statistics; inspired_by only contains names returned by inspect_gap; when
the evidence has an owner_request, the first concept is that business (its genre exactly as given), designed to win at
this site, and the other two are the strongest alternatives; respect the owner's other notes.
Be specific enough that an owner could act on it, never filler such as "great vibes" or "quality and atmosphere":
- three concepts are three different businesses (not brunch and breakfast, not a café and a coffee shop), each one a
  business someone can open: never a broad genre such as Personal care; test a specific one instead (gym, barbershop);
- one_liner is the positioning in one sentence: what it is and how it differs from the competitors inside the walk.
  It states no number the evidence does not give (no seat counts, floor areas, years or prices) and places no
  competitor "next door" (they are inside the walk);
- signature items come first from inspect_gap's menu_gap: what the places people here love are known for and no place
  inside the walk is;
- price_level follows the price_evidence and the owner's price range.
When the evidence has a wildcard_candidate, also submit wildcard: one business that combines exactly its two loves,
with a name, a one_liner and signature items drawn from its loved_items, under the same hard rules. It is shown after
the three concepts as untested and is never ranked."""


MAX_LIVE_TESTS = 3


MAX_FAN_CHECKS = 4


REASON = {"type": "string", "description": "One sentence: why you are checking this, naming the evidence behind it"}


CONCEPT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "test_category",
            "description": "Test a business category that is not in the gap table, live against Qloo: places inside the walk, "
                           "what the surroundings predict, places people here love versus the city's, and a gap score on "
                           "the same scale as the table. At most 3 per survey.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "A storefront category, e.g. 'bakery' or 'sports bar'"},
                    "reason": REASON,
                },
                "required": ["category", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fan_taste",
            "description": "Live Qloo cross-domain check: brands and artists that people who love a category also love "
                           "(its audience at large, biased to this area), which of them belong to this area's signature "
                           "taste, and whether Qloo ignores the category as a signal here.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "A genre from the gap table or a tested category"},
                    "reason": REASON,
                },
                "required": ["category", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_gap",
            "description": "Competitors within walking distance (with what reviews know them for and complain about) and "
                           "the favorite places of people here of one genre, plus the design DNA of those favorites.",
            "parameters": {
                "type": "object",
                "properties": {
                    "genre": {"type": "string", "description": "Genre exactly as written in the gap table or a test result"},
                    "reason": REASON,
                },
                "required": ["genre", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_concepts",
            "description": "Submit the final 3 concepts, and the wildcard when the evidence has a wildcard_candidate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "concepts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "A memorable venue name"},
                                "genre": {"type": "string", "description": "Genre exactly as written in the gap table or a test result"},
                                "one_liner": {"type": "string", "description": "The positioning: what it is and how it differs from the competitors inside the walk"},
                                "price_level": {"type": "integer", "minimum": 1, "maximum": 4},
                                "signature": {"type": "array", "items": {"type": "string"},
                                              "description": "3-4 short items (2-6 words each): dishes, drinks or experiences "
                                                             "people would come for; never the room, seating or mood"},
                                "inspired_by": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["name", "genre", "one_liner", "signature"],
                        },
                    },
                    "wildcard": {
                        "type": "object",
                        "description": "Only with a wildcard_candidate: one business combining exactly its two loves",
                        "properties": {
                            "name": {"type": "string", "description": "A memorable venue name"},
                            "one_liner": {"type": "string", "description": "What it is: the two loves in one storefront"},
                            "signature": {"type": "array", "items": {"type": "string"},
                                          "description": "3-4 short items, drawn from the candidate's loved_items"},
                        },
                    },
                },
                "required": ["concepts"],
            },
        },
    },
]


AGENT_VERSION = fingerprint(CONCEPT_SYSTEM, CONCEPT_TOOLS, MAX_LIVE_TESTS, MAX_FAN_CHECKS)


@dataclass
class AgentResult:
    concepts: list[dict]
    raw_concepts: list[dict]
    model: str | None
    trail: list[list]  # replayable record of what the agent did: [event, data] pairs
    raw_wildcard: dict | None = None  # the model's name, one-liner and signature for the wildcard, as it sent them
    notes: list[str] = field(default_factory=list)  # what the owner's rules repaired or dropped, in plain words


async def agent_concepts(llm: LLM, q: QlooClient, run: RunState, emit: Emit) -> AgentResult:
    trail: list[list] = []
    testing: dict[str, asyncio.Future] = {}  # genre id -> live measurement, shared by concurrent calls
    announced: set[tuple[str, str]] = set()
    results: dict[tuple[str, str], asyncio.Future] = {}
    fan_checks = 0

    def call_key(name: str, args: dict) -> tuple[str, str]:
        return name, str(args.get("category") or args.get("genre") or "").strip().lower()

    async def record(event: str, data: dict) -> None:
        trail.append([event, data])
        await emit(event, data)

    async def refuse(message: str) -> dict:
        await record("finding", {"text": message})
        return {"error": message}

    async def inspect(args: dict) -> dict:
        row = gap_for(run, str(args.get("genre") or ""))
        return inspect_payload(run, row) if row else {"error": "Unknown genre. Use one from the gap table or a test result."}

    async def resolve(query: str) -> tuple[dict | None, str | None]:
        row = gap_for(run, query)
        if row:
            return {"id": row["genre_id"], "name": row["genre"]}, None
        return await engine.find_genre(q, run.genres, query)

    async def measure(genre: dict) -> dict:
        row = annotate(run, await engine.probe_genre(q, run.catchment, genre, run.gaps))
        row["source"] = "agent"
        run.explored.append(row)
        trail.append(["explored", {"genre": genre}])
        await emit("explored", {"row": public_gap(row)})
        if not fits(row):
            await record("finding", {"text": f"{row['genre']} does not fit this unit: it {row['fit']['reason']}."})
        return row

    async def test_category(args: dict) -> dict:
        query = str(args.get("category") or "").strip()[:80]
        try:
            genre, why_not = await engine.find_genre(q, run.genres, query) if query else (None, "No category given.")
        except QlooError as exc:
            return await refuse(f"Qloo lookup for '{query}' failed: {exc}")
        if not genre:
            return await refuse(why_not or f"Qloo has no storefront category matching '{query}'.")
        if genre["id"] not in testing:
            existing = gap_for(run, genre["name"])
            if existing:
                await record("finding", {"text": f"{existing['genre']} is already in the gap table (gap {existing['gap_score']})."})
                return {"already_measured": True, **gap_summary(existing)}
            if not scoring.matches_focus(genre["name"], run.site.focus):
                return await refuse(f"{genre['name']} is outside the owner's focus.")
            if len(testing) >= MAX_LIVE_TESTS:
                return await refuse(f"Live test budget used ({MAX_LIVE_TESTS} per survey).")
            testing[genre["id"]] = asyncio.ensure_future(measure(genre))
        try:
            row = await asyncio.shield(testing[genre["id"]])
        except QlooError as exc:
            return await refuse(f"Qloo test of {genre['name']} failed: {exc}")
        return {"tested_live": True, **gap_summary(row), "evidence": gap_evidence(row, run.site.minutes)}

    async def fan_taste(args: dict) -> dict:
        nonlocal fan_checks
        query = str(args.get("category") or "").strip()[:80]
        if fan_checks >= MAX_FAN_CHECKS:
            return await refuse(f"Fan taste budget used ({MAX_FAN_CHECKS} per survey).")
        fan_checks += 1
        try:
            genre, why_not = await resolve(query) if query else (None, "No category given.")
            if not genre:
                return await refuse(why_not or f"Qloo has no storefront category matching '{query}'.")
            fans = await fans_of(q, run, genre["id"])
        except QlooError as exc:
            return await refuse(f"Qloo fan taste for '{query}' failed: {exc}")
        if not fans.get("specific"):
            await record("finding", {"text": (
                f"Qloo ranks people who love {genre['name']} like everyone near the site, so their taste says nothing "
                "specific about the category here."
            )})
            return {"category": genre["name"], "specific": False,
                    "note": "Qloo ignores this category as a signal here; this is no evidence for or against it."}
        brands = [b["name"] for b in fans["brands"]]
        artists = [a["name"] for a in fans["artists"]]
        signature = {e["name"] for e in run.taste.get("distinctive_brands", []) + run.taste.get("distinctive_artists", [])}
        shared = [name for name in brands + artists if name in signature]
        text = f"People who love {genre['name']} also love {', '.join(brands[:4]) or 'no brands Qloo knows'}"
        text += f"; artists {', '.join(artists[:3])}" if artists else ""
        text = text.rstrip(".") + "."
        if shared:
            text += f" Shared with this area's signature taste: {', '.join(shared)}".rstrip(".") + "."
        await record("finding", {"text": text})
        return {"category": genre["name"], "specific": True,
                "people_who_love_it_also_love": {"brands": brands, "artists": artists},
                "shared_with_area_signature": shared,
                "note": "These are the category's audience at large, not only people here; overlap with the area's "
                        "signature taste is the evidence of fit."}

    async def on_call(name: str, args: dict, thought: str | None) -> None:
        if name == "submit_concepts":
            return
        key = call_key(name, args)
        if key in announced:  # a repeated check adds nothing new to the log
            return
        announced.add(key)
        await record("agent", {"tool": name, "args": args, "thought": thought})

    def once(name: str, handler: Callable[[dict], Awaitable[dict]]) -> Callable[[dict], Awaitable[dict]]:
        """Runs each distinct check once; a repeat gets the earlier result back, saying so."""
        async def checked(args: dict) -> dict:
            key = call_key(name, args)
            if key in results:
                result = await asyncio.shield(results[key])
                return {**result, "note": "You already ran this check in this survey; this is the same result."}
            results[key] = asyncio.ensure_future(handler(args))
            return await asyncio.shield(results[key])
        return checked

    async def on_step(step: int, phase: str) -> None:
        label = "Agent reads the evidence and plans what to check" if step == 0 else "Agent weighs what it found"
        state = {"start": "running", "end": "done"}.get(phase, phase)
        await emit("status", {"step": f"agent-{step}", "state": state, "label": label})

    waits = 0

    async def on_wait(seconds: float, phase: str) -> None:
        nonlocal waits
        if phase == "start":
            waits += 1
        await emit("status", {
            "step": f"agent-wait-{waits}", "state": "running" if phase == "start" else "done",
            "label": f"Free AI quota refills in {max(1, round(seconds))} s; the agent waits",
        })

    result, model = await llm.run_tools(
        CONCEPT_SYSTEM,
        "Evidence pack:\n" + json.dumps(agent_brief(run), ensure_ascii=False),
        CONCEPT_TOOLS,
        {
            "inspect_gap": once("inspect_gap", inspect),
            "test_category": once("test_category", test_category),
            "fan_taste": once("fan_taste", fan_taste),
        },
        final_tool="submit_concepts",
        max_steps=6,
        on_call=on_call,
        on_step=on_step,
        on_wait=on_wait,
    )
    raw = [c for c in submitted(result, "concepts") or [] if isinstance(c, dict)]
    wildcard = submitted(result, "wildcard")
    log.info("Agent %s submitted %s", model, [(c.get("name"), c.get("genre")) for c in raw] if result else "nothing")
    notes: list[str] = [] if raw else ["The agent submitted no concepts, so the evidence rules designed them."]
    concepts = clean_concepts(run, copy.deepcopy(raw), notes)
    return AgentResult(concepts, raw, model, trail, wildcard if isinstance(wildcard, dict) else None, notes)


def submitted(result: dict | None, key: str) -> object:
    """A field of the agent's submission; some models send a list or an object as a JSON string, which is read too."""
    value = (result or {}).get(key)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value


async def replay_agent(
    q: QlooClient, run: RunState, saved: dict, emit: Emit, notes: list[str] | None = None,
) -> list[dict]:
    """Re-emits a saved investigation for identical evidence; live tests are re-measured from the Qloo cache."""
    for event, data in saved.get("trail", []):
        if event == "explored":
            row = annotate(run, await engine.probe_genre(q, run.catchment, data["genre"], run.gaps))
            row["source"] = "agent"
            run.explored.append(row)
            await emit("explored", {"row": public_gap(row)})
        else:
            await emit(event, data)
    return clean_concepts(run, copy.deepcopy(saved.get("raw_concepts", [])), notes)


async def concepts_from_agent(
    llm: LLM, q: QlooClient, run: RunState, emit: Emit, answers: AnswerCache | None,
) -> tuple[list[dict], dict]:
    """The agent's concepts and how they were made; an empty list means the evidence rules must step in.

    The ranked concepts come first, then the wildcard when the evidence supports one. `notes` in the second value says,
    in plain words, what was repaired, replaced or dropped, the owner's rules first among the reasons."""
    key = fingerprint("concepts", AGENT_VERSION, agent_brief(run))
    saved = answers.get("concepts", key) if answers else None
    notes: list[str] = []
    try:
        if saved:
            await emit("replay", {"saved_at": saved.get("saved_at"), "model": saved.get("model")})
            concepts = await replay_agent(q, run, saved, emit, notes)
            ranked = requested_first(run, strong_enough(run, concepts, notes))
            about = {"model": saved.get("model"), "replayed_from": saved.get("saved_at")}
            return with_wildcard(run, ranked, saved.get("raw_wildcard"), notes), with_notes(about, notes)
        result = await agent_concepts(llm, q, run, emit)
    except LLMUnavailable:
        log.warning("Every LLM model is resting; falling back to evidence rules", exc_info=True)
        await emit("notice", {"message": "Every free AI model is busy or out of quota right now, so these concepts come from the evidence rules."})
        return [], {}
    except Exception as exc:  # LLM outages must not break the demo
        log.warning("Concept agent failed; falling back to evidence rules", exc_info=True)
        await emit("notice", {"message": f"The AI agent failed ({type(exc).__name__}), so these concepts come from the evidence rules."})
        return [], {}
    if result.concepts and answers:
        answers.put("concepts", key, {"trail": result.trail, "raw_concepts": result.raw_concepts, "model": result.model,
                                      "raw_wildcard": result.raw_wildcard})
    notes = result.notes
    ranked = requested_first(run, strong_enough(run, result.concepts, notes))
    return with_wildcard(run, ranked, result.raw_wildcard, notes), with_notes({"model": result.model}, notes)


def with_notes(about: dict, notes: list[str]) -> dict:
    """The concepts payload's extras, with what was repaired, replaced or dropped when anything was."""
    return {**about, "notes": list(dict.fromkeys(notes))} if notes else about


BASELINE_SYSTEM = "You are a retail strategy consultant."


async def baseline_concepts(llm: LLM, site: Site, answers: AnswerCache | None = None) -> list[dict]:
    """What a language model suggests with no data, shown next to the evidence-based concepts."""
    prompt = (
        f"There is an empty ground-floor storefront at {site.label} (lat {site.lat}, lon {site.lon}). "
        "Propose 3 business concepts likely to succeed there. Return JSON {\"concepts\": [{\"name\", \"genre\", \"one_liner\"}]}."
    )
    key = fingerprint("baseline", BASELINE_SYSTEM, prompt)
    saved = answers.get("baseline", key) if answers else None
    if saved:
        return saved.get("concepts", [])
    data, model = await llm.complete_json(BASELINE_SYSTEM, prompt)
    concepts = [c for c in data.get("concepts") or [] if isinstance(c, dict)][:3]
    if concepts and answers:
        answers.put("baseline", key, {"concepts": concepts, "model": model})
    return concepts
