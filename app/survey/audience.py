"""Who the places people here love draw: Qloo's audience data (urn:demographics) for those places, read as leans.

Qloo answers, for each place, how much more or less each age group and each gender engages with it than everyone does
(-1 to 1, 0 is like everyone). One place's answer is noisy, so the sheet reads the median over the places people here
love of the concept's kind, and names an age group or a gender only when the lean is clear. These are leans, not head
counts: "draws 35–44-year-olds most" means they over-index, not that most customers are 35–44.
"""
from __future__ import annotations

import logging
import statistics

from .. import scoring
from ..demographics import BANDS
from ..qloo import QlooClient, QlooError
from .evidence import competitor_places, example_places, plural

log = logging.getLogger("walkin")

MIN_PLACES = 3  # fewer places say too little about an audience
MAX_PLACES = 8  # one request
CLEAR_AGE = 0.1  # an age group leans when its median is at least this (so half the places lean at least this much)
CLEAR_GENDER = 0.15
STRONG_GENDER = 0.3  # past this, an ad can target the gender; below it, the lean is worth knowing but not narrowing on
TIP_GAP = 0.25  # how much more the loved places lean toward a group than the places already here, to call it a gap
BASIS = ("Qloo's audience data for the {n} {kinds} people here love: how much more or less each age group and gender "
         "engages with them than everyone does, the median over those places. Leans, not head counts.")
GENERAL_BASIS = ("Qloo's audience data for {kinds} in general, everywhere: too few of the places people here love of "
                 "this kind have their own. How much more or less each age group and gender engages with them than "
                 "everyone does. Leans, not head counts.")


async def audience(q: QlooClient, row: dict | None, here: str = "walk") -> dict | None:
    """The audience of the places people here love of this row's kind; when too few of them have audience data, the
    category's audience in general, said as such. None when Qloo has neither or fails.

    The places already inside the area (`here`: 'walk', or '30-minute drive') are read the same way, and when the loved
    places draw a group the ones already here do not, `tip` says so: that is who a new place can win."""
    if not row:
        return None
    places = [p for p in example_places(row) if scoring.item_id(p)][:MAX_PLACES]
    try:
        if len(places) >= MIN_PLACES:
            data = await q.insights({
                "filter.type": "urn:demographics",
                "signal.interests.entities": ",".join(scoring.item_id(p) for p in places),
            })
            found = read(_rows(data), answered_names(_rows(data), places), row["genre"])
            if found:
                return {**found, **await against_inside(q, row, found, here)}
        data = await q.insights({"filter.type": "urn:demographics", "signal.interests.tags": row["genre_id"]})
    except QlooError:
        log.warning("Audience lookup failed; the sheet goes without it", exc_info=True)
        return None
    return read(_rows(data)[:1], [], row["genre"], general=True)


async def against_inside(q: QlooClient, row: dict, loved: dict, here: str = "walk") -> dict:
    """Who the places of this kind already inside the area draw (`inside`), and the positioning `tip` when the loved
    places draw a group they do not. Both None when too few have audience data or Qloo fails: the sheet then says
    nothing more."""
    places = [p for p in competitor_places(row) if scoring.item_id(p)][:MAX_PLACES]
    if len(places) < MIN_PLACES:
        return {"inside": None, "tip": None}
    try:
        data = await q.insights({
            "filter.type": "urn:demographics",
            "signal.interests.entities": ",".join(scoring.item_id(p) for p in places),
        })
    except QlooError:
        log.warning("Audience lookup for the places already here failed; the sheet goes without the tip", exc_info=True)
        return {"inside": None, "tip": None}
    there = read(_rows(data), answered_names(_rows(data), places), row["genre"])
    if not there:
        return {"inside": None, "tip": None}
    inside = {key: there[key] for key in ("ages", "gender", "gender_lean", "bands", "places")}
    return {"inside": inside, "tip": tip(loved, there, row["genre"], here, len(there["places"]))}


def answered_names(rows: list[dict], places: list[dict]) -> list[str]:
    """The names of the places Qloo has audience data for, in its order: the places a reading is read from."""
    names = {scoring.item_id(place): place.get("name") for place in places}
    return [names[r["entity_id"]] for r in rows
            if ((r.get("query") or {}).get("age")) and names.get(r.get("entity_id"))]


def tip(loved: dict, inside: dict, genre: str, here: str = "walk", n: int | None = None) -> str | None:
    """'The 6 hamburger places already inside the walk draw people 45 and over and lean toward men. The ones people here
    love draw 30–44-year-olds, leaning toward women: aim the concept at them.'

    Only for a group the places already here lean away from: they clearly draw another age group (and not this one),
    or clearly lean toward the other gender. Places that draw everyone alike serve the group too, so they give no tip."""
    first, last = _age_range(loved["bands"])
    own_first, own_last = _age_range(inside["bands"])
    age_gap = False
    if first is not None and own_first is not None and (own_first, own_last) != (first, last):
        span = range(first, last + 1)
        loved_lean = statistics.mean(loved["bands"][i]["lean"] for i in span)
        inside_lean = statistics.mean(inside["bands"][i]["lean"] for i in span)
        age_gap = inside_lean <= 0 and loved_lean - inside_lean >= TIP_GAP
    gender_gap = bool(loved.get("gender") and inside.get("gender") and inside["gender"] != loved["gender"])
    if not (age_gap or gender_gap):
        return None
    theirs, target = [], []
    if age_gap:
        theirs.append(f"draw {_who(own_first, own_last)}")
        target.append(_who(first, last))
    if gender_gap:
        theirs.append(f"lean toward {inside['gender']}")
        target.append(loved["gender"] if not age_gap else f"leaning toward {loved['gender']}")
    count = f"{n} " if n else ""
    return (f"The {count}{plural(genre)} already inside the {here} {' and '.join(theirs)}. The ones people here love "
            f"draw {', '.join(target)}: aim the concept at them.")


def _rows(data: dict | None) -> list[dict]:
    return ((data or {}).get("results") or {}).get("demographics") or []


def read(rows: list[dict], names: list[str], genre: str, general: bool = False) -> dict | None:
    """Qloo's answers as one audience: median leans, the clearest age group and gender lean, ready lines. `general`:
    one answer for the category everywhere, used when too few of the places people here love have their own."""
    ages = [((r.get("query") or {}).get("age") or {}) for r in rows]
    answered = sum(1 for a in ages if a)
    if answered < (1 if general else MIN_PLACES):
        return None
    genders = [((r.get("query") or {}).get("gender") or {}).get("female") for r in rows]
    bands = []
    for key, label, _, _ in BANDS:
        values = [a[key] for a in ages if isinstance(a.get(key), int | float)]
        bands.append({"band": label, "lean": round(statistics.median(values), 2) if values else 0.0})
    first, last = _age_range(bands)
    females = [g for g in genders if isinstance(g, int | float)]
    gender_lean = round(statistics.median(females), 2) if females else None
    gender = None
    if gender_lean is not None and abs(gender_lean) >= CLEAR_GENDER:
        gender = "women" if gender_lean > 0 else "men"
    age_min = BANDS[first][2] if first is not None else None
    age_max = BANDS[last][3] if last is not None else None
    return {
        "ages": _ages_label(first, last),
        "age_min": age_min,
        "age_max": age_max,
        "gender": gender,
        "bands": bands,
        "gender_lean": gender_lean,
        "places": names[:MAX_PLACES],
        "line": _line(answered, genre, first, last, gender, general),
        "basis": (GENERAL_BASIS if general else BASIS).format(n=answered, kinds=plural(genre)),
        "ad": ad_setting(age_min, age_max, gender, gender_lean),
        "general": general,
    }


def _age_range(bands: list[dict]) -> tuple[int | None, int | None]:
    """The clearest age group, widened to neighbouring groups that lean too; (None, None) when none leans clearly."""
    top = max(range(len(bands)), key=lambda i: bands[i]["lean"])
    if bands[top]["lean"] < CLEAR_AGE:
        return None, None
    first = last = top
    while first > 0 and bands[first - 1]["lean"] >= CLEAR_AGE:
        first -= 1
    while last < len(bands) - 1 and bands[last + 1]["lean"] >= CLEAR_AGE:
        last += 1
    return first, last


def _ages_label(first: int | None, last: int | None) -> str | None:
    if first is None or last is None or (first == 0 and last == len(BANDS) - 1):
        return None
    low, high = BANDS[first][2], BANDS[last][3]
    if last == len(BANDS) - 1:
        return f"{low}+"
    if first == 0:
        return f"Under {high + 1}"
    return f"{low}–{high}"


def _who(first: int | None, last: int | None) -> str:
    label = _ages_label(first, last)
    if label is None:
        return ""
    if label.startswith("Under"):
        return f"people {label.lower()}"
    if label.endswith("+"):
        return f"people {label[:-1]} and over"
    return f"{label}-year-olds"


def _line(n: int, genre: str, first: int | None, last: int | None, gender: str | None, general: bool = False) -> str:
    kinds = plural(genre)
    subject = f"{kinds[:1].upper()}{kinds[1:]} in general" if general else f"The {n} {kinds} people here love"
    who = _who(first, last)
    if who and gender:
        return f"{subject} draw {who} most, and lean toward {gender}."
    if who:
        return f"{subject} draw {who} most, with no clear lean between women and men."
    if gender:
        return f"{subject} draw every age group about equally, and lean toward {gender}."
    return f"{subject} draw every age group and both women and men about equally: no need to narrow an ad by either."


def ad_setting(age_min: int | None, age_max: int | None, gender: str | None, lean: float | None) -> str | None:
    """The age and gender an ad platform takes: 'Ages 30–44, women'. None when nothing leans clearly."""
    parts = []
    if age_min is not None and age_max is not None:
        parts.append(f"Ages {age_min}–{'65+' if age_max >= 65 else age_max}")
    if gender and lean is not None and abs(lean) >= STRONG_GENDER:
        parts.append(gender)
    elif gender:
        parts.append(f"all genders (the lean toward {gender} is mild)")
    return ", ".join(parts) if parts else None
