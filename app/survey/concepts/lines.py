"""What a concept says in words (its positioning, who it is for) and the checks that keep the model's lines to what
the evidence says: no figure it does not give, no filler nothing measured backs, no competitor 'next door'.
"""
from __future__ import annotations

import re

from ... import scoring, space
from ...catchment import area_text
from ...demographics import ages_label
from ..evidence import (
    aged,
    area_noun,
    crowd_of,
    gap_evidence,
    in_running_text,
    in_sentence,
    is_walk,
    people_here,
    plural,
    storefront_favorites,
    supply,
)
from ..models import Site

# A count of seats or guests, or a floor area: facts about a unit the model has never seen.
UNIT_CLAIM = re.compile(
    r"\b(\d[\d,.]*)\s*-?\s*(seats?|seater|covers?|guests?|people|m2|m²|sq\.?\s?ft|square\s(?:feet|foot|met(?:er|re)s?))\b",
    re.IGNORECASE,
)


# Competitors are measured inside the area, never placed next to the unit.
NEXT_DOOR = re.compile(r"\b(?:next door|across the (?:street|road|block))\b", re.IGNORECASE)


# Words that describe a feeling instead of the place, and that no measurement can back: a line leaning on them says
# nothing a chatbot would not. Positioning and ads say what the place is, serves or answers instead.
FILLER = re.compile(
    r"\b(?:cozy|cosy|cozier|chic|vibes?|vibey|vibrant|welcoming|inviting|curated|elevated|haven|oasis|sanctuary|"
    r"hidden gem|must[- ]visit|one[- ]of[- ]a[- ]kind|trendy|stylish|sophisticated|charming|laid[- ]back|"
    r"unforgettable|ambian[cs]e)\b",
    re.IGNORECASE,
)


DIGITS = re.compile(r"\d+(?:[.,]\d+)?")


def without_names(text: str, names) -> str:
    """The text with the given names (the business's own, the site's, and each part of a label such as 'New Haven,
    Connecticut') blanked, so 'Haven' in 'New Haven' or '5' in 'Bakery on 5th' is not read as filler or a figure."""
    parts = {part.strip() for name in names if isinstance(name, str) for part in (name, *name.split(","))}
    for name in sorted((p for p in parts if len(p) > 1), key=len, reverse=True):
        text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
    return text


def grounded_line(text: str, row: dict, site: Site, also: str = "") -> str:
    """The model's positioning, unless it states a number the evidence does not give: a capacity or floor area the
    unit does not have, or any other figure ('since 1998', 'a warm 200-seat room'); then the evidence's own line.
    `also` is the business's own name, whose figures are its own. Competitors it places next door are only known to be
    nearby."""
    text = " ".join(text.split())
    if not text or any(not unit_supports(match, row, site) for match in UNIT_CLAIM.finditer(text)) \
            or stray_numbers(without_names(text, (also, site.label)), row, site):
        return one_liner(row, site.area, site.ages)
    return NEXT_DOOR.sub("nearby", text)


def plain_number(token: str) -> str:
    """'3.30' -> '3.3', '1,200' -> '1200', so a figure matches however it is written."""
    token = token.replace(",", "")
    return token.rstrip("0").rstrip(".") if "." in token else token


def area_figures(site: Site) -> str:
    """The figures a line may take from the survey itself: the area's minutes or kilometres ('30-minute drive'), and the
    owner's age focus ('25–34'). A road distance's minutes are no figure of the area, so they are not among them."""
    return f"{site.area} {ages_label(site.ages) or ''}"


def stray_numbers(text: str, row: dict, site: Site) -> list[str]:
    """The figures in a line that neither the gap's evidence, the area's own figures nor a capacity or floor area the
    unit supports give."""
    said = " ".join([*gap_evidence(row, site.area, site.ages), one_liner(row, site.area, site.ages), area_figures(site)])
    allowed = {plain_number(token) for token in DIGITS.findall(said)}
    allowed |= {plain_number(m.group(1)) for m in UNIT_CLAIM.finditer(text) if unit_supports(m, row, site)}
    return [token for token in DIGITS.findall(text) if plain_number(token) not in allowed]


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


def neighbors(area: str | int, ages: str | None = None) -> str:
    """Who the gap is for, in the concepts' words: 'neighbors' within a walk, 'people here' within a drive or a road
    distance; either 'aged 25–34' with an age focus."""
    return f"neighbors{aged(ages)}" if is_walk(area) else people_here(ages)


def one_liner(row: dict, area: str | int, ages: str | None = None) -> str:
    """The case for the concept in one sentence, led by its strongest evidence. Trips are measured to the favorites
    outside the area (median_far_km); without that measure, no distance is given."""
    title = scoring.genre_title(row["genre"])
    places = plural(row["genre"])
    nearby, expected, km = supply(row), row.get("expected_nearby"), row.get("median_far_km")
    leakage = row.get("leakage")
    travels = row.get("favorites_kind") == "local" and leakage is not None and leakage >= 0.65 and row["favorites_far"] >= 3
    under = expected is not None and (row.get("relative_supply", 1) <= 0.75 or nearby == 0 and expected >= 1)
    walk, people, noun = is_walk(area), people_here(ages), area_noun(area)
    # Favorites outside a walk are across town; outside a drive they are farther still, and the concept only closer.
    close = "close to home" if walk else "closer to home"
    if travels and nearby == 0:
        away = f", their favorites a median {km} km away" if km else ""
        go = "cross town" if walk else "travel far"
        return f"The {places} {people} now {go} for: none inside the {area_text(area)}{away}."
    if travels and under:
        trip = f" {km} km" if km else ""
        return (f"{title} {close}: {nearby} inside the {noun} where a block this dense has about {expected:g}, and "
                f"{people} travel{trip} for their favorites.")
    if travels:
        trip = f" a median {km} km" if km else ""
        return f"{title} {close}: {people} travel{trip} for the {places} they love most."
    if under:
        return f"{title} for {'a block' if walk else 'an area'} with {nearby} where its density predicts about {expected:g}."
    ref = row.get("ref_rank")
    who = neighbors(area, ages)
    if ref is not None and ref - row["demand_rank"] >= 3:
        return f"{title} for {who} who rank it #{row['demand_rank']}, against #{round(ref)} in the areas around."
    if row["demand_rank"] <= 3:
        interest = (f"the neighborhood's #{row['demand_rank']} interest" if who == "neighbors"
                    else f"the #{row['demand_rank']} interest of {who}")
        return f"{title} for {interest}, better than the {nearby} already inside the {noun}."
    return f"{title} for {who} who rank it #{row['demand_rank']} among the place types they engage with."


# Demand ranks are a reason to open only near the top; lower down, "who rank it #21" reads as a weakness.
TOP_DEMAND = 10


def for_whom(row: dict, area: str | int, ages: str | None = None) -> str:
    """Who the evidence points to. Qloo's age and gender skews describe visitors inconsistently, so none are guessed: an
    age said here is the owner's own focus, which the rankings and favorites lean toward. Who the places people here
    love of this kind draw comes from Qloo's tags on those places. The trip is measured to the favorites outside the
    area (median_far_km), and left out when that measure is missing."""
    who = f"{'Neighbors' if is_walk(area) else 'People'}{aged(ages)} within a {area_text(area)}"
    crowd = [in_running_text(label) for label in crowd_of(row)]
    draws = f"; the {plural(row['genre'])} {people_here(ages)} love draw {scoring.natural_list(crowd)}" if crowd else ""
    if row.get("favorites_kind") == "local" and row["favorites_far"] >= 3:
        names = [c["name"] for c in storefront_favorites(row)[1] if c.get("name") and not c.get("within_walk")][:2]
        like = f" such as {scoring.natural_list(names)}" if names else ""
        km = row.get("median_far_km")
        trip = f"travel a median {km} km to" if km else "travel to"
        return f"{who} who now {trip} {plural(row['genre'])}{like}{draws}"
    if row["demand_rank"] <= TOP_DEMAND:
        rank = f"{who}, who rank {in_sentence(row['genre'])} #{row['demand_rank']} among the place types they engage with"
        return rank + draws
    return who + draws
