"""The mood board on a design sheet: the faces, posters and brands people here over-index on, the era they point to,
and the design direction the renders follow.

The tiles are Qloo's signature taste, what people within 1.5 km rank much higher than three same-size areas around
(artists, films, shows and brands), the kinds taking turns so no one kind fills the board. When Qloo really used the
concept's category (experience.fans_of says so), the names its fans share come first. A board short of six tiles is
filled first from what those fans also love, then from what people here rank highest that is not a household name
everywhere; such tiles are marked ("via"), and only Qloo's own images are used, so the credit holds.

The era is read from the years of the names people here over-index on (films and shows by release, artists by the
year they started): the decade most of them come from, joined by its neighbor when that one holds at least half as
many. A rules table turns the era into a direction (palette, materials, lighting, lettering, music). When the years
are too few or too spread to read an era, the board says so and the direction follows the design DNA of the places
people here love instead.

A model may word the statement, with the board's names and its era only: a statement naming anything else, or a
number or year the evidence does not hold, is asked for once more, then replaced by a sentence built from the board.
The renders get the direction in words, never a name, a portrait or a poster.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlparse

from .. import scoring
from ..answers import AnswerCache, fingerprint
from ..llm import LLM
from .evidence import in_sentence
from .models import RunState

log = logging.getLogger("walkin")

MAX_TILES = 9
MIN_TILES = 6
# The kinds on the board, in the order they take turns: (run.taste domain, tile kind).
DOMAINS = (("artists", "artist"), ("movies", "film"), ("tv", "show"), ("brands", "brand"))
FAN_DOMAINS = (("artists", "artist"), ("brands", "brand"))
# What dates each kind: films and shows their release, artists the year they started. Podcasts and brands have none.
DATED = (("artists", "since"), ("movies", "year"), ("tv", "year"))
# Brands that fill a short board, most telling first: what people make and sell before banks and phone networks.
BRAND_KINDS = ("product", "retail", "personal", "media", "entertainment", "service", "corporate")
MIN_DATED = 5  # fewer names with a year say nothing about an era
MIN_SPAN_SHARE = 0.5  # an era holds at least half of the names with a year
CLASSIC_YEARS = 20  # as scoring.era: 20 years or older is a classic
CREDIT = "Images: Qloo"
SOURCE = "What people within 1.5 km over-index on compared with three same-size areas around (Qloo)"
HOW_DATED = "artists by the year they started, films and shows by release"
RETRY_S = 30.0  # longest wait for the model's second try at a statement


def swatches(*pairs: tuple[str, str]) -> list[dict]:
    return [{"hex": hex_code, "name": name} for hex_code, name in pairs]


# The direction each decade points to, for a storefront opening today: that era's palette, materials, light and
# lettering, made new. No numbers, names or brands, so any of it can go into a statement or a render prompt.
ERA_DIRECTIONS: dict[int, dict] = {
    1950: {
        "name": "Mid-century classic",
        "palette": swatches(("#6B1E23", "oxblood"), ("#B58B4C", "brass"), ("#1E4635", "bottle green"),
                            ("#F1E7D2", "ivory"), ("#5A3A26", "walnut")),
        "materials": ["walnut panelling", "brass trim", "terrazzo floors", "leather banquettes"],
        "lighting": "Milk-glass globes and brass wall sconces, warm and low",
        "type": "a gilded serif with a looping script",
    },
    1960: {
        "name": "Sixties modern",
        "palette": swatches(("#E07B30", "tangerine"), ("#6E7B39", "avocado"), ("#9B5B2D", "teak"),
                            ("#F0E5CC", "cream"), ("#2E2D2B", "ink")),
        "materials": ["teak", "rattan", "mosaic tile", "moulded plywood"],
        "lighting": "Opal globe pendants and teak floor lamps",
        "type": "a rounded geometric sans in lowercase",
    },
    1970: {
        "name": "Seventies warmth",
        "palette": swatches(("#C2602A", "burnt orange"), ("#D8A031", "mustard"), ("#6A6A2C", "olive"),
                            ("#E8DCC2", "oatmeal"), ("#4A2B1B", "chocolate")),
        "materials": ["walnut veneer", "cork", "smoked glass", "terracotta tile"],
        "lighting": "Amber glass pendants, low and warm",
        "type": "a soft, heavy serif with rounded corners",
    },
    1980: {
        "name": "Eighties gloss",
        "palette": swatches(("#E8B4AE", "blush"), ("#A3D9C9", "mint"), ("#2A4BA8", "cobalt"),
                            ("#F3F1EC", "chalk"), ("#151515", "lacquer black")),
        "materials": ["terrazzo", "glass block", "black lacquer", "chrome"],
        "lighting": "Neon accents over clean, even light",
        "type": "a neon script beside a wide geometric sans",
    },
    1990: {
        "name": "Nineties raw",
        "palette": swatches(("#2E4A35", "forest"), ("#6B2433", "burgundy"), ("#4E6C8E", "denim"),
                            ("#ECE8DE", "bone"), ("#B3A07C", "khaki")),
        "materials": ["birch plywood", "galvanized steel", "polished concrete", "corrugated metal"],
        "lighting": "Caged bare bulbs and a warm workshop glow",
        "type": "a condensed, stencil-cut sans",
    },
    2000: {
        "name": "Two-thousands sleek",
        "palette": swatches(("#5EC6D2", "aqua"), ("#B5D64B", "lime"), ("#B8BDC3", "silver"),
                            ("#F5F6F4", "gloss white"), ("#393C41", "graphite")),
        "materials": ["white lacquer", "brushed steel", "frosted acrylic", "glass"],
        "lighting": "Cool white light strips behind frosted panels",
        "type": "a rounded techno sans in lowercase",
    },
    2010: {
        "name": "Twenty-tens workshop",
        "palette": swatches(("#9B4A33", "brick"), ("#9DAF89", "sage"), ("#C6A079", "oak"),
                            ("#F1EEE8", "chalk white"), ("#33302D", "slate")),
        "materials": ["reclaimed oak", "exposed brick", "blackened steel", "marble counters"],
        "lighting": "Bare filament bulbs on cloth cords",
        "type": "a clean sans, hand-painted on the glass",
    },
    2020: {
        "name": "Warm minimal",
        "palette": swatches(("#B66A4B", "clay"), ("#6F794E", "olive"), ("#D8C2A4", "sand"),
                            ("#F2EEE6", "chalk"), ("#3A2A21", "espresso")),
        "materials": ["limewash walls", "travertine", "microcement", "curved oak"],
        "lighting": "Soft, diffused light from paper and linen shades",
        "type": "a small, widely spaced lowercase grotesk",
    },
}

# When there is no era to read: the style the favorites' design DNA tags point to, decor tags weighing double.
DNA_STYLES: tuple[tuple[str, re.Pattern, dict], ...] = (
    ("Industrial", re.compile(r"industrial|loft|warehouse|exposed", re.IGNORECASE), {
        "palette": swatches(("#9A4A34", "brick"), ("#B38A4F", "brass"), ("#8D8B86", "concrete"),
                            ("#F1EDE5", "warm white"), ("#2A2A2A", "blackened steel")),
        "materials": ["polished concrete", "blackened steel", "exposed brick", "reclaimed timber"],
        "lighting": "Metal pendants and warm task light",
        "type": "a stencil-cut sans",
    }),
    ("Vintage", re.compile(r"vintage|retro|nostalgic|diner|speakeasy|art deco|old world", re.IGNORECASE), {
        "palette": swatches(("#A3312E", "cherry"), ("#2F6E6B", "teal"), ("#D3A13A", "mustard"),
                            ("#EFE4CB", "cream"), ("#5B3C28", "walnut")),
        "materials": ["vintage furniture", "checkerboard floors", "chrome trim", "laminate counters"],
        "lighting": "Milk-glass pendants",
        "type": "a retro script over block capitals",
    }),
    ("Classic elegant", re.compile(r"elegant|upscale|luxur|sophisticat|grand|parisian|french|bistro", re.IGNORECASE), {
        "palette": swatches(("#6E1F24", "oxblood"), ("#B08D57", "brass"), ("#CDC8BF", "marble grey"),
                            ("#F2EBDD", "ivory"), ("#1F2A44", "ink navy")),
        "materials": ["marble", "brass", "velvet", "dark-stained wood"],
        "lighting": "Brass sconces and a warm, low glow",
        "type": "a high-contrast serif",
    }),
    ("Bohemian", re.compile(r"bohemian|eclectic|artistic|funky|whimsical|colorful|quirky|themed", re.IGNORECASE), {
        "palette": swatches(("#C0643F", "terracotta"), ("#2F6F73", "teal"), ("#DFA33A", "saffron"),
                            ("#F2E7D3", "cream"), ("#3F2A2E", "aubergine")),
        "materials": ["rattan", "patterned tile", "woven textiles", "mismatched vintage chairs"],
        "lighting": "Woven shades and strings of warm light",
        "type": "hand-drawn, playful letters",
    }),
    ("Rustic", re.compile(r"rustic|farmhouse|country|traditional|authentic|historic", re.IGNORECASE), {
        "palette": swatches(("#9A4E2A", "rust"), ("#3D5540", "forest"), ("#A87B4E", "oak"),
                            ("#E8E0D0", "linen"), ("#4A3B2F", "smoked timber")),
        "materials": ["raw timber", "stone", "linen", "wrought iron"],
        "lighting": "Warm lanterns and candlelight",
        "type": "a carved or hand-painted serif",
    }),
    ("Garden", re.compile(r"tropical|botanical|garden|nautical|open air|airy", re.IGNORECASE), {
        "palette": swatches(("#DE7A5F", "coral"), ("#2F6A4E", "palm green"), ("#E1D1AF", "sand"),
                            ("#F6F3EC", "shell white"), ("#1F4A5C", "deep sea")),
        "materials": ["rattan", "cane", "white plaster", "terrazzo"],
        "lighting": "Bright daylight and woven pendants",
        "type": "a breezy rounded sans",
    }),
    ("Cozy", re.compile(r"cozy|cosy|homey|warm|intimate|romantic|candle", re.IGNORECASE), {
        "palette": swatches(("#C88A3A", "amber"), ("#6C2D3A", "burgundy"), ("#5D6A44", "moss"),
                            ("#EEE2CB", "cream"), ("#3E2A1E", "walnut")),
        "materials": ["dark wood", "wool", "leather", "deep shelves"],
        "lighting": "Low, warm lamps at every table",
        "type": "a soft serif",
    }),
    ("Modern minimal", re.compile(r"minimal|modern|contemporary|clean|simple|functional|sleek|stylish", re.IGNORECASE), {
        "palette": swatches(("#A3B393", "sage"), ("#D6C19E", "pale oak"), ("#A8A49B", "stone grey"),
                            ("#F2F0EB", "chalk"), ("#1D1D1D", "black")),
        "materials": ["pale oak", "white plaster", "steel", "glass"],
        "lighting": "Even, diffused light",
        "type": "a clean grotesk",
    }),
)
CASUAL = {
    "name": "Plain and casual",
    "palette": swatches(("#C56A46", "terracotta"), ("#A2B089", "sage"), ("#C29A6B", "oak"),
                        ("#F2EEE6", "warm white"), ("#232323", "ink")),
    "materials": ["oak", "tile", "plaster", "plants"],
    "lighting": "Daylight by day, warm pendants after dark",
    "type": "a friendly sans",
}

# What would put the names on the board into the room: their pictures, their faces, their logos. The names belong to
# their owners, so neither a render prompt nor the statement may.
DECOR_USE = (
    r"posters?|portraits?|headshots?|photo(graph)?s? of|pictures? of|paintings? of|murals? of|album (art|covers?)|"
    r"record sleeves?|(film|movie) stills?|framed (photos?|photographs|prints)|autograph\w*|logos?|merch"
)
STATEMENT_DECOR = re.compile(rf"\b({DECOR_USE})\b", re.IGNORECASE)
PORTRAITS = re.compile(rf"\b({DECOR_USE}|selfies?|faces? of|celebrit(y|ies)|likeness(es)?)\b", re.IGNORECASE)

MOOD_SYSTEM = """You write the mood statement on a design sheet's mood board: one or two sentences on how the room
should feel. Use only the names in tiles, written exactly as given, and only the era given: no other names, places,
numbers or years. Start each sentence with an ordinary word, not a name. Never suggest putting these names in the room
(posters, portraits, photos or logos): they set the mood only. Return JSON: {"statement": "..."}."""


def word_set(text: str) -> frozenset[str]:
    return frozenset(text.split())


# Ordinary words a sentence of a mood statement may start with; a capitalized word anywhere else must be on the board.
STARTERS = word_set("""
a an the this that these those here there it its it's with where when while from for in on at by like as after before
between under over through every each all some most more much many few none people neighbors neighbours locals guests
everyone everything nothing light color colour colors colours music sound sounds taste mood room rooms space spaces
walls floors think picture imagine expect come step walk sit stay let let's make keep give take bring mix pair blend
borrow channel echo nod set build built lit dressed styled framed painted finished layered lean leaning go aim pull
drawing drawn inspired rooted grounded shaped warm cool soft low bright dark deep rich quiet loud slow easy bold calm
raw honest unfussy timeless nostalgic retro vintage modern classic contemporary fresh playful moody cinematic analog
analogue golden late early morning evening night nights afternoon weekend weekends so and but yet or not no just only
still even now today tonight then inside outside behind beyond above below across around along toward towards into
without within against among amid both either neither several other another such same very too quite almost always
never often sometimes again also what who why how which whose if because though although once until whether your our
we you they their mornings evenings afternoons days nightly daily linger lounge gather settle unwind sip dine browse
listen watch read talk meet stay neon amber brass oak walnut velvet terracotta concrete steel glass wood timber linen
leather marble tile tiles stone candlelight candles lamps lamp pendants shelves records vinyl playlists playlist songs
beats cosy cozy intimate lively social relaxed relaxing welcoming homey eclectic artistic industrial minimal rustic
elegant polished curated textured sleek glossy matte muted saturated faded sun-faded weathered worn lived-in handmade
crafted hand-painted clean simple plain spare lush green leafy plants greenery hushed buzzing easygoing laid-back
""")
# Words a statement may capitalize anywhere: styles and kinds of music, not names of people, works or brands.
STYLE_WORDS = word_set("""
art deco nouveau bauhaus mid-century midcentury scandinavian nordic japandi brutalist victorian edwardian baroque
modernist postmodern psychedelic tv dj djs lp lps vhs cd cds hi-fi jazz soul funk disco hip-hop rap rock pop folk r&b
indie house techno ambient afrobeat afrobeats reggae reggaeton salsa latin country blues gospel motown neo-soul grunge
punk shoegaze lo-fi
""")
NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100, "dozen": 12,
}
DECADE_WORDS = {
    "twenties": (1920, 2020), "thirties": (1930,), "forties": (1940,), "fifties": (1950,), "sixties": (1960,),
    "seventies": (1970,), "eighties": (1980,), "nineties": (1990,), "noughties": (2000,), "aughts": (2000,),
}
WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
NUMBER = re.compile(r"['’]?\d[\d,]*(?:\.\d+)?(?:s\b|%)?")
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
MAX_STATEMENT = 300  # characters besides the names on the board
MIN_WORDS = 6  # words besides the names: fewer is a list of names, not a sentence about the room


# ---------- Tiles ----------

def fold(text: Any) -> str:
    """'Beyoncé' -> 'beyonce': names compared without case, accents or punctuation."""
    if not isinstance(text, str):
        return ""
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^\w]+", " ", plain.lower()).split())


def qloo_image(url: Any) -> str | None:
    """Qloo's own image URL (images.qloo.com), so the board's credit holds; anything else is left out."""
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    host = (urlparse(url).hostname or "").lower()
    return url if host == "qloo.com" or host.endswith(".qloo.com") else None


def tile(card: Any, kind: str, via: str | None = None) -> dict | None:
    """A taste card as a tile: its name, kind, image and year (a film's or show's) or start (an artist's)."""
    if not isinstance(card, dict):
        return None
    name, image = card.get("name"), qloo_image(card.get("image"))
    if not isinstance(name, str) or not name.strip() or not image or not scoring.is_safe_name(name):
        return None
    item: dict[str, Any] = {"name": name.strip(), "kind": kind, "image": image}
    key = "since" if kind == "artist" else "year" if kind in ("film", "show") else None
    if key and isinstance(card.get(key), int) and not isinstance(card.get(key), bool):
        item[key] = card[key]
    if via:
        item["via"] = via
    return item


def take_turns(pools: list[list[dict]], limit: int, seen: set[str]) -> list[dict]:
    """Tiles from each pool in turn, best first, skipping names already on the board."""
    queues = [list(pool) for pool in pools]
    out: list[dict] = []
    while len(out) < limit and any(queues):
        for queue in queues:
            while queue and len(out) < limit:
                item = queue.pop(0)
                if fold(item["name"]) not in seen:
                    seen.add(fold(item["name"]))
                    out.append(item)
                    break
    return out


def ordinary(card: Any) -> bool:
    """Not a household name everywhere (Qloo popularity below scoring.SUPERSTAR): those top every list, so they say
    nothing about the mood of one place."""
    return isinstance(card, dict) and (card.get("popularity") or 0) < scoring.SUPERSTAR


def loved_pools(taste: dict) -> list[list[dict]]:
    """What people here rank highest, without the household names that top every list: the last filler of a board."""
    artists = [item for card in taste.get("artists") or [] if ordinary(card) and (item := tile(card, "artist", "loved"))]
    brands = sorted(
        (card for card in taste.get("brands") or [] if ordinary(card)),
        key=lambda card: BRAND_KINDS.index(card["kind"]) if card.get("kind") in BRAND_KINDS else len(BRAND_KINDS),
    )
    return [artists, [item for card in brands if (item := tile(card, "brand", "loved"))]]


def pick_tiles(taste: dict, fans: dict | None = None, limit: int = MAX_TILES, least: int = MIN_TILES) -> list[dict]:
    """Up to nine names people here over-index on that have an image, the kinds taking turns. When the category's fan
    taste is specific, the names those fans share come first in each kind. A board short of six is filled from what
    the fans also love ("via": "fans", only when specific), then from what people here rank highest ("via": "loved"),
    household names left out of both."""
    specific = bool(fans and fans.get("specific"))
    shared = {fold(card.get("name")) for domain, _ in FAN_DOMAINS for card in (fans or {}).get(domain) or []
              if isinstance(card, dict)} if specific else set()
    pools = []
    for domain, kind in DOMAINS:
        cards = [card for card in taste.get(f"distinctive_{domain}") or [] if isinstance(card, dict)]
        cards.sort(key=lambda card: fold(card.get("name")) not in shared)
        pools.append([item for card in cards if (item := tile(card, kind))])
    seen: set[str] = set()
    tiles = take_turns(pools, limit, seen)
    if specific and fans and len(tiles) < least:
        fan_pools = [[item for card in fans.get(domain) or [] if ordinary(card) and (item := tile(card, kind, "fans"))]
                     for domain, kind in FAN_DOMAINS]
        tiles += take_turns(fan_pools, least - len(tiles), seen)
    if len(tiles) < least:
        tiles += take_turns(loved_pools(taste), least - len(tiles), seen)
    return tiles


# ---------- Era ----------

def dated_years(taste: dict, this_year: int) -> list[int]:
    """The year of each artist, film and show people here over-index on that has one, each name once."""
    years, seen = [], set()
    for domain, key in DATED:
        for card in taste.get(f"distinctive_{domain}") or []:
            if not isinstance(card, dict):
                continue
            year, ident = card.get(key), card.get("id") or fold(card.get("name"))
            if isinstance(year, int) and not isinstance(year, bool) and 1880 <= year <= this_year + 1 and ident not in seen:
                seen.add(ident)
                years.append(year)
    return years


def decade_label(decades: tuple[int, ...]) -> str:
    """(1970,) -> '1970s'; (1970, 1980) -> '1970s–80s'; (1990, 2000) -> '1990s–2000s'."""
    first, last = decades[0], decades[-1]
    if first == last:
        return f"{first}s"
    return f"{first}s–{last % 100:02d}s" if first // 100 == last // 100 else f"{first}s–{last}s"


def decade_words(decades: tuple[int, ...]) -> str:
    """(1970, 1980) -> 'the 1970s and 80s', for a sentence."""
    if len(decades) == 1:
        return f"the {decades[0]}s"
    first, last = decades[0], decades[-1]
    return f"the {first}s and {last % 100:02d}s" if first // 100 == last // 100 else f"the {first}s and {last}s"


@dataclass(frozen=True)
class Era:
    """What the years of the names people here over-index on add up to."""

    dated: int = 0  # names with a year
    classic: int = 0  # of which 20 or more years old
    span: tuple[int, ...] = ()  # the decades of the dominant span
    top: int | None = None  # the decade holding the most names
    in_span: int = 0
    first: int | None = None  # the earliest and latest decades
    last: int | None = None
    this_year: int = 0

    @property
    def clear(self) -> bool:
        return self.dated >= MIN_DATED and self.in_span >= MIN_SPAN_SHARE * self.dated

    @property
    def label(self) -> str | None:
        return decade_label(self.span) if self.clear else None

    def payload(self) -> dict:
        return {
            "label": self.label,
            "from": self.span[0] if self.clear else None,
            "to": min(self.span[-1] + 9, self.this_year) if self.clear else None,
            "classic_share": round(self.classic / self.dated, 2) if self.dated else None,
            "dated": self.dated,
            "classic": self.classic,
        }


def read_era(taste: dict, this_year: int) -> Era:
    """The decade most names with a year come from, with its neighbor when that one holds at least half as many."""
    years = dated_years(taste, this_year)
    if not years:
        return Era(this_year=this_year)
    counts = Counter(year // 10 * 10 for year in years)
    top = max(counts, key=lambda decade: (counts[decade], decade))
    neighbor = max((top - 10, top + 10), key=lambda decade: (counts.get(decade, 0), decade))
    span = tuple(sorted({top, neighbor})) if counts.get(neighbor, 0) * 2 >= counts[top] else (top,)
    return Era(
        dated=len(years), classic=sum(1 for year in years if this_year - year >= CLASSIC_YEARS), span=span, top=top,
        in_span=sum(counts[decade] for decade in span), first=min(counts), last=max(counts), this_year=this_year,
    )


# ---------- Direction ----------

def era_direction(era: Era) -> dict:
    """The rules table's direction for the era's fullest decade."""
    decade = min(max(era.top or max(ERA_DIRECTIONS), min(ERA_DIRECTIONS)), max(ERA_DIRECTIONS))
    return {
        **copy.deepcopy(ERA_DIRECTIONS[decade]),
        "source": "era",
        "music": f"Records from {decade_words(era.span)}, as most of these names are",
        "cues": [],
    }


def distinct_cues(tags: list[str], limit: int = 2) -> list[str]:
    """Tags that say different things: 'Industrial chic' and 'Urban industrial' say one."""
    kept: list[str] = []
    for tag in tags:
        if not any(set(fold(tag).split()) & set(fold(other).split()) for other in kept):
            kept.append(tag)
    return kept[:limit]


def dna_direction(dna: dict) -> dict:
    """The style the favorites' design DNA points to: decor tags count twice, ambience tags once."""
    decor = [tag for tag in dna.get("decor") or [] if isinstance(tag, str)]
    ambience = [tag for tag in dna.get("ambience") or [] if isinstance(tag, str)]
    best: tuple[int, str, dict, list[str]] | None = None
    for name, pattern, style in DNA_STYLES:
        decor_hits = [tag for tag in decor if pattern.search(tag)]
        ambience_hits = [tag for tag in ambience if pattern.search(tag)]
        score = 2 * len(decor_hits) + len(ambience_hits)
        if score and (best is None or score > best[0]):
            best = (score, name, style, decor_hits + ambience_hits)
    if best:
        _, name, style, hits = best
        return {"name": name, **copy.deepcopy(style), "source": "dna", "music": None, "cues": distinct_cues(hits)}
    cues = distinct_cues(decor + ambience)
    return {**copy.deepcopy(CASUAL), "source": "dna" if cues else "default", "music": None, "cues": cues}


# ---------- The board ----------

def natural_list(items: list[str]) -> str:
    items = [item for item in items if item]
    return f"{', '.join(items[:-1])} and {items[-1]}" if len(items) > 1 else (items[0] if items else "")


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def places_loved(genre: str) -> str:
    return " ".join(f"the {genre} places people here love".split())


def plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


def basis_line(era: Era, genre: str, direction: dict) -> str:
    """How the era was read, in one plain line, and what the direction follows when there is none."""
    if era.clear:
        classic = (f"{era.classic} {plural(era.classic, 'is', 'are')} 20 or more years old" if era.classic
                   else "none is 20 or more years old")
        return (f"{era.in_span} of the {era.dated} names people here over-index on that have a year date from "
                f"{decade_words(era.span)}; {classic} ({HOW_DATED}).")
    if direction["source"] == "dna":
        follows = f"the direction follows the design DNA of {places_loved(genre)}"
    else:
        follows = "the direction is a plain, casual default, as the places people here love carry no design tags either"
    if not era.dated:
        return f"None of the names people here over-index on has a year ({HOW_DATED}): there is no era to read, so {follows}."
    if era.dated < MIN_DATED:
        return (f"Only {era.dated} of the names people here over-index on {plural(era.dated, 'has', 'have')} a year "
                f"({HOW_DATED}): too few to read an era, so {follows}.")
    return (f"The {era.dated} names people here over-index on that have a year spread from the {era.first}s to the "
            f"{era.last}s, with no era holding half of them, so {follows}.")


def source_line(tiles: list[dict], genre: str) -> str:
    """Where the tiles come from, with the share of each filler, named as the board labels them."""
    counts = Counter(item.get("via") for item in tiles)
    parts = [f"{SOURCE}."]
    if counts["fans"]:
        parts.append(f"{counts['fans']} marked “Fans’ pick” {plural(counts['fans'], 'is', 'are')} what people near here "
                     f"who love {genre} places also love.".replace("  ", " "))
    if counts["loved"]:
        parts.append(f"{counts['loved']} marked “Loved here” {plural(counts['loved'], 'is', 'are')} among what people "
                     "here rank highest, though not more than the areas around do.")
    return " ".join(parts)


def short_names(tiles: list[dict], count: int = 3) -> list[str]:
    """A few names of the area's own tiles to quote, the short ones first."""
    own = [item["name"] for item in tiles if not item.get("via")]
    return sorted(own[: count + 2], key=lambda name: len(name) > 32)[:count]


def rules_statement(tiles: list[dict], era: Era, direction: dict, genre: str) -> str:
    """The statement built from the board alone, when no model wrote one that holds."""
    names = natural_list(short_names(tiles))
    such = f", such as {names}," if names else ""
    materials = natural_list(direction["materials"][:3])
    if era.clear:
        amount = "Most" if era.in_span * 2 > era.dated else "Half"
        return (f"{amount} of what people here over-index on{such} dates from the {era.label}. The room takes that "
                f"era's look, made new: {materials} under {lower_first(direction['lighting'])}.")
    if not era.dated:
        lead = f"None of the names people here over-index on{such} carries a year, so there is no era to read."
    elif era.dated < MIN_DATED:
        lead = f"Too few of the names people here over-index on{such} carry a year to read an era."
    else:
        lead = f"The names people here over-index on{such} span too many eras to point to one."
    if direction["source"] != "dna":
        return f"{lead} The room stays plain and casual: {materials} under {lower_first(direction['lighting'])}."
    style = natural_list([cue.lower() for cue in direction["cues"]]) or lower_first(direction["name"])
    return (f"{lead} The room follows {places_loved(genre)} instead: {style}, with {materials} under "
            f"{lower_first(direction['lighting'])}.")


def build(run: RunState, concept: dict, dna: dict | None = None, fans: dict | None = None,
          this_year: int | None = None) -> dict:
    """The mood board for a concept, its statement built from the board; `finish` lets a model's wording replace it."""
    this_year = this_year or date.today().year
    taste = run.taste or {}
    tiles = pick_tiles(taste, fans)
    era = read_era(taste, this_year)
    genre = in_sentence(concept.get("genre") or "")
    direction = era_direction(era) if era.clear else dna_direction(dna or {})
    return {
        "tiles": tiles,
        "era": era.payload(),
        "direction": direction,
        "statement": rules_statement(tiles, era, direction, genre),
        "statement_by": "rules",
        "basis": basis_line(era, genre, direction),
        "source": source_line(tiles, genre),
        "credit": CREDIT,
    }


def brief(board: dict) -> dict:
    """What the design model sees of the board: the names, the era and the direction its interior follows."""
    direction = board["direction"]
    return {
        "tiles": [item["name"] for item in board["tiles"]],
        "era": board["era"]["label"] or "no clear era",
        "direction": {
            "name": direction["name"],
            "palette": [swatch["name"] for swatch in direction["palette"]],
            "materials": direction["materials"],
            "lighting": direction["lighting"],
            "lettering": direction["type"],
        },
    }


# ---------- The statement's checks ----------

def fold_keep(text: str) -> str:
    """Lowercased, without accents, curly quotes or long dashes, and the same length as the text, so a match in it is a
    match at the same place in the text."""
    out = []
    for ch in text:
        base = unicodedata.normalize("NFKD", ch)[:1] or ch
        base = {"’": "'", "‘": "'", "–": "-", "—": "-"}.get(base, base).lower()
        out.append(base if len(base) == 1 else ch)
    return "".join(out)


def mask(text: str, phrases: Iterable[str]) -> str:
    """The text with each allowed phrase (a name on the board, the concept's name) replaced by 'x'."""
    folded = fold_keep(text)
    spans: list[tuple[int, int]] = []
    wanted = {fold_keep(phrase.strip()) for phrase in phrases if isinstance(phrase, str) and phrase.strip()}
    for phrase in sorted(wanted, key=len, reverse=True):
        for match in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", folded):
            if not any(start < match.end() and match.start() < end for start, end in spans):
                spans.append((match.start(), match.end()))
    for start, end in sorted(spans, reverse=True):
        text = f"{text[:start]}x{text[end:]}"
    return text


def evidence_numbers(board: dict) -> tuple[set[float], set[int]]:
    """The numbers a statement may use (the board's years, counts, distances and shares) and the decades it may name."""
    era = board["era"]
    years = [item.get("year") or item.get("since") for item in board["tiles"]]
    years = [year for year in years if isinstance(year, int)] + [y for y in (era.get("from"), era.get("to")) if isinstance(y, int)]
    lines = f"{board.get('basis') or ''} {board.get('source') or ''}"
    numbers = {float(year) for year in years} | {float(n) for n in re.findall(r"\d+(?:\.\d+)?", lines)}
    if isinstance(era.get("classic_share"), float | int):
        share = round(era["classic_share"] * 100)
        numbers |= {float(share), float(100 - share)}
    decades = {year // 10 * 10 for year in years}
    if era.get("from") and era.get("to"):
        decades |= set(range(era["from"] // 10 * 10, era["to"] + 1, 10))
    return numbers, decades


def number_problems(text: str, board: dict) -> list[str]:
    numbers, decades = evidence_numbers(board)
    problems = []
    for match in NUMBER.finditer(text):
        raw = match.group(0)
        digits = re.sub(r"[^\d.]", "", raw)
        if raw.endswith("s") and digits.isdigit():
            value = int(digits)
            decade = value if value >= 100 else (1900 + value if value >= 30 else 2000 + value)
            if decade not in decades:
                problems.append(f"'{raw}' is not an era on the board")
        elif not digits.replace(".", "", 1).isdigit() or float(digits) not in numbers:
            problems.append(f"'{raw}' is not a number the evidence holds")
    for word in WORD.findall(text):
        lower = word.lower()
        if lower in NUMBER_WORDS and NUMBER_WORDS[lower] not in numbers:
            problems.append(f"'{word}' is not a number the evidence holds")
        if lower in DECADE_WORDS and not set(DECADE_WORDS[lower]) & decades:
            problems.append(f"'{word}' is not an era on the board")
    return problems


def name_problems(text: str, board: dict, also: Iterable[str] = ()) -> list[str]:
    """Capitalized words that are not on the board: a name the evidence does not hold, unless it starts a sentence as
    an ordinary word does."""
    direction = board["direction"]
    tile_names = [item["name"] for item in board["tiles"]]
    allowed = [*tile_names, *also, direction["name"], *(direction.get("cues") or []), *direction["materials"],
               *(swatch["name"] for swatch in direction["palette"])]
    tile_words = {word.lower() for name in tile_names for word in WORD.findall(name) if len(word) > 2}
    described = " ".join(text for text in (direction.get("lighting"), direction.get("type"), direction.get("music"))
                         if isinstance(text, str))
    ordinary = STARTERS | {word.lower() for phrase in [*allowed, described] for word in WORD.findall(phrase)}
    problems = []
    for sentence in SENTENCE_END.split(mask(text, allowed)):
        for index, word in enumerate(WORD.findall(sentence)):
            lower = word.lower()
            if not word[:1].isupper() or len(word) == 1 or lower in tile_words or lower in STYLE_WORDS \
                    or lower in DECADE_WORDS or lower in NUMBER_WORDS or (index == 0 and lower in ordinary):
                continue
            problems.append(f"'{word}' is not a name on the board")
    return problems


def check_statement(text: Any, board: dict, also: Iterable[str] = ()) -> list[str]:
    """What is wrong with a model's statement; empty when it holds: one or two sentences about the room (not a list of
    names), only the board's names (or the concept's and the site's own), only the board's years and numbers, and none
    of the names put in the room."""
    if not isinstance(text, str) or not text.strip():
        return ["there is no statement"]
    text = " ".join(text.split())
    also = list(also)
    masked = mask(text, [*(item["name"] for item in board["tiles"]), *also])
    problems = []
    if len(masked) > MAX_STATEMENT:
        problems.append(f"it is longer than {MAX_STATEMENT} characters")
    if len([part for part in SENTENCE_END.split(masked) if part.strip()]) > 2:
        problems.append("it is longer than two sentences")
    if len([word for word in WORD.findall(masked) if word != "x"]) < MIN_WORDS:
        problems.append("it lists names instead of saying how the room should feel")
    if STATEMENT_DECOR.search(masked):
        problems.append("it puts the names in the room (posters, portraits, photos or logos)")
    problems += name_problems(text, board, also)
    problems += number_problems(masked, board)
    return problems


def tidy(text: str) -> str:
    text = " ".join(text.split()).strip(" \"'“”")
    return text if text[-1:] in ".!?" else f"{text}."


def allowed_names(names: Iterable[Any]) -> list[str]:
    """The concept's and the site's names, and each part of a site label ('Zamalek, Cairo': 'Zamalek' and 'Cairo')."""
    return [part.strip() for name in names if isinstance(name, str) for part in (name, *name.split(",")) if part.strip()]


async def ask_again(llm: LLM, board: dict, written: str, problems: list[str], answers: AnswerCache | None) -> str | None:
    """The model's second try at the statement, told what was wrong with the first; given up after RETRY_S seconds,
    as the design sheet waits for it."""
    payload = json.dumps({**brief(board), "earlier": written, "problems": problems}, ensure_ascii=False)
    key = fingerprint("mood", MOOD_SYSTEM, payload)
    saved = answers.get("mood", key) if answers else None
    if saved:
        statement = saved.get("statement")
    else:
        try:
            reply, model = await asyncio.wait_for(llm.complete_json(MOOD_SYSTEM, payload), RETRY_S)
        except Exception:
            log.warning("The mood statement retry failed; the board's own sentence stands", exc_info=True)
            return None
        statement = reply.get("statement") if isinstance(reply, dict) else None
        if isinstance(statement, str) and answers:
            answers.put("mood", key, {"statement": statement, "model": model})
    return statement if isinstance(statement, str) else None


async def finish(llm: LLM, board: dict, written: Any, answers: AnswerCache | None = None,
                 also: Iterable[Any] = (), rules: Callable[[str], list[str]] | None = None) -> dict:
    """The board with the model's statement when it holds, else with its second try, else with the board's own.
    `also` are names a statement may use besides the board's (the concept's and the site's); `rules` adds what else a
    statement must not say (the owner's rules)."""
    if not isinstance(written, str) or not written.strip():
        return board
    names = allowed_names(also)

    def problems(text: str) -> list[str]:
        found = check_statement(text, board, names)
        return found + (rules(text) if rules and not found else [])

    wrong = problems(written)
    if not wrong:
        return {**board, "statement": tidy(written), "statement_by": "agent"}
    log.info("Mood statement rejected: %s", "; ".join(wrong))
    if llm.enabled:
        again = await ask_again(llm, board, written, wrong, answers)
        if again and not problems(again):
            return {**board, "statement": tidy(again), "statement_by": "agent"}
    return board


# ---------- Renders ----------

def names_in(text: str, names: Iterable[str]) -> list[str]:
    """The names a text mentions, compared without case or accents. A mention is written with a capital somewhere
    ('Making It', 'making It'), as names are, so ordinary words ('making it feel airy', 'power sockets') are not taken
    for a show or a brand."""
    folded = fold_keep(text)
    found = []
    for name in names:
        if not isinstance(name, str) or len(name.strip()) < 2:
            continue
        name = name.strip()
        for match in re.finditer(rf"(?<!\w){re.escape(fold_keep(name))}(?!\w)", folded):
            written = text[match.start():match.end()]
            if written == name or any(ch.isupper() for ch in written):
                found.append(name)
                break
    return found


def taste_names(run: RunState) -> set[str]:
    """Every name of a person, title or brand the run read: none of them may reach a render prompt."""
    lists = [cards for cards in run.taste.values() if isinstance(cards, list)]
    lists += [cards for fans in run.fans.values() if isinstance(fans, dict) for cards in fans.values() if isinstance(cards, list)]
    return {card["name"] for cards in lists for card in cards if isinstance(card, dict) and isinstance(card.get("name"), str)}


def scrub(text: str, names: Iterable[str], keep: Iterable[str] = ()) -> str:
    """A render prompt without the sentences that name a person, title or brand people here love, or that would show
    portraits, posters or pictures of anyone. Phrases in `keep` (the site, the sign) are not read as names."""
    names, keep = list(names), list(keep)
    kept = []
    for part in SENTENCE_END.split(text.strip()):
        plain = mask(part, keep)
        if not PORTRAITS.search(plain) and not names_in(plain, names):
            kept.append(part)
    return " ".join(kept)


def clip(text: str, limit: int) -> str:
    """At most `limit` characters, cut after a whole sentence when there is one, so the rules that follow a model's
    description survive the shortest prompt an image service takes."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > limit // 3 else f"{cut[: cut.rfind(' ')].rstrip(',;:')}."


def closed(text: str) -> str:
    """The text ending a sentence, so what is appended after it starts a new one."""
    text = text.strip()
    return text if not text or text[-1] in ".!?" else f"{text}."


def materials_beyond(direction: dict) -> list[str]:
    """The direction's materials, without those already named as colors of its palette ('pale oak' and 'pale oak')."""
    colors = {fold(swatch["name"]) for swatch in direction["palette"]}
    return [m for m in direction["materials"] if fold(m) not in colors] or list(direction["materials"])


def interior_direction(board: dict) -> str:
    """The direction as a render reads it: the era, palette, materials and light, never a name."""
    direction, label = board["direction"], board["era"].get("label")
    look = f"the {label} made new" if label else lower_first(direction["name"])
    palette = natural_list([swatch["name"] for swatch in direction["palette"]])
    return (f"Design direction: {look}, in a palette of {palette}, with {natural_list(materials_beyond(direction))}; "
            f"{lower_first(direction['lighting'])}. On the walls, only abstract art, plants and objects in these colors.")


def facade_direction(board: dict) -> str:
    """The shopfront's share of the direction: two colors of the palette, a material and the lettering."""
    direction, label = board["direction"], board["era"].get("label")
    palette = [swatch["name"] for swatch in direction["palette"]]
    era = f", the {label} made new" if label else ""
    return (f"The shopfront follows the same direction{era}: {palette[0]} and {palette[1]} with "
            f"{materials_beyond(direction)[0]}, the sign lettered in {direction['type']}.")
