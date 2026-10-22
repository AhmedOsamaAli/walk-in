"""The launch kit an owner buys for one concept: ad copy for each channel of the launch plan, a poster drawn from the
walk, tracked links and the decision dossier.

The model writes the copy; deterministic checks read every line against the plan's claims, so an ad never states a
number the evidence does not give, names a competitor or a place on the block, borrows an artist's, a show's or a
brand's name, says "only" without the proof, or reaches for a superlative. Rejected lines go back to the model once
with the reasons; whatever is still missing is written by rules from the claims themselves, so the kit always works
without a model. The poster is data for vector art (the walk's real outline), never a stock or generated picture.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

from .. import scoring
from ..answers import AnswerCache, fingerprint
from ..llm import LLM
from . import launch
from .concepts import COMMON_NAME_WORDS, place_names
from .constraints import Constraints
from .dossier import build_dossier, business_name, campaign, claim_level, concept_at, usable_claims, walk_outline
from .evidence import NATIONAL, NOT_NATIONAL, PROPER_WORDS, dollars, gap_for, offer_items, plural, singular
from .models import RunState

log = logging.getLogger("walkin")

# Each channel's fields and their limits: characters (spaces included), words, list sizes; a script is read aloud.
FORMATS: dict[str, dict[str, dict]] = {
    "spotify": {"script": {"words": 75, "spoken": True}, "companion": {"chars": 40}},
    "nextdoor": {"headline": {"chars": 60}, "body": {"chars": 600}},
    "google_search": {"headlines": {"chars": 30, "min": 8, "max": 15}, "descriptions": {"chars": 90, "min": 4, "max": 4}},
    "meta": {"primary_text": {"chars": 125}, "headline": {"chars": 40}, "description": {"chars": 30}},
    "poster": {"headline": {"chars": 40}, "subline": {"chars": 90}},
}
# The launch plan's channels, and the copy each one runs.
CHANNELS = {
    "Spotify Ads": "spotify", "Nextdoor": "nextdoor", "Google Ads custom segment": "google_search",
    "Meta or Google local ads": "meta",
}
CHANNEL_NAMES = {key: name for name, key in CHANNELS.items()} | {"poster": "Poster"}
# utm_source and utm_medium per channel, in the forms analytics tools group by default.
UTM = {
    "spotify": ("spotify", "audio"), "nextdoor": ("nextdoor", "paid_social"), "google_search": ("google", "cpc"),
    "meta": ("facebook", "paid_social"), "poster": ("poster", "qr"),
}
# Who each channel reaches, so the copy says "close by" only where it is true.
REACHES = {
    "spotify": "Listeners across the city who over-index on the area's artists and podcasts; most do not live nearby.",
    "nextdoor": "Neighbors in the neighborhoods of the walk.",
    "google_search": "People searching who browse the websites of the places locals now travel to.",
    "meta": "People inside a radius that covers the walk.",
    "poster": "People passing the door: it hangs in the window.",
}
# Price levels in words, where a voice reads the ad or a search ad would reject '$$$'.
AD_PRICE = {1: "low-priced", 2: "mid-priced", 3: "upscale", 4: "high-end"}
WORDS_PER_SECOND = 2.5

NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")
NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100, "thousand": 1000, "dozen": 12,
}
NUMBER_WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.IGNORECASE)
ONLY = re.compile(r"\bonly\b", re.IGNORECASE)
SUPERLATIVE = re.compile(
    r"#\s*1\b|\bno\.?\s*1\b|\bnumber\s+one\b|\b(?:best|cheapest|finest|greatest|tastiest|freshest|fastest|"
    r"(?:top|highest|best)[- ]rated|(?:world[- ])?famous|renowned|legendary|iconic|award[- ]winning|unbeat(?:able|en)|"
    r"unmatched|unrivall?ed|unparalleled|ultimate|world[- ]class|best[- ]in[- ]class|lowest[- ]priced|lowest prices?|"
    r"most (?:popular|loved|beloved|famous|authentic|delicious|trusted|celebrated))\b",
    re.IGNORECASE,
)
WEB = re.compile(
    r"https?://|\bwww\.|[\w.+-]+@[\w-]+\.\w|\b[a-z0-9-]+\.(?:com|net|org|co|io|us|uk|ca|shop|store|cafe|bar|menu|app)\b",
    re.IGNORECASE,
)
UNSPOKEN = re.compile(r"[$#@*/|·•_<>=~^\[\]{}]")
# Characters after which a capitalized word starts a sentence rather than naming something.
SENTENCE_END = set(".!?:;\"“”(–—-•·|")
MASK = " zzownzz "


def fold(text: str) -> str:
    """Accents and apostrophes dropped, case kept: 'Joe’s Café' -> 'Joes Cafe'."""
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return re.sub(r"['’`]", "", plain)


def numbers_in(text: str) -> list[str]:
    return NUMBER.findall(text) + [match.group(1) for match in NUMBER_WORD.finditer(text)]


def canon(token: str) -> str:
    """One form per number: 'ten' and '10', '1,000' and '1000', '2.10' and '2.1'; times of day stay as written."""
    word = NUMBER_WORDS.get(token.lower())
    if word is not None:
        return f"{word:g}"
    token = re.sub(r",(?=\d{3}(?!\d))", "", token)
    if ":" in token:
        return token
    try:
        return f"{float(token.replace(',', '.')):g}"
    except ValueError:
        return token


def phrase_pattern(phrase: str) -> re.Pattern | None:
    """A phrase however it is written: 'Tide & Table' also matches 'tide and table'."""
    words = scoring.topic_text(phrase).split()
    if not words:
        return None
    parts = [r"(?:and|&)" if word == "and" else re.escape(word) for word in words]
    return re.compile(r"(?<!\w)" + r"\W*".join(parts) + r"(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class Name:
    """A name copy must not use. A one-word name that is also a plain word ('Rise', 'Proof') only counts written as a
    name: capitalized, and not just because it starts a sentence. A match inside the business's own words ('Crumb' in
    its 'Crumb cake') is the business's; one reaching beyond them ('Joe's Bakery' around 'bakery') is the name."""

    text: str
    pattern: re.Pattern
    single: bool

    def found(self, folded: str, own: list[tuple[int, int]]) -> bool:
        for match in self.pattern.finditer(folded):
            start, end = match.span()
            if any(low <= start and end <= high for low, high in own):
                continue
            before = folded[:start].rstrip()
            named = match.group(0)[:1].isupper() and bool(before) and before[-1] not in SENTENCE_END
            if not self.single or named:
                return True
        return False


def names_of(texts: Iterable[str], generic: set[str]) -> list[Name]:
    """Names to watch for; names made only of plain category words ('The Bakery', 'Coffee Shop') say nothing."""
    out: dict[str, Name] = {}
    for text in texts:
        words = [word for word in scoring.topic_text(text).split() if word != "the"]
        pattern = phrase_pattern(" ".join(words))
        if not pattern or len("".join(words)) < 3 or set(words) <= generic:
            continue
        out.setdefault(pattern.pattern, Name(text.strip(), pattern, len(words) == 1))
    return list(out.values())


@dataclass
class Facts:
    """What the copy may say: the numbers the claims, proofs, hours, walk and name give, whether an 'only' claim exists,
    and the names it must never use. The business's own name, menu and neighborhoods are its own words: masked before
    the number, 'only' and superlative checks, and never mistaken for another business's name."""

    numbers: set[str]
    only: bool
    places: list[Name]
    audience: list[Name]
    own: list[re.Pattern]
    constraints: Constraints

    def mask(self, folded: str) -> str:
        for pattern in self.own:
            folded = pattern.sub(MASK, folded)
        return folded

    def check(self, text: str, chars: int | None = None, words: int | None = None, spoken: bool = False) -> list[str]:
        """Why a line cannot run; empty when it can."""
        reasons = []
        if chars and len(text) > chars:
            reasons.append(f"over {chars} characters ({len(text)})")
        if words and len(text.split()) > words:
            reasons.append(f"over {words} words ({len(text.split())})")
        folded = fold(text)
        spans = [match.span() for pattern in self.own for match in pattern.finditer(folded)]
        masked = self.mask(folded)
        place = next((name for name in self.places if name.found(folded, spans)), None)
        if place:
            reasons.append(f"names {place.text}, a place near the site: ads must not name other businesses")
        listened = next((name for name in self.audience if name.found(folded, spans)), None)
        if listened:
            reasons.append(f"names {listened.text}, from the audience: artists, shows, podcasts and brands are for "
                           f"targeting only")
        stray = list(dict.fromkeys(token for token in numbers_in(masked) if canon(token) not in self.numbers))
        if stray:
            reasons.append(f"states {', '.join(stray)}, a number no claim, proof, the hours or the walk gives")
        if not self.only and ONLY.search(masked):
            reasons.append('says "only" without an "only" claim')
        superlative = SUPERLATIVE.search(masked)
        if superlative:
            reasons.append(f'"{superlative.group(0)}" is a superlative nothing proves')
        if WEB.search(text):
            reasons.append("a web address or email: the tracked link carries the website")
        if spoken and UNSPOKEN.search(text):
            reasons.append("a symbol a voice cannot read")
        if not self.constraints.allows_item(masked):
            reasons.append("offers something the owner's notes rule out")
        return reasons


def facts_for(run: RunState, concept: dict, design: dict, name: str, claims: list[dict]) -> Facts:
    """The facts a concept's copy is checked against."""
    genre = concept["genre"]
    row = gap_for(run, genre)
    plan = design.get("launch") if isinstance(design.get("launch"), dict) else {}
    texts = [c["line"] for c in claims] + [c["proof"] for c in claims]
    texts += [design.get("hours") or "", name, str(concept.get("name") or "")]
    numbers = {canon(token) for text in texts for token in numbers_in(text)} | {canon(str(run.site.minutes))}
    own = [name, str(concept.get("name") or ""), scoring.genre_title(genre), singular(genre), plural(genre)]
    own += neighborhoods_of(run, design)
    own += [item for item in (concept.get("signature") or []) + (design.get("offer") or []) if isinstance(item, str)]
    own += [item["item"] for item in offer_items(row, run.constraints, limit=8)] if row else []
    patterns = [p for p in (phrase_pattern(text) for text in sorted(set(own), key=len, reverse=True)) if p]
    generic = {w for text in (*COMMON_NAME_WORDS, genre, singular(genre), plural(genre)) for w in scoring.topic_text(text).split()}
    generic |= {"and", "of", "a", "an", "new", "place", "places", "co"}
    return Facts(
        numbers=numbers,
        only=any(c["kind"] == "only" for c in claims),
        places=names_of(place_texts(run), generic),
        audience=names_of(audience_texts(run, plan), generic),
        own=patterns,
        constraints=run.constraints,
    )


def place_texts(run: RunState) -> set[str]:
    """Every place the survey saw: the block, each category's places inside the walk, the places locals love, anchors."""
    names = set(place_names(run))
    for row in run.gaps + run.explored:
        for key in ("_nearby_entities", "_favorite_entities"):
            names |= {place.get("name") for place in row.get(key) or []}
        names |= {anchor.get("name") for anchor in (row.get("price") or {}).get("anchors") or []}
    if run.place:
        names.add(run.place.get("name"))
    return {name for name in names if isinstance(name, str) and name.strip()}


def audience_texts(run: RunState, plan: dict) -> set[str]:
    """Artists, podcasts, films, shows and brands the area or a category's fans over-index on: targeting, not creative."""
    names: set = set()
    for cards in run.taste.values():
        if isinstance(cards, list):
            names |= {card.get("name") for card in cards if isinstance(card, dict)}
    for fans in run.fans.values():
        for key in ("brands", "artists"):
            names |= {card.get("name") for card in fans.get(key) or [] if isinstance(card, dict)}
    audience = plan.get("audience") or {}
    for key in ("artists", "podcasts", "screen", "brands", "shared"):
        names |= {name for name in audience.get(key) or [] if isinstance(name, str)}
    return {name for name in names if isinstance(name, str) and name.strip()}


def limits(spec: dict) -> dict:
    return {key: spec[key] for key in ("chars", "words", "spoken") if key in spec}


# ---------- Copy written by rules ----------

Candidate = tuple[str, tuple[str, ...]]

DAY_NAMES = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday",
             "Sun": "Sunday"}
# Lines true of any new business on the walk, so a channel's copy is complete even when the evidence says little.
SAFE_HEADLINES = ("New on the block", "A short walk away", "Come say hello", "Walk in and say hello",
                  "Made for the neighborhood", "Your new neighborhood spot", "Steps from home")
SAFE_DESCRIPTIONS = ("New on the block. Walk in and say hello.", "Made for the neighborhood, a short walk from home.",
                     "Steps from home. Come in and say hello.")


@dataclass
class Brief:
    """What the rules write from: the business, where it is, its hours and the claims it may make."""

    name: str
    kind: str
    title: str
    hood: str | None
    minutes: int
    hours: str | None
    claims: list[dict]

    def claim(self, kind: str) -> dict | None:
        return next((c for c in self.claims if c["kind"] == kind), None)

    @property
    def named(self) -> bool:
        """Whether the name says more than the category: 'Golden Hour' does, a rules-made 'Seafood' does not."""
        return scoring.topic_text(self.name) not in {scoring.topic_text(self.title), scoring.topic_text(self.kind)}

    def intro(self, where: str = "") -> str:
        """'Golden Hour is a new bakery in Holly', or 'A new seafood place in Holly' when the name is the category."""
        return f"{self.name} is a new {self.kind}{where}." if self.named else f"A new {self.kind}{where}."


def item_of(claim: dict) -> str:
    """The item a 'new' claim is about: 'Kouign amann, which no bakery…' -> 'Kouign amann'."""
    return claim["line"].split(", which", 1)[0].strip()


def mid_sentence(item: str) -> str:
    """'Kouign amann' as it reads inside a sentence; 'Neapolitan pizza' and 'BLT' keep their capitals."""
    first = item.split()[0] if item.split() else ""
    proper = bool(NATIONAL.match(first)) and first not in NOT_NATIONAL or first in PROPER_WORDS or len(first) > 1 and first.isupper()
    return item if proper else item[:1].lower() + item[1:]


def sentence(text: str) -> str:
    text = " ".join(text.split()).rstrip(".")
    return text[:1].upper() + text[1:] + "."


def hours_text(hours: str, spoken: bool = False) -> str:
    """'Mon–Thu 11 am–10 pm · Sun noon–6 pm' for a line of copy, or as a voice says it."""
    if not spoken:
        return hours.replace(" · ", ", ")
    text = hours.replace(" · ", "; ").replace("–", " to ")
    return re.sub(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", lambda m: DAY_NAMES[m.group(1)], text)


def claim_sentences(brief: Brief, worded: bool = False, prose: bool = False, skip: tuple[str, ...] = ()) -> list[Candidate]:
    """Each claim as a sentence; `worded` says the price level in words, for a voice or a search ad, and `prose` makes
    the 'only' claim a full sentence for running text."""
    out = []
    for claim in brief.claims:
        kind = claim["kind"]
        if kind in skip:
            continue
        level = claim_level(claim) if kind == "only" else None
        if kind == "only":
            text = claim["line"]
            if worded and level in AD_PRICE:
                text = re.sub(r"\$+", AD_PRICE[level], text, count=1)
            if prose:
                text = f"It is {text[:1].lower()}{text[1:]}"
        elif kind == "new":
            text = f"Come for the {mid_sentence(item_of(claim))}, which no {brief.kind} within a {brief.minutes}-minute walk is known for"
        else:
            text = claim["line"]
        out.append((sentence(text), (claim["id"],)))
    return out


def pick(candidates: Iterable[Candidate], facts: Facts, spec: dict) -> Candidate | None:
    """The first candidate that passes every check."""
    for text, ids in candidates:
        text = " ".join(text.split())
        if text and not facts.check(text, **limits(spec)):
            return text, ids
    return None


def pick_all(candidates: Iterable[Candidate], facts: Facts, spec: dict) -> list[Candidate]:
    """Every distinct candidate that passes, up to the field's most."""
    out: list[Candidate] = []
    seen: set[str] = set()
    for text, ids in candidates:
        text = " ".join(text.split())
        if text and text.casefold() not in seen and not facts.check(text, **limits(spec)):
            seen.add(text.casefold())
            out.append((text, ids))
    return out[: spec["max"]]


def compose(parts: Iterable[Candidate], facts: Facts, spec: dict) -> Candidate:
    """Sentences joined while the whole stays within the limits; a sentence that fails a check is left out."""
    text, ids = "", ()
    for part, used in parts:
        joined = f"{text} {part}".strip()
        if not facts.check(part, spoken=spec.get("spoken", False)) and not facts.check(joined, **limits(spec)):
            text, ids = joined, ids + used
    return text, ids


def piece(fields: dict[str, Candidate | list[Candidate] | None]) -> dict:
    """A rules piece: each field's text and the claims the piece uses."""
    out: dict = {}
    ids: set[str] = set()
    for field, value in fields.items():
        if isinstance(value, list):
            out[field] = [text for text, _ in value]
            ids |= {claim for _, used in value for claim in used}
        elif value and value[0]:
            out[field] = value[0]
            ids |= set(value[1])
    return {"fields": out, "claims": ids}


def rules_spotify(b: Brief, facts: Facts) -> dict:
    spec = FORMATS["spotify"]
    where = f" in {b.hood}" if b.hood else ""
    # The city hears it, so 'without crossing town' is left to the local channels.
    parts = [(b.intro(where), ()), *claim_sentences(b, worded=True, prose=True, skip=("closer",))]
    if b.hours:
        parts.append((f"Open {hours_text(b.hours, spoken=True)}.", ()))
    closing = f"{b.name}{f', {b.hood}' if b.hood else ''}. " if b.named else ""
    parts.append((f"{closing}Walk in and say hello.", ()))
    companion = [(f"{b.name}, {b.hood}", ())] if b.hood and b.named else []
    companion += [(f"New {b.kind} in {b.hood}", ())] if b.hood else []
    companion += [(b.name, ())] if b.named else []
    companion += [(f"A new {b.kind}", ()), ("New on the block", ())]
    return piece({"script": compose(parts, facts, spec["script"]), "companion": pick(companion, facts, spec["companion"])})


def rules_nextdoor(b: Brief, facts: Facts) -> dict:
    spec = FORMATS["nextdoor"]
    only = b.claim("only")
    headlines = [(only["line"], (only["id"],))] if only else []
    headlines += [(f"{b.name}: a new {b.kind} close by", ())] if b.named else []
    headlines += [(f"A new {b.kind} close by", ()), ("New on the block", ())]
    where = f" in {b.hood}" if b.hood else ""
    hello = f"{b.name} is a new {b.kind}{where}, close by." if b.named else f"there is a new {b.kind}{where}, close by."
    parts = [(f"Hi neighbors! {hello[:1].upper() + hello[1:]}", ()), *claim_sentences(b, prose=True)]
    if b.hours:
        parts.append((f"Open {hours_text(b.hours)}.", ()))
    parts.append(("Come say hello.", ()))
    return piece({"headline": pick(headlines, facts, spec["headline"]), "body": compose(parts, facts, spec["body"])})


def rules_google(b: Brief, facts: Facts) -> dict:
    spec, m = FORMATS["google_search"], b.minutes
    where = f" in {b.hood}" if b.hood else ""
    headlines: list[Candidate] = [(b.name, ())]
    if b.hood:
        headlines += [(f"New {b.kind} in {b.hood}", ()), (f"{b.title} in {b.hood}", ())]
    headlines += [(c["line"], (c["id"],)) for c in b.claims if c["kind"] in ("closer", "promise")]
    headlines += [(item_of(c), (c["id"],)) for c in b.claims if c["kind"] == "new"]
    headlines += [(f"A new {b.kind} near you", ()), (f"Within a {m}-minute walk", ())]
    headlines += [(f"Open {part}", ()) for part in (b.hours or "").split(" · ") if part]
    headlines += [(f"{m} minutes on foot", ()), *[(text, ()) for text in SAFE_HEADLINES]]
    descriptions = claim_sentences(b, worded=True)
    if b.hours:
        descriptions.append((f"Open {hours_text(b.hours)}.", ()))
    descriptions += [(b.intro(where), ())] if b.named else []
    descriptions += [(f"A new {b.kind}{where}. Walk in and say hello.", ()), (f"Within a {m}-minute walk. Come say hello.", ())]
    descriptions += [(text, ()) for text in SAFE_DESCRIPTIONS]
    return piece({"headlines": pick_all(headlines, facts, spec["headlines"]),
                  "descriptions": pick_all(descriptions, facts, spec["descriptions"])})


def rules_meta(b: Brief, facts: Facts) -> dict:
    spec = FORMATS["meta"]
    intro = b.intro(" close by")
    primary = [(f"{intro} {text}", ids) for text, ids in claim_sentences(b, prose=True)]
    primary += [(intro, ()), ("New on the block. Come say hello.", ())]
    headline = [(b.name, ())] if b.named else []
    headline += [(f"New {b.kind} in {b.hood}", ())] if b.hood else []
    headline += [(f"A new {b.kind} close by", ()), ("New on the block", ())]
    description = [(c["line"], (c["id"],)) for c in b.claims if c["kind"] in ("promise", "closer")]
    description += [("A short walk away", ()), ("New on the block", ())]
    return piece({"primary_text": pick(primary, facts, spec["primary_text"]),
                  "headline": pick(headline, facts, spec["headline"]),
                  "description": pick(description, facts, spec["description"])})


def rules_poster(b: Brief, facts: Facts) -> dict:
    spec = FORMATS["poster"]
    headlines = [(c["line"], (c["id"],)) for c in b.claims if c["kind"] in ("only", "closer", "promise")]
    headlines += [(f"A new {b.kind} on the block", ()), ("New on the block", ())]
    headline = pick(headlines, facts, spec["headline"])
    used = set(headline[1]) if headline else set()
    sublines = [(text, ids) for text, ids in claim_sentences(b) if not used & set(ids)]
    if b.hours:
        sublines.append((f"Open {hours_text(b.hours)}.", ()))
    sublines.append(("A short walk from home. Walk in and say hello.", ()))
    return piece({"headline": headline, "subline": pick(sublines, facts, spec["subline"])})


RULES = {"spotify": rules_spotify, "nextdoor": rules_nextdoor, "google_search": rules_google, "meta": rules_meta,
         "poster": rules_poster}


# ---------- Copy written by the model ----------

KIT_SYSTEM = """You write the launch ads for a new storefront business. The owner runs them under their own name, so every
line must be true today and provable from the claims you are given.
Rules for every line:
- Claim only what the claims say: rephrase a claim if you like, never stretch it. Without claims, say what the
  business is, where it is, when it is open and what is on its menu.
- Use no number that is not in the claims, their proofs, the hours, the walk minutes or the business name.
- Never name another business, nor any artist, podcast, show or brand: platforms reject other businesses' names,
  and naming an artist or a brand implies an endorsement the owner does not have. The neighborhoods given are fine.
- Write "only" only when a claim of kind "only" is given.
- No superlatives nothing proves (best, #1, cheapest, famous, award-winning, top-rated, world-class).
- No web addresses, phone numbers, discounts or prices in money: price levels are $ to $$$$, never amounts.
- Keep every field within its limit; characters include spaces.
Each channel says who it reaches: say "close by" or "on your block" only where it reaches neighbors. A script is read
aloud: no symbols, price levels in words.
For each channel, list in "claims" the ids of the claims its lines use.
Return JSON with exactly the channels asked: {"<channel>": {"<field>": ..., "claims": [ids]}}; list fields are arrays
of strings."""
KIT_VERSION = fingerprint(KIT_SYSTEM, FORMATS)
RULES_SOURCE = -1


def describe(spec: dict) -> str:
    """A field's limits in words, for the model."""
    parts = []
    if "min" in spec:
        parts.append(f"exactly {spec['min']} lines" if spec["min"] == spec["max"] else f"{spec['min']} to {spec['max']} lines")
    if "chars" in spec:
        parts.append(f"at most {spec['chars']} characters{' each' if 'min' in spec else ''}")
    if "words" in spec:
        parts.append(f"at most {spec['words']} words, about 30 seconds read aloud")
    if spec.get("spoken"):
        parts.append("no symbols")
    return ", ".join(parts)


def neighborhoods_of(run: RunState, design: dict) -> list[str]:
    plan = design.get("launch") if isinstance(design.get("launch"), dict) else {}
    return (plan.get("where") or {}).get("neighborhoods") or launch.where(run, None)["neighborhoods"]


def model_brief(run: RunState, concept: dict, design: dict, name: str, claims: list[dict], keys: list[str], facts: Facts) -> dict:
    """What the model writes from: the business, the claims with their proofs, the voice, and each channel's format."""
    plan = design.get("launch") if isinstance(design.get("launch"), dict) else {}
    when = plan.get("when") or {}
    tagline = design.get("tagline")
    tagline = " ".join(tagline.split()) if isinstance(tagline, str) and tagline.strip() else None
    menu = [item for item in (design.get("offer") or []) + (concept.get("signature") or []) if isinstance(item, str)]
    level = design.get("price_level") or concept.get("price_level")
    return {
        "business": {
            "name": name, "kind": singular(concept["genre"]), "price_level": dollars(level) or None,
            "menu": list(dict.fromkeys(menu))[:6],
            "tagline": tagline if tagline and not facts.check(tagline, chars=90) else None,
        },
        "where": {"neighborhoods": neighborhoods_of(run, design), "walk_minutes": run.site.minutes},
        "hours": design.get("hours"),
        "claims": claims,
        "voice": {
            "crowd": [share["label"] for share in (plan.get("audience") or {}).get("crowd") or []],
            "busy_times": [share["label"] for share in when.get("times") or []],
            "lead_with": [share["angle"] for share in when.get("intents") or [] if share.get("angle")][:1],
        },
        "channels": {
            key: {"reaches": REACHES[key], "fields": {field: describe(spec) for field, spec in FORMATS[key].items()}}
            for key in keys
        },
    }


async def ask(llm: LLM, answers: AnswerCache | None, user: str) -> tuple[dict, str | None]:
    """One answer from the model, replayed from the cache while the evidence and the prompt are unchanged."""
    key = fingerprint("kit", KIT_VERSION, user)
    saved = answers.get("kit", key) if answers else None
    if saved and isinstance(saved.get("copy"), dict):
        return copy.deepcopy(saved["copy"]), saved.get("model")
    data, model = await llm.complete_json(KIT_SYSTEM, user)
    if data and answers:
        answers.put("kit", key, {"copy": data, "model": model})
    return (copy.deepcopy(data) if isinstance(data, dict) else {}), model


def check_answer(answer: dict, keys: list[str], facts: Facts, ids: set[str]) -> tuple[dict, list[dict], list[str]]:
    """The answer's lines that pass every check, per channel; the lines rejected and why; and what is still missing."""
    pieces: dict = {}
    rejected: list[dict] = []
    problems: list[str] = []
    for key in keys:
        raw = answer.get(key) if isinstance(answer.get(key), dict) else {}
        fields: dict = {}
        for field, spec in FORMATS[key].items():
            value = raw.get(field)
            many = "min" in spec
            texts = (value if isinstance(value, list) else []) if many else [value]
            kept: list[str] = []
            refused = False
            for text in texts:
                if not isinstance(text, str) or not text.strip():
                    continue
                text = " ".join(text.split())
                reasons = facts.check(text, **limits(spec))
                if reasons:
                    refused = True
                    rejected.append({"channel": key, "field": field, "text": text, "reasons": reasons})
                    problems.append(f'{key}.{field} "{text}": {"; ".join(reasons)}')
                elif text.casefold() not in {k.casefold() for k in kept}:
                    kept.append(text)
            if many:
                fields[field] = kept[: spec["max"]]
                if len(kept) < spec["min"]:
                    problems.append(f"{key}.{field}: {len(kept)} usable lines, {spec['min']} needed")
            elif kept:
                fields[field] = kept[0]
            elif not refused:
                problems.append(f"{key}.{field}: missing")
        listed = raw.get("claims") if isinstance(raw.get("claims"), list) else []
        pieces[key] = {"fields": fields, "claims": {c for c in listed if isinstance(c, str) and c in ids}}
    return pieces, rejected, problems


def retry_prompt(brief: str, answer: dict, problems: list[str]) -> str:
    previous = json.dumps(answer, ensure_ascii=False)[:6000]
    return (f"{brief}\n\nYour previous answer:\n{previous}\n\nIt broke these rules. Write the whole JSON again, keep what "
            "was right and fix every point:\n- " + "\n- ".join(problems))


async def write_copy(
    llm: LLM | None, answers: AnswerCache | None, brief: str, keys: list[str], facts: Facts, claims: list[dict],
) -> tuple[list[tuple[dict, str | None]], list[dict]]:
    """The model's checked attempts (a second one only when the first broke a rule) and every line rejected."""
    attempts: list[tuple[dict, str | None]] = []
    rejected: list[dict] = []
    if llm is None or not getattr(llm, "enabled", False):
        return attempts, rejected
    ids = {claim["id"] for claim in claims}
    user = brief
    for attempt in (1, 2):
        try:
            answer, model = await ask(llm, answers, user)
        except Exception:  # an outage must not cost the owner the kit
            log.warning("Launch kit copy: the model failed; the rules write what is missing", exc_info=True)
            break
        pieces, dropped, problems = check_answer(answer, keys, facts, ids)
        attempts.append((pieces, model))
        rejected += [{**item, "attempt": attempt} for item in dropped]
        if not problems:
            break
        user = retry_prompt(brief, answer, problems)
    return attempts, rejected


def detect(texts: list[str], claims: list[dict]) -> set[str]:
    """The claims a piece's words lean on, whatever the model listed: 'only' said, a new item named, a line quoted."""
    said = " ".join(fold(text).lower() for text in texts)
    found = set()
    for claim in claims:
        if claim["kind"] == "only":
            hit = bool(ONLY.search(said))
        else:
            phrase = fold(item_of(claim) if claim["kind"] == "new" else claim["line"]).lower().rstrip(".")
            hit = bool(phrase) and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", said) is not None
        if hit:
            found.add(claim["id"])
    return found


def merge(
    keys: list[str], attempts: list[tuple[dict, str | None]], rules: dict[str, dict], claims: list[dict],
) -> tuple[dict, int | None]:
    """Each field from the latest attempt that got it right, else from the rules; lists short of their minimum are
    topped up from the rules. Returns the copy and the latest attempt any of it came from."""
    out: dict = {}
    latest: int | None = None
    for key in keys:
        fields: dict = {}
        sources: set[int] = set()
        for field, spec in FORMATS[key].items():
            tried = [(index, attempts[index][0].get(key, {}).get("fields", {}).get(field)) for index in reversed(range(len(attempts)))]
            if "min" in spec:
                lines: list[str] = []
                for source, texts in [*tried, (RULES_SOURCE, rules[key]["fields"].get(field))]:
                    # The rules fill a list the model left empty, and only top up one it started.
                    cap = spec["max"] if source != RULES_SOURCE or not lines else spec["min"]
                    for text in texts or []:
                        if len(lines) < cap and text.casefold() not in {line.casefold() for line in lines}:
                            lines.append(text)
                            sources.add(source)
                fields[field] = lines
            else:
                source, text = next(((index, text) for index, text in tried if text), (RULES_SOURCE, None))
                fields[field] = text or rules[key]["fields"].get(field) or ""
                sources.add(source)
        used = {source for source in sources if source != RULES_SOURCE}
        ids = {claim for index in used for claim in attempts[index][0].get(key, {}).get("claims", set())}
        ids |= detect([text for value in fields.values() for text in (value if isinstance(value, list) else [value])], claims)
        piece_out = {"channel": CHANNEL_NAMES[key], **fields, "claims": [c["id"] for c in claims if c["id"] in ids],
                     "source": "rules" if not used else "agent" if RULES_SOURCE not in sources else "mixed"}
        if key == "spotify":
            words = len(fields["script"].split())
            piece_out["words"], piece_out["seconds"] = words, round(words / WORDS_PER_SECOND)
        out[key] = piece_out
        if used:
            latest = max(used | ({latest} if latest is not None else set()))
    return out, latest


# ---------- The kit ----------

def channel_keys(design: dict) -> list[str]:
    """The copy to write: one piece per channel of the launch plan, and the poster."""
    plan = design.get("launch") if isinstance(design.get("launch"), dict) else {}
    present = {CHANNELS.get(c.get("channel")) for c in plan.get("channels") or [] if isinstance(c, dict)}
    return [key for key in FORMATS if key in present or key == "poster"]


def make_poster(run: RunState, design: dict, name: str, piece: dict | None, claims: list[dict], facts: Facts) -> dict:
    """What the poster says and the shapes it is drawn from: the walk's outline, the door, the neighborhoods."""
    tagline = design.get("tagline")
    tagline = " ".join(tagline.split()) if isinstance(tagline, str) and tagline.strip() else None
    if tagline and facts.check(tagline, chars=90):
        tagline = None
    used = set((piece or {}).get("claims") or [])
    lead = next((c for c in claims if c["id"] in used), None) or (claims[0] if claims else None)
    return {
        "name": name,
        "tagline": tagline,
        "headline": (piece or {}).get("headline"),
        "subline": (piece or {}).get("subline"),
        "claim": {key: lead[key] for key in ("kind", "line", "proof")} if lead else None,
        "hours": design.get("hours"),
        "minutes": run.site.minutes,
        "ring": walk_outline(run),
        "site": [run.site.lat, run.site.lon],
        "neighborhoods": neighborhoods_of(run, design),
    }


def make_links(keys: list[str], name: str, genre: str) -> list[dict]:
    """UTM tags per channel; the page adds the owner's website in front of the query."""
    tag = campaign(name, genre)
    out = []
    for key in keys:
        source, medium = UTM[key]
        params = {"utm_source": source, "utm_medium": medium, "utm_campaign": tag}
        out.append({"key": key, "channel": CHANNEL_NAMES[key], **params, "query": urlencode(params)})
    return out


async def build_kit(
    llm: LLM | None, run: RunState, index: int, design: dict, answers: AnswerCache | None = None,
) -> dict:
    """The launch kit for concept `index` and its design sheet: checked ad copy per channel, the poster, tracked links
    and the dossier. Works without a model: the rules then write every line."""
    concept = concept_at(run, index)
    genre = concept["genre"]
    name = business_name(run, concept, design)
    claims, notes = usable_claims(concept, design)
    keys = channel_keys(design)
    facts = facts_for(run, concept, design, name, claims)
    hoods = neighborhoods_of(run, design)
    brief = Brief(name, singular(genre), scoring.genre_title(genre), hoods[0] if hoods else None, run.site.minutes,
                  design.get("hours"), claims)
    rules = {key: RULES[key](brief, facts) for key in keys}
    payload = json.dumps(model_brief(run, concept, design, name, claims, keys, facts), ensure_ascii=False)
    attempts, rejected = await write_copy(llm, answers, payload, keys, facts, claims)
    ads, latest = merge(keys, attempts, rules, claims)
    return {
        "concept": {"index": index, "name": name, "genre": genre},
        "claims": claims,
        "copy": ads,
        "poster": make_poster(run, design, name, ads.get("poster"), claims, facts),
        "links": make_links(keys, str(concept.get("name") or name), genre),
        "dossier": build_dossier(run, index, design, ads),
        "rejected": rejected,
        "notes": notes,
        "mode": "agent" if latest is not None else "rules",
        "model": attempts[latest][1] if latest is not None else None,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
