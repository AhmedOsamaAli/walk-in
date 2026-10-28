"""What a concept sells: its signature items within the owner's rules, which categories are one business, and which
are too broad to open as one.
"""
from __future__ import annotations

import re

from ... import scoring
from ..evidence import offer_items
from ..models import RunState

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


# Genres too broad to open as a business ('Personal care' is salons, barbers, spas and gyms at once): they stay in the
# gap table as evidence, but a concept is always a business someone can open.
TOO_BROAD = {"personalcare", "healthandbeauty", "beauty", "wellness", "shopping", "services", "entertainment"}


def loses_signature(run: RunState, row: dict) -> bool:
    """Whether the owner's rules forbid everything the places people here love of this kind are known for."""
    return bool(offer_items(row, None, limit=1)) and not offer_items(row, run.constraints, limit=1)
