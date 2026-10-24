"""Qloo's age bands: the owner's age focus (a signal that leans what is ranked toward an age group) and the bands an
audience lean is read in."""
from __future__ import annotations

# key: (label, the value of Qloo's signal.demographics.age). Qloo answers 25–29 and 30–34 alike, and 35–44 with 45–54
# as one group (checked with the hackathon key), so the focus offers the groups that rank differently.
AGES: dict[str, tuple[str, str | None]] = {
    "all": ("Everyone", None),
    "under_25": ("Under 25", "24_and_younger"),
    "25_34": ("25–34", "25_to_29,30_to_34"),
    "35_54": ("35–54", "35_to_44,45_to_54"),
    "55_plus": ("55+", "55_and_older"),
}

# Qloo's audience bands, as (key, label, youngest, oldest) for ad settings; ad platforms stop at 65+.
BANDS: tuple[tuple[str, str, int, int], ...] = (
    ("24_and_younger", "Under 25", 18, 24),
    ("25_to_29", "25–29", 25, 29),
    ("30_to_34", "30–34", 30, 34),
    ("35_to_44", "35–44", 35, 44),
    ("45_to_54", "45–54", 45, 54),
    ("55_and_older", "55+", 55, 65),
)


def age_signal(ages: str | None) -> dict:
    """The Qloo parameters that lean a ranking toward the owner's age focus; none for everyone."""
    value = AGES.get(ages or "all", AGES["all"])[1]
    return {"signal.demographics.age": value, "signal.demographics.age.weight": "high"} if value else {}


def ages_label(ages: str | None) -> str | None:
    """'25–34' for a focus; None for everyone."""
    if not ages or ages == "all" or ages not in AGES:
        return None
    return AGES[ages][0]
