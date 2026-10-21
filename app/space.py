"""What fits in the unit: the kitchen each kind of business needs, and how many guests the floor area holds.

Capacity uses the occupant load factors of the International Building Code (Table 1004.5): 15 net ft² (1.39 m²) per
guest at tables and chairs, 5 net ft² (0.46 m²) per standing guest. They are code maximums for the net guest area,
so the usable share of the unit is taken out first: kitchens typically take 15-25 % of a restaurant, and storage,
restrooms and circulation take more. The result is a planning estimate, not a floor plan.
"""
from __future__ import annotations

import re

from . import scoring

SQ_FT_M2 = 0.092903
SEATED_M2 = 15 * SQ_FT_M2
STANDING_M2 = 5 * SQ_FT_M2
# Share of the unit left for guests, by the kitchen the business needs (low and high planning assumptions).
GUEST_SHARE = {"full": (0.55, 0.65), "light": (0.65, 0.75), "none": (0.70, 0.80)}
KITCHENS = ("none", "light", "full")
KITCHEN_LABELS = {"full": "a full kitchen with extraction", "light": "a light-prep kitchen", "none": "no kitchen"}

# Food businesses that work without a cooking line and its extraction hood.
LIGHT_FOOD = re.compile(
    r"\b(cafe|café|coffee|tea|juice|smoothie|dessert|ice cream|gelato|frozen yogurt|chocolate|bubble tea|deli|"
    r"sandwich|salad|acai|açaí)\b",
    re.IGNORECASE,
)
# Places people mostly stand in.
STANDING = re.compile(r"\b(music|night ?club|club|concert|dance)\b", re.IGNORECASE)


def kitchen_need(genre: str) -> str:
    kind = scoring.genre_kind(genre)
    if kind in ("retail", "wellness"):
        return "none"
    if kind == "food" and not LIGHT_FOOD.search(genre):
        return "full"
    return "light"


def misfit(genre: str, kitchen: str) -> str | None:
    """Why this kind of business cannot run in the unit, or None when it can (or the kitchen is unknown)."""
    if kitchen not in KITCHENS:
        return None
    need = kitchen_need(genre)
    if KITCHENS.index(kitchen) >= KITCHENS.index(need):
        return None
    return f"needs {KITCHEN_LABELS[need]}; the unit has {KITCHEN_LABELS[kitchen]}"


def capacity(size_m2: float | None, genre: str) -> dict | None:
    """Guests the unit holds at most, as a range; None for shops and services or when the size is unknown."""
    if not size_m2 or scoring.genre_kind(genre) in ("retail", "wellness"):
        return None
    standing = bool(STANDING.search(genre))
    per_guest = STANDING_M2 if standing else SEATED_M2
    low_share, high_share = GUEST_SHARE[kitchen_need(genre)]
    return {
        "mode": "standing" if standing else "seated",
        "low": int(size_m2 * low_share / per_guest),
        "high": int(size_m2 * high_share / per_guest),
    }


def capacity_text(cap: dict | None) -> str | None:
    if not cap:
        return None
    count = f"{cap['low']}" if cap["low"] == cap["high"] else f"{cap['low']}–{cap['high']}"
    return f"about {count} {cap['mode']} guests at most"


def size_text(size_m2: float | None) -> str | None:
    if not size_m2:
        return None
    return f"{size_m2:.0f} m² ({size_m2 / SQ_FT_M2:,.0f} ft²)"


def fit(genre: str, size_m2: float | None, kitchen: str | None) -> dict | None:
    """How a business of this type fits the unit; None when the owner gave no unit details."""
    if not size_m2 and kitchen not in KITCHENS:
        return None
    reason = misfit(genre, kitchen) if kitchen in KITCHENS else None
    cap = capacity(size_m2, genre)
    return {"fits": reason is None, "reason": reason, "needs": kitchen_need(genre), "capacity": cap,
            "capacity_text": capacity_text(cap)}


def unit_text(size_m2: float | None, kitchen: str | None, outdoor: bool | None) -> dict | None:
    """The unit in words, for the agent and the designer."""
    if not size_m2 and kitchen not in KITCHENS and outdoor is None:
        return None
    return {
        "size": size_text(size_m2) or "unknown",
        "kitchen": KITCHEN_LABELS.get(kitchen or "", "unknown"),
        "outdoor_space": "unknown" if outdoor is None else "yes" if outdoor else "none",
    }
