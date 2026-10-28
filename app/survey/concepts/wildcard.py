"""The wildcard after the ranked concepts, never ranked itself: a kind of place people here love hosting what they
watch, hear and follow (themed), or else two things people here love combined into a business no place inside the
area is.
"""
from __future__ import annotations

import logging
import re
from itertools import combinations

from ... import scoring
from ...catchment import area_text
from .. import themes
from ..evidence import (
    aged,
    area_noun,
    capitalized,
    count_of,
    fits,
    is_walk,
    love_evidence,
    offer_items,
    people_here,
    plural,
    singular,
    storefront_favorites,
    supply,
)
from ..experience import basis as taste_basis
from ..models import RunState
from .lines import DIGITS, FILLER, NEXT_DOOR, UNIT_CLAIM, area_figures, without_names
from .names import invent_name, place_names, placeholder_name, taken_name
from .offer import TOO_BROAD, loses_signature, ruled_items, same_business
from .owner_rules import misfit, owner_rule_lines, removed_text, rule_problems

log = logging.getLogger("walkin")


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
    """Whether a place inside the area is already both kinds of business."""
    places = [*run.block, *(first.get("_nearby_entities") or []), *(second.get("_nearby_entities") or [])]
    return any(carries(place, first) and carries(place, second) for place in places)


def loved_rows(run: RunState) -> list[tuple[dict, tuple[float, str]]]:
    """The categories people here demonstrably love (love_evidence) that are a business someone can open and that the
    unit and the owner's notes allow, with how clearly they love them and the evidence in words."""
    loved = []
    for row in run.gaps:
        if not fits(row) or scoring.genre_key(row["genre"]) in TOO_BROAD or not scoring.strict_kind(row["genre"]):
            continue
        love = love_evidence(row, run.site.ages)
        if love and not loses_signature(run, row):
            loved.append((row, love))
    return loved


def wildcard_pair(run: RunState) -> tuple[dict, str, dict, str] | None:
    """The two categories people here demonstrably love (love_evidence) that combine into the business no place inside
    the area already is, both allowed by the unit and the owner's notes: (first, its evidence, second, its evidence),
    the stronger love first. None when no pair qualifies."""
    best = None
    for (a, (score_a, why_a)), (b, (score_b, why_b)) in combinations(loved_rows(run), 2):
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


def wildcard_line(first: dict, second: dict, area: str | int, ages: str | None = None) -> str:
    """The wildcard's positioning when the model gave none: what it combines, and that the area has nothing like it."""
    loves = f"two things {people_here(ages)} love, and nothing inside the {area_text(area)} is both."
    for day, night in ((first, second), (second, first)):
        if LIGHT_FORMAT.search(day["genre"]) and scoring.genre_kind(night["genre"]) in ("bar", "venue"):
            return (f"{article(singular(day['genre'])).capitalize()} by day and {article(singular(night['genre']))} by "
                    f"night, under one roof: {loves}")
    return f"{article(singular(first['genre'])).capitalize()} and {article(singular(second['genre']))} in one: {loves}"


def wildcard_items(run: RunState, first: dict, second: dict) -> list[str]:
    """What the places people here love of both kinds are known for, within the owner's rules: the first kind's two
    leading items, and the second's when it sells food or drink."""
    items = [i["item"] for i in offer_items(first, run.constraints, limit=4)][:2]
    if scoring.genre_kind(second["genre"]) in ("food", "bar"):
        items += [i["item"] for i in offer_items(second, run.constraints, limit=4)][:2]
    seen: set[str] = set()
    return [item for item in items if not (scoring.item_key(item) in seen or seen.add(scoring.item_key(item)))][:4]


def proposed_name(run: RunState, proposal: dict, genre: str, taken: set[str]) -> str | None:
    """The model's name for a wildcard of this category, when it is a real name that no place here and no other concept
    has, and that names nothing the owner's rules forbid; None otherwise."""
    name = " ".join(str(proposal.get("name") or "").split())[:60]
    if not name or taken_name(name, place_names(run)) or placeholder_name(name, genre, run.site.label) \
            or name.lower() in {t.lower() for t in taken} or run.constraints.item_problem(name):
        return None
    return name


def proposed_line(run: RunState, proposal: dict, name: str) -> str | None:
    """The model's one-liner for a wildcard, when it claims nothing about the unit, nothing the owner's rules forbid, no
    filler and no figure but the area's own; None otherwise."""
    line = " ".join(str(proposal.get("one_liner") or "").split())
    plain = without_names(line, (name, run.site.label))
    figures = set(DIGITS.findall(area_figures(run.site)))  # the area's minutes or kilometres, and the age focus
    if not line or UNIT_CLAIM.search(line) or run.constraints.item_problem(line) or FILLER.search(plain) \
            or any(token not in figures for token in DIGITS.findall(plain)):
        return None
    return line


def wildcard_concept(run: RunState, ranked: list[dict], proposed: object = None, notes: list[str] | None = None) -> dict | None:
    """At most one concept after the ranked ones, when the evidence supports it: two things people here love, combined
    into a business no place inside the area is. It keeps the owner's rules like any concept, carries `wildcard`,
    `combines` and a plain caution, and is never ranked (no gap score). `proposed` is the model's name, one-liner and
    signature for it, kept where they pass the same checks."""
    notes = notes if notes is not None else []
    pair = wildcard_pair(run) if ranked else None
    if not pair:
        return None
    first, why_first, second, why_second = pair
    area, ages = run.site.area, run.site.ages
    proposal = proposed if isinstance(proposed, dict) else {}
    taken = {c["name"] for c in ranked}
    name = proposed_name(run, proposal, first["genre"], taken) \
        or invent_name(run, first["genre"], taken, second=second["genre"])
    line = proposed_line(run, proposal, name) or wildcard_line(first, second, area, ages)
    signature, removed = ruled_items(proposal.get("signature"), wildcard_items(run, first, second), run, fallback=4)
    if removed:
        notes.append(f"{name}: took out {removed_text(removed)}.")
    cards = [card for row in (first, second) for card in storefront_favorites(row)[1][:2] if card.get("name")]
    both = f"{article(singular(first['genre']))} and {article(singular(second['genre']))}"
    halves = [count_of(row["genre"], supply(row), row.get("nearby_capped"))
              for row in (first, second) if supply(row)]
    noun = area_noun(area)
    beat = (f"No place inside the {noun} is both; the nearest competition is the {' and the '.join(halves)} inside the "
            f"{noun}, each doing one half." if halves else f"No place inside the {noun} is either.")
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
        "for_whom": f"{'Neighbors' if is_walk(area) else 'People'}{aged(ages)} within a {area_text(area)} who love both "
                    f"{plural(first['genre'])} and {plural(second['genre'])}",
        "why_here": [
            f"{why_first[:1].upper() + why_first[1:]}.",
            f"{why_second[:1].upper() + why_second[1:]}.",
            f"No place inside the {area_text(area)} is both {both}.",
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


THEMED_CAUTION = (
    "Untested: nothing like this exists nearby, so there is no direct proof people would come; it rests on a kind of "
    "place people here love and on what they watch, hear and follow."
)


def place_kind(genre: str) -> str:
    """The kind of place a category is, in the words themes use (themes.Theme.kinds): 'cafe' for the light formats
    (coffee, tea, juice, bakery, dessert), else scoring.genre_kind's (food, bar, venue, retail or wellness)."""
    return "cafe" if LIGHT_FORMAT.search(genre) else scoring.genre_kind(genre)


def themed_base(
    theme: themes.Theme, loved: list[tuple[dict, tuple[float, str]]], ranked: list[dict],
) -> tuple[dict, str] | None:
    """The loved category that hosts a theme, with the evidence of that love: a kind of place the theme suits, one that
    no ranked concept already is before one that is, then the theme's best kind, then the clearest love. None when no
    loved category suits the theme."""
    suited = [(row, love) for row, love in loved if place_kind(row["genre"]) in theme.kinds]
    if not suited:
        return None

    def order(item: tuple[dict, tuple[float, str]]) -> tuple[bool, int, float, int]:
        row, (score, _) = item
        ranked_already = any(same_business(c["genre"], row["genre"]) for c in ranked)
        return ranked_already, theme.kinds.index(place_kind(row["genre"])), -score, -row["gap_score"]

    row, (_, why) = min(suited, key=order)
    return row, why


def themed_line(row: dict, theme: themes.Theme, area: str | int, ages: str | None = None) -> str:
    """The themed wild card's positioning when the model gave none that names the theme: the place, what it hosts, and
    that nothing inside the area is known for it."""
    return (f"{article(singular(row['genre'])).capitalize()} with {theme.activity}: {people_here(ages)} over-index on "
            f"{theme.label}, and nothing inside the {area_text(area)} is known for it.")


def themed_wildcard(run: RunState, ranked: list[dict], notes: list[str] | None = None) -> dict | None:
    """The wildcard built on a theme (themes.found): a kind of place people here love, hosting what they watch, hear
    and follow, which no place inside the area is known for. The strongest theme wins unless a place inside the area is
    already known for it, the owner's rules rule it out (nightlife for a family place, a cook-along without a kitchen)
    or no loved category the unit and the rules allow suits it; then the next. It keeps the owner's rules like any
    concept and is never ranked; who it draws (`theme.draws`) is read once the concepts are made (pipeline). Its name,
    line and signature are the theme's own: the model is shown two loves (wildcard_brief), never the theme, so what it
    proposed is for another business."""
    notes = notes if notes is not None else []
    if not ranked:
        return None
    loved, rules = loved_rows(run), run.constraints
    for theme, evidence in themes.found(run.taste, rules):
        if theme.nightlife and rules.family or rules.item_problem(theme.activity) or themes.known_inside(run, theme):
            continue
        base = themed_base(theme, loved, ranked)
        concept = themed_concept(run, ranked, theme, evidence, base, notes) if base else None
        if concept:
            return concept
    return None


def themed_concept(
    run: RunState, ranked: list[dict], theme: themes.Theme, evidence: list[tuple[str, dict]], base: tuple[dict, str],
    notes: list[str],
) -> dict | None:
    """The themed wildcard for one theme, hosted in one loved category; None, with a note, when it breaks a rule."""
    row, why = base
    area, ages = run.site.area, run.site.ages
    taken = {c["name"] for c in ranked}
    lines, named = themes.program(theme, evidence)
    cards = themes.built_on(evidence, named)
    titles = [card["name"] for card in cards]
    name = invent_name(run, row["genre"], taken, words=theme.name_words)
    line = themed_line(row, theme, area, ages)
    over = f"{people_here(ages)} over-index on {scoring.natural_list(titles[:3])} compared with same-size areas around"
    seen: set[str] = set()
    items = [capitalized(theme.activity), *(i["item"] for i in offer_items(row, run.constraints, limit=4))]
    signature = [item for item in items if not (scoring.item_key(item) in seen or seen.add(scoring.item_key(item)))][:4]
    nearby, noun = supply(row), area_noun(area)
    beat = (f"No place inside the {noun} is known for {theme.label}; the nearest competition is the "
            f"{count_of(row['genre'], nearby, row.get('nearby_capped'))} inside the {noun}." if nearby
            else f"No place inside the {noun} is known for {theme.label}, and no {singular(row['genre'])} competes there.")
    concept = {
        "name": name,
        "genre": row["genre"],
        "genre_id": row["genre_id"],
        "gap_score": None,
        "wildcard": True,
        "combines": [
            {"item": plural(row["genre"]), "genre": row["genre"], "source": f"{capitalized(why)} (Qloo)."},
            {"item": theme.label, "genre": "", "source": f"{capitalized(over)} (Qloo)."},
        ],
        "theme": {"key": theme.key, "label": theme.label, "program": lines, "built_on": cards, "draws": None,
                  "basis": taste_basis(run)},
        "caution": THEMED_CAUTION,
        "one_liner": NEXT_DOOR.sub("nearby", line),
        "for_whom": f"{'Neighbors' if is_walk(area) else 'People'}{aged(ages)} within a {area_text(area)} who love "
                    f"{theme.label}",
        "why_here": [
            f"{capitalized(why)}.",
            f"{capitalized(over)}.",
            f"No place inside the {area_text(area)} is known for {theme.label}.",
        ],
        "beat_competitors": beat,
        "signature": signature,
        "inspired_by": [card["name"] for card in storefront_favorites(row)[1][:3] if card.get("name")],
        "risk": THEMED_CAUTION,
    }
    concept["evidence"] = concept["why_here"]
    concept["owner_rules"] = owner_rule_lines(run, row, concept)
    problems = rule_problems(run, row, concept)
    if problems:
        notes.append(f"Dropped the themed wildcard {name}: {'; '.join(problems)}.")
        return None
    return concept


def with_wildcard(run: RunState, ranked: list[dict], proposed: object = None, notes: list[str] | None = None) -> list[dict]:
    """The ranked concepts, then at most one wildcard when the evidence supports one: built on a theme people here
    over-index on when one qualifies (themed_wildcard), else two loves combined (wildcard_concept)."""
    try:
        themed = themed_wildcard(run, ranked, notes)
    except Exception:  # the theme reads Qloo's genre tags: a surprise in them must never cost the owner the concepts
        log.error("The themed wildcard failed; the two-loves one stands in", exc_info=True)
        themed = None
    wildcard = themed or wildcard_concept(run, ranked, proposed, notes)
    return [*ranked, wildcard] if wildcard else ranked
