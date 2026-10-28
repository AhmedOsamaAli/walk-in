"""Business names for concepts: an original name, never a category plus the neighborhood, never one that reuses
or echoes an existing place's.
"""
from __future__ import annotations

import logging
import re
import zlib

from ... import scoring
from ..evidence import short_label
from ..models import RunState

log = logging.getLogger("walkin")


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


def invent_name(run: RunState, genre: str, taken: set[str], second: str | None = None, words: tuple[str, ...] = ()) -> str:
    """A real business name for a concept the model did not name well ('Linden Coffee', 'Daybreak Table'), chosen the
    same way for the same site and category, never one an existing place or another concept here has. `words` are tried
    first ('Cliffhanger Wine Room' for a reality-TV wild card), then the rules' own."""
    noun = name_noun(genre) if not second else f"{name_noun(genre, side=True)} & {name_noun(second, side=True)}"
    places = place_names(run)
    used = {word for name in taken for word in _name_words(name)}
    seed = zlib.crc32(f"{run.site.label}|{genre}|{second or ''}".encode())
    names = [f"{pool[(seed + i) % len(pool)]} {noun}" for pool in (words, NAME_WORDS) if pool for i in range(len(pool))]
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
