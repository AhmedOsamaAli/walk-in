"""A concept's dossier: the case for one storefront business, ready to hand to a landlord, a lender or a partner.

Nothing here is computed by a model. Every number is quoted from the survey's evidence, or worked out from it, and
every section carries a basis saying where it comes from, so a reader can check it; a section the evidence cannot
support is left out, not padded. The design sheet's own words (its tagline, its interior) are kept only when they state
no number, so no figure a model wrote stands beside a measured one. Price levels stay Qloo's levels ($ to $$$$): Qloo
gives no amounts, so none are made up.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime

from .. import scoring, space
from ..catchment import WALK_M_PER_MIN
from ..geo import distance_m
from . import launch
from .concepts import (
    COMMON_NAME_WORDS,
    TOO_BROAD,
    caution,
    concept_risk,
    for_whom,
    one_liner,
    place_names,
    same_business,
    taken_name,
)
from .constraints import ALCOHOL_GENRE, DRY_BY_NATURE
from .design import CAPACITY_BASIS, sign_text
from .evidence import (
    COMPLAINT_MOVES,
    OVER,
    STRONGER,
    competitor_places,
    dollars,
    example_places,
    gap_evidence,
    gap_for,
    gap_reading,
    number,
    offer_items,
    plural,
    price_evidence,
    singular,
    storefront_favorites,
)
from .experience import BASIS as TASTE_BASIS
from .models import RunState

# The verdict on the owner's idea, as its stamp reads on the page.
VERDICT_STAMPS = {
    "strong": "Strong fit", "possible": "Possible", "weak": "Weak", "thin": "Thin data", "misfit": "Doesn't fit",
    "unknown": "Not on Qloo",
}
SECTIONS = (
    "cover", "case", "alternatives", "competition", "travel", "offer", "room", "experience", "launch", "first_90_days",
    "before_you_sign", "method",
)
NO_AMOUNTS = "Levels are Qloo's, from $ to $$$$; Qloo gives no amounts, so none are given here."
ALTERNATIVES_SHOWN = 6
# Words that say what kind of business a place is rather than which one: a 'Golden Hour Bakery' takes 'Golden Hour'.
CATEGORY_WORDS = frozenset({
    "bakery", "bakeshop", "bakehouse", "patisserie", "cafe", "coffee", "espresso", "roasters", "roastery", "tea",
    "teahouse", "bar", "pub", "tavern", "taproom", "brewery", "brewing", "winery", "wine", "lounge", "kitchen", "grill",
    "diner", "deli", "bistro", "brasserie", "eatery", "canteen", "cantina", "taqueria", "trattoria", "pizzeria", "pizza",
    "restaurant", "market", "shop", "store", "boutique", "studio", "gallery", "salon", "spa", "gym", "club", "co",
    "company", "inc", "llc", "ltd",
})
# A wildcard concept combines things locals are shown to love into a business no place nearby offers yet.
UNTESTED = ("Untested: no place like it exists nearby, so there is no direct proof of demand. It combines things locals "
            "are shown to love; test demand with a pop-up, a market stall or pre-orders before you sign.")
UNTESTED_BASIS = ("A wildcard concept: the evidence shows locals love what it combines, but no place like it nearby "
                  "measures demand for the combination.")


def build_dossier(
    run: RunState, index: int, design: dict, copy: dict | None = None, *, prepared: date | None = None,
) -> dict:
    """The dossier for concept `index` and its design sheet; `copy` is the launch kit's checked ad copy, when bought."""
    concept = concept_at(run, index)
    row = gap_for(run, concept["genre"])
    name = business_name(run, concept, design)
    level = design.get("price_level") or concept.get("price_level")
    parts = {
        "cover": cover(run, concept, design, row, name, prepared),
        "case": case(run, concept, design, row, level) if row else None,
        "alternatives": alternatives(run, concept, row),
        "competition": competition(run, row) if row else None,
        "travel": travel(run, row) if row else None,
        "offer": offer(run, design, row, level) if row else None,
        "room": room(design),
        "experience": experience(design),
        "launch": launch_section(concept, design, copy),
        "first_90_days": first_90_days(run, concept, design, row, name, level),
        "before_you_sign": before_you_sign(run, concept, design, row, level),
        "method": method(run, design),
    }
    present = {key: value for key, value in parts.items() if value}
    return {"sections": [key for key in SECTIONS if key in present], **present}


# ---------- Shared with the launch kit ----------

def concept_at(run: RunState, index: int) -> dict:
    """The concept a kit or a dossier is for. Runs that improve an existing place design no concept, so have none."""
    if not 0 <= index < len(run.concepts):
        raise IndexError(f"Run {run.id} has no concept {index}: only designed concepts (explore and open) have a kit.")
    return run.concepts[index]


def business_name(run: RunState, concept: dict, design: dict) -> str:
    """The name on the sign: the sheet's own, else the concept's, unless it is a real place's name (taken_by); then
    the category's, which no one owns."""
    places = place_names(run)
    genre = str(concept.get("genre") or "")
    generic = {word for text in (genre, singular(genre), plural(genre)) for word in scoring.topic_text(text).split()}
    for proposed in (design.get("name"), concept.get("name")):
        if isinstance(proposed, str) and proposed.strip():
            name = sign_text(proposed)
            if not taken_by(name, places, generic):
                return name
    return sign_text(scoring.genre_title(genre))


def taken_by(name: str, places: Iterable[str], generic: Iterable[str] = ()) -> str | None:
    """The real place a business name would pass for, if any: one whose whole name it contains ('Otis & Main' takes
    'Otis', as concepts.taken_name checks), or the same name give or take the words that only say what kind of business
    it is ('Golden Hour' is taken by a 'Golden Hour Bakery' or a 'Cafe Golden Hour'). A shorter name is another name
    ('Golden'), and one with no words but category words ('The Bakery', or `generic`, the concept's own) is anyone's."""
    names = {place for place in places if isinstance(place, str) and place.strip()}
    found = taken_name(name, names)
    if found:
        return found
    core = name_core(name)
    if len("".join(core)) < 3 or set(core) <= COMMON_NAME_WORDS | set(generic):
        return None
    return next((place for place in sorted(names) if name_core(place) == core), None)


def name_core(name: str) -> list[str]:
    """A name's own words, without the category words around them: 'The Golden Hour Bakery & Cafe' -> golden, hour."""
    return [word for word in scoring.topic_text(name).split() if word not in CATEGORY_WORDS and word not in ("the", "and")]


def untested(concept: dict) -> str | None:
    """The plain warning a wildcard concept carries: no place like it nearby, so nothing proves its demand."""
    return UNTESTED if concept.get("wildcard") else None


def walk_outline(run: RunState) -> list[list[float]]:
    """The walk's outline as [lat, lon] points in the order it was traced; the catchment stores (lon, lat)."""
    catchment = run.catchment
    return [[lat, lon] for lon, lat in catchment.ring] if catchment and catchment.ring else []


def slug(text: str) -> str:
    """'Tide & Table' -> 'tide-and-table', 'Café Olé!' -> 'cafe-ole'."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:48].strip("-")


def campaign(name: str, genre: str = "") -> str:
    """The utm_campaign every tracked link of a concept shares."""
    return f"{slug(name) or slug(genre) or 'walk-in'}-launch"


def claim_level(claim: dict) -> int | None:
    """The price level an 'only' claim is about: 'The only $$$ bakery…' -> 3."""
    found = re.search(r"\$+", claim.get("line") or "")
    return len(found.group(0)) if found else None


def usable_claims(concept: dict, design: dict) -> tuple[list[dict], list[str]]:
    """The launch plan's claims with ids ('only', 'new-1', 'new-2'…), and notes on any left out.

    The plan prices its 'only' claim at the concept's level; when the sheet settled on another level, the claim would
    promise a price the menu does not charge, so it is left out.
    """
    plan = design.get("launch") or {}
    sheet_level = design.get("price_level")
    raw = [c for c in plan.get("claims") or [] if isinstance(c, dict) and c.get("line") and c.get("proof")]
    kept, notes = [], []
    for claim in raw:
        level = claim_level(claim) if claim.get("kind") == "only" else None
        if level and sheet_level and level != sheet_level:
            notes.append(f'Left out "{claim["line"]}": the sheet prices the concept at {dollars(sheet_level)}, so the '
                         f"claim would promise a level the menu does not charge.")
            continue
        kept.append(claim)
    totals = Counter(c.get("kind") for c in kept)
    seen: Counter[str] = Counter()
    out = []
    for claim in kept:
        kind = str(claim.get("kind") or "claim")
        seen[kind] += 1
        out.append({"id": kind if totals[kind] == 1 else f"{kind}-{seen[kind]}", "kind": kind,
                    "line": claim["line"], "proof": claim["proof"]})
    return out, notes


def price_label(level: object) -> str | None:
    return dollars(int(level)) if isinstance(level, int | float) and not isinstance(level, bool) and 1 <= level <= 4 else None


def open_level(ladder: list[dict]) -> int | None:
    """The level at least two places locals love charge and no place inside the walk does, when the walk has priced
    places of the kind (the same reading as evidence.open_price_note)."""
    if not sum(step["inside"] for step in ladder):
        return None
    steps = [step for step in ladder if step["loved"] >= 2 and not step["inside"]]
    return max(steps, key=lambda s: (s["loved"], s["level"]))["level"] if steps else None


def evidence_date(run: RunState) -> str:
    return datetime.fromtimestamp(run.created_at, UTC).date().isoformat()


def ranked_gaps(run: RunState, row: dict | None) -> list[dict]:
    """The site's gaps by gap score, highest first (ties in the gap table's order), with `row` among them: the one order
    the verdict, the decision's rank and the alternatives table all count by."""
    rows = [r for r in run.gaps if row is None or r["genre_id"] != row["genre_id"]] + ([row] if row else [])
    return sorted(rows, key=lambda r: -r["gap_score"])


def rank_among_gaps(run: RunState, row: dict) -> tuple[int, int]:
    """Where a category ranks by gap score among the site's gaps, counted the way the verdict counts it."""
    ranked = ranked_gaps(run, row)
    return next(index for index, r in enumerate(ranked, 1) if r is row), len(ranked)


# ---------- Cover ----------

def cover(run: RunState, concept: dict, design: dict, row: dict | None, name: str, prepared: date | None) -> dict:
    site, catchment = run.site, run.catchment
    walk = launch.where(run, None)
    return {
        "concept": name,
        "genre": scoring.genre_title(concept["genre"]),
        "tagline": tagline_of(run, concept, design, row),
        "site_label": site.label,
        "lat": site.lat,
        "lon": site.lon,
        "walk_minutes": site.minutes,
        "walk_source": catchment.source if catchment else None,
        "area_km2": round(catchment.area_m2 / 1e6, 2) if catchment else None,
        "reach_m": walk["reach_m"],
        "ring": walk_outline(run),
        "neighborhoods": walk["neighborhoods"],
        "evidence_date": evidence_date(run),
        "prepared_date": (prepared or datetime.now(UTC).date()).isoformat(),
        "sources": sources(run, design),
        "basis": f"The site and the {site.minutes}-minute walk the survey measured on {evidence_date(run)}; "
                 f"neighborhoods are those Qloo gives for the places inside the walk.",
    }


def tagline_of(run: RunState, concept: dict, design: dict, row: dict | None) -> str | None:
    """The sheet's tagline, unless it states a number; then the evidence's own one-line case, whose numbers are all
    in the case below."""
    for text in (design.get("tagline"), concept.get("one_liner")):
        if isinstance(text, str) and text.strip() and not re.search(r"\d", text):
            return " ".join(text.split())
    return one_liner(row, run.site.minutes) if row else None


def sources(run: RunState, design: dict) -> list[dict]:
    out = [{"name": "Qloo Insights API", "used_for": "Places inside the walk and around it, what locals engage with and "
            "love, their taste in brands, artists, films, shows and podcasts, review keywords, price levels and hours"}]
    catchment = run.catchment
    if catchment and catchment.source == "circle":
        out.append({"name": f"A circle of {WALK_M_PER_MIN} m per minute of walking",
                    "used_for": "The walk, because street routing was unavailable"})
    elif catchment:
        out.append({"name": "Valhalla routing on OpenStreetMap data (FOSSGIS)", "used_for": "The walk, traced over the streets"})
    if design.get("capacity"):
        out.append({"name": "International Building Code, Table 1004.5", "used_for": "Capacity: occupant load factors"})
    return out


# ---------- The case ----------

WHO_BASIS = ("Neighbors inside the walk, the trips they make to places of this kind (Qloo), and Qloo's crowd tags on the "
             "places locals love.")
RISK_BASIS = "The biggest risk the measurements show, stated with its numbers."


def case(run: RunState, concept: dict, design: dict, row: dict, level: int | None) -> dict:
    """The one-page pitch: the decision, the numbers behind it, who it is for and what could sink it."""
    minutes = run.site.minutes
    numbers = [
        demand_number(row), supply_number(row, minutes), pull_number(row), price_number(run, row, design, level),
        capacity_number(run, design, row),
    ]
    out = {
        "decision": decision(run, concept, row),
        "numbers": [n for n in numbers if n],
        "who": {"text": for_whom(row, minutes), "basis": WHO_BASIS},
        "risk": {"text": concept_risk(run, row, level), "check": risk_check(run, row, level), "basis": RISK_BASIS},
        "basis": f"Qloo measurements of {plural(row['genre'])} for this site's walk and the six same-size areas around it.",
    }
    warning = caution(run, run.concepts)
    if warning:
        out["caution"] = warning
    if untested(concept):
        out["untested"] = {"text": UNTESTED, "basis": UNTESTED_BASIS}
    return out


def decision(run: RunState, concept: dict, row: dict) -> dict:
    """The verdict when this is the business the owner asked to open; otherwise where it ranks among the gaps."""
    verdict = run.verdict or {}
    title = scoring.genre_title(row["genre"])
    if verdict.get("found") and verdict.get("genre_id") == row["genre_id"]:
        return {
            "kind": "verdict", "stamp": VERDICT_STAMPS.get(verdict["level"], verdict["level"]), "level": verdict["level"],
            "reason": verdict["headline"], "rank": verdict.get("position"), "of": verdict.get("of"),
            "gap_score": verdict.get("gap_score"),
            "basis": f"You asked to open {verdict.get('query') or title}; it is ranked by gap score among every category "
                     f"measured here, and checked against the unit and your notes.",
        }
    rank, total = rank_among_gaps(run, row)
    out = {
        "kind": "gap", "stamp": row.get("reading") or gap_reading(row), "rank": rank, "of": total,
        "gap_score": row["gap_score"],
        "reason": f"{title} ranks #{rank} of the {total} categories measured here, with a gap score of {row['gap_score']} of 100.",
        "basis": "The site's gap table, ranked by gap score: demand against the areas around, supply against density and "
                 "the trips locals make.",
    }
    if verdict.get("query"):
        out["asked"] = {"business": verdict["query"], "stamp": VERDICT_STAMPS.get(verdict.get("level"), verdict.get("level")),
                        "reason": verdict.get("headline")}
    return out


def demand_number(row: dict) -> dict:
    rank, ref = row["demand_rank"], row.get("ref_rank")
    value = "outside the top 50 here" if rank >= scoring.UNRANKED else f"#{rank} here"
    if ref is not None:
        value += ", outside the top 50 around" if ref >= scoring.UNRANKED else f", #{number(ref)} in the areas around"
    return {
        "label": "Demand", "value": value, "data": {"here": rank, "around": ref},
        "basis": "Where people inside the walk rank this place type among those they engage with (Qloo; #1 is the "
                 "strongest), against its median rank in six same-size areas a few kilometres around.",
    }


def supply_number(row: dict, minutes: int) -> dict:
    nearby, expected = row["nearby_count"], row.get("expected_nearby")
    value = f"{nearby}{'+' if row.get('nearby_capped') else ''} inside the walk"
    if expected is not None:
        value += f", {'at least' if row.get('around_capped') else 'about'} {number(expected)} typical"
    return {
        "label": "Supply", "value": value, "data": {"inside": nearby, "typical": expected},
        "basis": f"Places of this kind Qloo lists inside the {minutes}-minute walk, against what a block this dense holds: "
                 f"the count in a circle twice the walk's radius, scaled to the walk's area and to this site's median "
                 f"supply across categories.",
    }


def pull_number(row: dict) -> dict | None:
    """How far locals travel for the places of this kind they love: the median trip to those outside the walk (the
    trip a place inside it would save them), or no distance at all when it is not known."""
    total, far, km = row.get("favorites_total") or 0, row.get("favorites_far") or 0, row.get("median_far_km")
    if row.get("favorites_kind") != "local" or total < 3:
        return None
    return {
        "label": "Pull",
        "value": f"{far} of {total} loved places outside the walk" + (f"; median distance {number(km)} km" if km is not None else ""),
        "data": {"outside": far, "of": total, "median_km": km},
        "basis": "Places of this kind that people inside the walk love more than the city does (Qloo)"
                 + (f", and the median straight-line distance from the site of the {far} outside the walk." if km is not None
                    else "."),
    }


def price_number(run: RunState, row: dict, design: dict, level: int | None) -> dict | None:
    if not level:
        return None
    price = row.get("price") or price_evidence(row, run.constraints)
    opened, loved = open_level(price.get("ladder") or []), price.get("loved")
    if opened == level:
        value = f"{dollars(level)}: a level locals love that no place inside the walk charges"
    elif opened:
        value = f"{dollars(level)}; the open level is {dollars(opened)}"
    else:
        value = dollars(level) + (f"; the places locals love are {dollars(loved)}" if loved and loved != level else "")
    return {
        "label": "Price position", "value": value,
        "data": {"level": level, "open": opened, "loved": loved, "inside": price.get("nearby")},
        "basis": f"{design.get('price_basis') or price['basis']} {NO_AMOUNTS}",
    }


def capacity_number(run: RunState, design: dict, row: dict) -> dict | None:
    text = design.get("capacity")
    if not text:
        return None
    fit = space.fit(row["genre"], run.site.size_m2, run.site.kitchen) or {}
    size = space.size_text(run.site.size_m2)
    return {
        "label": "Capacity", "value": text[:1].upper() + text[1:] + (f" in {size}" if size else ""),
        "data": fit.get("capacity"), "basis": design.get("capacity_basis") or CAPACITY_BASIS,
    }


def risk_check(run: RunState, row: dict, level: int | None) -> str:
    """How to test the risk concepts.concept_risk names, branch for branch, before signing."""
    loved = (row.get("price") or {}).get("loved")
    if loved and level and loved - level >= 1:
        return ("Read the menus of the places locals love (linked under Offer) and make sure the value and the speed "
                "make up for the lower price level.")
    if row.get("evidence") == "thin":
        return ("Visit the nearest places of this kind at a busy hour and count their customers: Qloo knows too few "
                "around here to judge demand.")
    if row.get("evidence") == "atypical":
        return ("Check whether the places locals love of this kind sit in hotels or malls; if most do, test demand with "
                "a pop-up before signing.")
    if (row.get("relative_supply") or 0) >= OVER and not row.get("around_capped"):
        return ("Count the customers of the places inside the walk at their busy hours: full rooms leave space for one "
                "more, half-empty ones do not.")
    if (row.get("lift") or 0) <= -STRONGER:
        return "Test demand before committing, with a pop-up, a market stall or pre-orders: locals rank it lower here."
    if row["nearby_count"] >= 8:
        return "Visit the competitors inside the walk at their busy hours and note what all of them miss: that is the opening."
    if row.get("favorites_kind") != "local":
        return ("Count passers-by at the door on a weekday and a weekend: the case rests on the ranking and the supply "
                "count, not on trips locals are known to make.")
    return ("Stand at the door for an hour at the times you plan to be busiest, on a weekday and on a weekend, and count "
            "who walks past; ask the landlord for any footfall counts the building has.")


# ---------- Alternatives ----------

def alternatives(run: RunState, concept: dict, row: dict | None) -> dict | None:
    """The site's strongest gaps beside the chosen one, by gap score as its rank counts them, and down to the chosen one
    at least: every category that scores higher is shown, with why it was not chosen."""
    if not run.gaps:
        return None
    chosen = row["genre_id"] if row else concept.get("genre_id")
    ranked = ranked_gaps(run, row)
    at = next((index for index, r in enumerate(ranked, 1) if r["genre_id"] == chosen), 0)
    score = row["gap_score"] if row else None
    items = []
    for position, r in enumerate(ranked[:max(ALTERNATIVES_SHOWN, at)], 1):
        item = {
            "genre": r["genre"], "gap_score": r["gap_score"], "reading": r.get("reading") or gap_reading(r),
            "position": position, "why": why_line(run, r), "chosen": r["genre_id"] == chosen,
        }
        if r.get("source") == "agent":
            item["tested_live"] = True
        if not item["chosen"] and score is not None and r["gap_score"] > score:
            item["why_not"] = why_not(run, concept, r)
        items.append(item)
    return {
        "items": items,
        "basis": "The site's gap table, 0 to 100, by gap score: demand against six same-size areas around, supply "
                 "against what a block this dense holds, and the trips locals make; the unit and your notes decide what "
                 "fits. Categories the agent tested live are scored on the same scale.",
    }


def why_line(run: RunState, row: dict) -> str:
    fit = row.get("fit") or {}
    if row.get("ruled_out"):
        return f"Your notes rule it out: it {row['ruled_out']}."
    if not fit.get("fits", True):
        return f"The unit cannot host it: it {fit['reason']}."
    if row.get("evidence") in ("thin", "atypical"):
        return gap_evidence(row, run.site.minutes)[-1]
    return one_liner(row, run.site.minutes)


def why_not(run: RunState, concept: dict, row: dict) -> str:
    """Why a category that scores higher than the chosen one is not the one in this dossier."""
    fit = row.get("fit") or {}
    verdict = run.verdict or {}
    if row.get("ruled_out"):
        return f"Scores higher, but your notes rule it out: it {row['ruled_out']}."
    if not fit.get("fits", True):
        return f"Scores higher, but the unit cannot host it: it {fit['reason']}."
    if row.get("evidence") == "thin":
        return "Scores higher on thin data: Qloo knows too few of them around here to judge."
    if row.get("evidence") == "atypical":
        return "Scores higher, but the ones locals love are mostly in hotels or malls."
    if scoring.genre_key(row["genre"]) in TOO_BROAD:
        return "Scores higher, but it is too broad to open as one business."
    if same_business(row["genre"], concept["genre"]):
        return f"The same business as {scoring.genre_title(concept['genre'])} under another name."
    if verdict.get("found") and verdict.get("genre_id") == concept.get("genre_id"):
        return f"Scores higher; this dossier covers {verdict.get('query') or concept['genre']}, the business you asked about."
    other = next((i for i, c in enumerate(run.concepts) if c.get("genre_id") == row["genre_id"]), None)
    if other is not None:
        return f"Scores higher; it is concept {chr(65 + other)} of this survey, with its own sheet."
    return "Scores higher and was not designed in this survey: worth a look before signing."


# ---------- Competition ----------

def competition(run: RunState, row: dict) -> dict | None:
    """Every place of the kind inside the walk, what its reviews hold against it, and the promises that answer that."""
    site = (run.site.lat, run.site.lon)
    entities = row.get("_nearby_entities")
    if entities is None:  # a row without its places: only the cards' complaint labels are known, not their counts
        rivals = [rival(card, None, True) for card in row.get("competitors") or [] if card.get("name")]
    else:
        earnest = {scoring.item_id(place) for place in competitor_places(row)}
        rivals = [
            rival(scoring.place_card(place, site), scoring.topic_groups([place])["complaint"], scoring.item_id(place) in earnest)
            for place in entities if place.get("name")
        ]
    if not rivals:
        return None
    themes: dict[str, dict] = {}
    for item in rivals:
        for complaint in item["complaints"]:
            theme = themes.setdefault(complaint["theme"], {"theme": complaint["theme"], "places": 0, "mentions": 0})
            theme["places"] += 1
            # Cards without their places carry no counts, and a sum of unknowns is unknown.
            known = theme["mentions"] is not None and complaint["mentions"] is not None
            theme["mentions"] = theme["mentions"] + complaint["mentions"] if known else None
    ordered = sorted(themes.values(), key=lambda t: (-t["places"], -(t["mentions"] or 0), t["theme"]))
    answers = [
        {**theme, "promise": launch.PROMISES[key], "move": COMPLAINT_MOVES.get(key)}
        for theme in ordered if (key := theme["theme"][:1].upper() + theme["theme"][1:]) in launch.PROMISES
    ][:3]
    minutes = run.site.minutes
    out = {
        "places": rivals,
        "count": row["nearby_count"],
        "capped": bool(row.get("nearby_capped")),
        "themes": ordered,
        "basis": f"Every place of this kind Qloo lists inside the {minutes}-minute walk, the main ones first; ratings and "
                 f"price levels from their Qloo records. Complaints are their review keywords grouped into themes; "
                 f"mentions are how often reviews use those keywords.",
    }
    if answers:
        out["your_answer"] = {
            "promises": answers,
            "basis": "The promises answer the complaints most of these places share; make one only if the service will "
                     "keep it.",
        }
    return out


def rival(card: dict, complaints: list[dict] | None, main: bool) -> dict:
    if complaints is None:
        listed = [{"theme": label[:1].upper() + label[1:], "mentions": None, "keywords": []} for label in card.get("complaints") or []]
    else:
        listed = [{"theme": g["label"], "mentions": g["mentions"], "keywords": g["keywords"][:3]} for g in complaints]
    return {
        "name": card["name"], "url": card.get("url"), "link": card.get("link"), "rating": card.get("rating"),
        "price_level": card.get("price_level"), "price": price_label(card.get("price_level")),
        "known_for": card.get("known_for") or [], "complaints": listed, "distance_m": card.get("distance_m"), "main": main,
    }


# ---------- Where customers go now ----------

def travel(run: RunState, row: dict) -> dict | None:
    """The places locals love outside the walk. Only places they love more than the city does count: the city's famous
    places are everyone's favorites and say nothing about trips."""
    if row.get("favorites_kind") != "local":
        return None
    places = []
    for card in storefront_favorites(row)[1]:
        if not card.get("name") or card.get("within_walk"):
            continue
        meters = card.get("distance_m")
        if meters is None and card.get("lat") is not None and card.get("lon") is not None:
            meters = distance_m(run.site.lat, run.site.lon, card["lat"], card["lon"])
        places.append({
            "name": card["name"], "url": card.get("url"), "link": card.get("link"),
            "km": round(meters / 1000, 1) if meters is not None else None, "price": price_label(card.get("price_level")),
            "known_for": (card.get("known_for") or [])[:3],
        })
    if not places:
        return None
    km = row.get("median_far_km")
    median = f"; the median is over the {row['favorites_far']} outside the walk" if km is not None else ""
    return {
        "places": places, "outside": row["favorites_far"], "of": row["favorites_total"], "median_km": km,
        "basis": f"Places of this kind that people inside the walk love more than the city does (Qloo), outside the walk, "
                 f"with their straight-line distance from the site{median}. Hotels and malls are left out.",
    }


# ---------- Offer and prices ----------

def offer(run: RunState, design: dict, row: dict, level: int | None) -> dict | None:
    """What to sell, from what the places locals love are known for, and what to charge, from what they charge."""
    loved = len(example_places(row))
    items = [{"item": i["item"], "places": i["places"], "of": loved, "new_here": i["new_here"]}
             for i in offer_items(row, run.constraints, limit=8)]
    known = {scoring.item_key(i["item"]): i for i in items}
    sheet = []
    for name in design.get("offer") or []:
        if not isinstance(name, str) or not name.strip():
            continue
        match = known.get(scoring.item_key(name))
        sheet.append({"item": name, "places": match["places"] if match else None,
                      "new_here": match["new_here"] if match else None})
    price = row.get("price") or price_evidence(row, run.constraints)
    ladder = [{"level": step["level"], "label": dollars(step["level"]), "loved": step["loved"], "inside": step["inside"]}
              for step in price.get("ladder") or []]
    anchors = design.get("price_anchors") if "price_anchors" in design else price.get("anchors")
    if not items and not sheet and not level and not any(s["loved"] or s["inside"] for s in ladder):
        return None
    return {
        "items": items,
        "sheet": sheet,
        "price": {
            "level": level, "label": dollars(level) or None, "basis": design.get("price_basis") or price["basis"],
            "ladder": ladder, "open_note": price.get("open_note"), "anchors": anchors or [],
        },
        "basis": f"What the {loved} {plural(row['genre'])} locals love are known for (Qloo tags and review keywords), "
                 f"each marked new when no place inside the walk is known for it; the sheet's offer is matched against "
                 f"them. {NO_AMOUNTS} Anchors link real places' own menus or websites.",
    }


# ---------- The room ----------

def room(design: dict) -> dict | None:
    """The room as the design sheet draws it. Its interior is a model's words, so any line of it that states a number
    is left out (as tagline_of leaves out a tagline): only the computed capacity estimate counts guests."""
    out: dict = {}
    interior = design.get("interior")
    if isinstance(interior, dict):
        kept = {key: value for key, value in ((key, unnumbered(value, design.get("capacity"))) for key, value in interior.items()) if value}
        if kept:
            out["interior"] = kept
    if design.get("unit"):
        out["unit"] = design["unit"]
    if design.get("capacity"):
        out["capacity"], out["capacity_basis"] = design["capacity"], design.get("capacity_basis") or CAPACITY_BASIS
    if design.get("hours"):
        out["hours"], out["hours_basis"] = design["hours"], design.get("hours_basis")
    dna = {key: value for key, value in (design.get("dna") or {}).items() if value and key != "typical_price_level"}
    if dna:
        out["dna"] = dna
    if not out:
        return None
    out["basis"] = ("The interior is the design sheet's, drawn from the design DNA: the decor, ambience, amenity and "
                    "menu tags most common among the places locals love; a line of it stating a number is left out. Hours "
                    "are those places' median hours; capacity is a building-code planning estimate.")
    return out


def unnumbered(value: object, computed: object = None) -> object:
    """A sheet's words with every line that states a number left out (None for a line, the rest of a list); the
    `computed` text, the capacity estimate, is not the model's and may stand in a line."""
    if isinstance(value, list):
        return [item for item in value if unnumbered(item, computed)]
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return None
    if isinstance(value, str):
        rest = value.replace(computed, " ") if isinstance(computed, str) and computed else value
        return value if not re.search(r"\d", rest) else None
    return value


# ---------- The experience ----------

def experience(design: dict) -> dict | None:
    plan = design.get("experience")
    if not isinstance(plan, dict):
        return None
    out: dict = {
        key: [item["name"] for item in plan[key] if isinstance(item, dict) and item.get("name")]
        for key in ("soundtrack", "screen", "talks") if plan.get(key)
    }
    if not any(out.values()):
        return None
    if plan.get("licensing"):
        out["licensing"] = plan["licensing"]
    out["basis"] = plan.get("basis") or TASTE_BASIS
    return out


# ---------- The launch ----------

def launch_section(concept: dict, design: dict, copy: dict | None) -> dict | None:
    plan = design.get("launch")
    if not isinstance(plan, dict):
        return None
    claims, notes = usable_claims(concept, design)
    out = {
        "claims": claims,
        "audience": plan.get("audience"),
        "where": plan.get("where"),
        "when": plan.get("when"),
        "channels": plan.get("channels") or [],
        "cautions": plan.get("cautions") or [],
        "basis": plan.get("basis") or "The launch plan of the design sheet.",
    }
    if notes:
        out["notes"] = notes
    if copy:
        out["copy"] = copy
    return out


# ---------- The first 90 days ----------

# The walk first, then the city, then the people who now travel elsewhere for it.
CHANNEL_STEPS = (
    ("Nextdoor", "Opening week", "Nextdoor, for the neighborhoods of the walk"),
    ("Meta or Google local ads", "Opening week", "A radius ad that covers the walk"),
    ("Spotify Ads", "Weeks 2–4", "Spotify, for awareness across the city"),
    ("Google Ads custom segment", "Weeks 2–4", "The Google segment, for people who now travel to places like it"),
)


def step(when: str, do: str, basis: str) -> dict:
    return {"when": when, "do": do, "basis": basis}


def first_90_days(
    run: RunState, concept: dict, design: dict, row: dict | None, name: str, level: int | None,
) -> dict | None:
    """Steps keyed to the evidence; a step whose evidence is missing is left out."""
    minutes = run.site.minutes
    plan = design.get("launch") if isinstance(design.get("launch"), dict) else {}
    claims, _ = usable_claims(concept, design)
    when = plan.get("when") or {}
    times = [t for t in when.get("times") or [] if t.get("label")]
    steps = []
    checked = [c for c in claims if c["kind"] in ("only", "new")]
    if checked:
        steps.append(step(
            "Before signing",
            f"Walk the {minutes}-minute walk and re-check what the ads will claim: "
            + "; ".join(f'"{c["line"]}"' for c in checked) + ".",
            f"True of the places Qloo knows as of {evidence_date(run)}; a place may have opened since. "
            + " ".join(c["proof"] for c in checked),
        ))
    busy = f", at the times the places locals love are tagged for ({', '.join(t['label'].lower() for t in times)})" if times else ""
    steps.append(step(
        "Before signing", f"Count passers-by at the door on a weekday and on a weekend{busy}.",
        "Qloo measures taste, not foot traffic: nothing in this dossier counts people walking past.",
    ))
    anchors = [a for a in design.get("price_anchors") or [] if a.get("name")]
    if level and anchors:
        steps.append(step(
            "Before opening",
            f"Set prices at {dollars(level)} after reading the menus of {scoring.natural_list([a['name'] for a in anchors])}.",
            f"{design.get('price_basis') or ''} {NO_AMOUNTS}".strip(),
        ))
    promise = next((c for c in claims if c["kind"] == "promise"), None)
    if promise:
        steps.append(step("Before opening", f"Build the service to keep the promise the ads make: {promise['line']}.",
                          promise["proof"]))
    hours = design.get("hours")
    if hours or times:
        labels = [t["label"].lower() for t in times]
        do = " ".join(part for part in (f"Open {hours}." if hours else "",
                                         f"Staff up for {scoring.natural_list(labels)}." if labels else "") if part)
        tagged = "; ".join(f"{t['label']}: {t['places']} of {t['of']}" for t in times)
        basis = " ".join(part for part in (
            f"{design.get('hours_basis') or 'Typical hours of the places locals love'}." if hours else "",
            f"Times of day are Qloo's tags on the places locals love of this kind ({tagged})." if times else "",
        ) if part)
        steps.append(step("Opening week", do, basis))
    lead = next((i for i in when.get("intents") or [] if i.get("angle")), None)
    if lead:
        steps.append(step("Opening week", lead["angle"], f"{lead['places']} of the {lead['of']} places locals love are tagged "
                                                         f"'{lead['label']}' (Qloo's visit-intent tags)."))
    channels = {c.get("channel"): c for c in plan.get("channels") or [] if isinstance(c, dict)}
    for channel, period, label in CHANNEL_STEPS:
        found = channels.get(channel)
        if found:
            steps.append(step(period, f"{label}: {scoring.inline_label(found['setting'])}", found["why"]))
    if channels:
        tag = campaign(str(concept.get("name") or name), concept["genre"])
        steps.append(step(
            "Day 30",
            f"Compare tracked visits per channel (every link carries utm_campaign={tag}) and move the budget to the "
            f"channels that bring people in.",
            "Each channel's link carries its own UTM tags; Qloo cannot see your visits.",
        ))
    if row:
        steps.append(step(
            "Day 60", "Run Walk-in again on the same pin and walk to see whether the gap closed.",
            f"Today: {supply_number(row, minutes)['value']}; gap score {row['gap_score']} of 100.",
        ))
    return {"steps": steps, "basis": "Each step answers something this survey measured, or could not measure."}


# ---------- Before you sign ----------

OUTDOOR = re.compile(r"\b(outdoor|patio|terrace|sidewalk|garden|rooftop)\b", re.IGNORECASE)
OUTDOOR_FAMILIES = (scoring.DESIGN_FAMILIES["amenities"], scoring.DESIGN_FAMILIES["setting"])


def question(ask: str, basis: str) -> dict:
    return {"ask": ask, "basis": basis}


def before_you_sign(run: RunState, concept: dict, design: dict, row: dict | None, level: int | None) -> dict:
    """Questions for the landlord from what the business needs against the unit, and the checks the risks call for."""
    site = run.site
    genre = row["genre"] if row else concept["genre"]
    kind = singular(genre)
    labels = space.KITCHEN_LABELS
    need = space.kitchen_need(genre)
    questions = []
    if need != "none":
        have = site.kitchen if site.kitchen in space.KITCHENS else None
        if have is None:
            ask = (f"Does the unit have, or allow, {labels['full']}: a hood vented above the roof line, make-up air and a "
                   f"grease trap?" if need == "full" else
                   "Can the unit take light food prep (sinks, refrigeration and power for ovens or machines) without a hood?")
        elif space.KITCHENS.index(have) < space.KITCHENS.index(need):
            ask = f"The unit has {labels[have]}: will the landlord allow {labels[need]}, and who pays for the works?"
        elif need == "full":
            ask = "Are the hood, its ducting and the grease trap in working order, and part of the lease?"
        else:
            ask = "Are the prep sinks, the refrigeration and the electrical capacity part of the lease?"
        given = f"you said the unit has {labels[have]}" if have else "the unit's kitchen was not given"
        questions.append(question(ask, f"A {kind} needs {labels[need]}; {given}."))
    licence = ALCOHOL_GENRE.search(genre) and not DRY_BY_NATURE.search(genre)
    questions.append(question(
        f"Does the lease's permitted use, and the zoning, allow a {kind}"
        + (", and can the unit get a liquor licence?" if licence else "?"),
        "Walk-in cannot see the lease, the zoning or the licensing.",
    ))
    if site.outdoor:
        questions.append(question("Is the outdoor space part of the lease, and does seating on it need a permit?",
                                  "You said the unit has outdoor space."))
    elif site.outdoor is None and row:
        places = example_places(row)
        outside = sum(
            any(OUTDOOR.search(t.get("name") or "") and (t.get("type") or "").startswith(OUTDOOR_FAMILIES)
                for t in place.get("tags") or [])
            for place in places
        )
        if outside >= 2:
            questions.append(question(
                "Does the unit come with outdoor space?",
                f"{outside} of the {len(places)} {plural(genre)} locals love are tagged for outdoor space (Qloo).",
            ))
    fit = space.fit(genre, site.size_m2, site.kitchen) if site.size_m2 else None
    cap = (fit or {}).get("capacity")
    if cap:
        questions.append(question(
            f"Does the certificate of occupancy allow {cap['high']} guests? At {space.size_text(site.size_m2)} the plan "
            f"assumes {space.capacity_text(cap)}.",
            design.get("capacity_basis") or CAPACITY_BASIS,
        ))
    elif not site.size_m2 and space.capacity(100, genre):
        questions.append(question("What is the floor area, and what occupant load does the certificate of occupancy allow?",
                                  "The unit's size was not given, so this dossier states no capacity."))
    out = {
        "questions": questions,
        "basis": f"What a {kind} needs, by Walk-in's kitchen and capacity rules, against the unit you described; then the "
                 f"main risk the evidence shows.",
    }
    checks = []
    if untested(concept):
        checks.append({"risk": "Untested: no place like it exists nearby, so there is no direct proof of demand.",
                       "check": "Test demand before you sign, with a pop-up, a market stall or pre-orders.",
                       "basis": UNTESTED_BASIS})
    if row:
        checks.append({"risk": concept_risk(run, row, level), "check": risk_check(run, row, level), "basis": RISK_BASIS})
    if checks:
        out["checks"] = checks
    return out


# ---------- Method ----------

LIMITS = (
    "Qloo measures taste and affinity, not foot traffic, rents or sales: a gap is evidence for a decision, not a forecast.",
    "Coverage is thinner in less digitally active areas, and some categories are tagged broadly.",
    "Distances to the places locals love are straight lines, not walking routes.",
    "The gap score ranks categories within this site; it is not a probability, and close scores are close calls.",
)


def method(run: RunState, design: dict) -> dict:
    """How each number is computed, how fresh the data is and where it stops."""
    minutes, catchment = run.site.minutes, run.catchment
    items = []
    if catchment and catchment.source == "circle":
        items.append({"topic": "The walk", "how": f"A circle of {minutes * WALK_M_PER_MIN} m around the pin ({WALK_M_PER_MIN} m "
                                                  f"per minute), because street routing was unavailable."})
    elif catchment:
        reach = launch.walk_reach_m(run)
        items.append({"topic": "The walk", "how": (
            f"The area reachable in {minutes} minutes on foot over the street network (Valhalla on OpenStreetMap data), "
            f"so rivers, parks and highways cut it: {catchment.area_m2 / 1e6:.2f} km², reaching {reach} m at its "
            f"farthest point."
        )})
    items += [
        {"topic": "Demand", "how": "Qloo ranks the place types people inside the walk engage with. The same ranking for six "
                                   "same-size areas a few kilometres away gives a median rank to compare with: comparing a "
                                   "neighborhood with a whole city is biased by scale."},
        {"topic": "Supply", "how": "Places of the type inside the walk, against the count in a circle twice the walk's "
                                   "radius scaled to the walk's area, then set against this site's median across categories "
                                   "so parks and rivers around do not bias every category."},
        {"topic": "Pull", "how": "Places of the type that people inside the walk love more than the city does: Qloo ranks "
                                 "places for the walk and for a 20 km circle, and the shared favorites are set aside; locals' "
                                 "favorites count as their own only when at least four remain. Distances are medians."},
        {"topic": "Gap score", "how": "0 to 100, from demand, supply and pull, each discounted when the data is thin or "
                                      "atypical."},
        {"topic": "Price levels", "how": "Qloo's levels, $ to $$$$. A concept's level follows the median level of the places "
                                         "locals love of its type, within your notes' range; levels are never turned into "
                                         "amounts."},
        {"topic": "Review themes", "how": "Qloo's review keywords grouped into themes, so one complaint written five ways "
                                          "counts once; mentions are how often reviews use the keywords, without polarity."},
        {"topic": "Hours", "how": "The median opening and closing hours, by day group, of the places locals love that list "
                                  "them; places listed as closed every day count as unknown."},
    ]
    if design.get("capacity"):
        items.append({"topic": "Capacity", "how": design.get("capacity_basis") or CAPACITY_BASIS})
    if design.get("experience") or design.get("launch"):
        items.append({"topic": "Taste and audiences", "how": TASTE_BASIS})
    return {
        "items": items,
        "freshness": f"Surveyed on {evidence_date(run)}. The server keeps Qloo's answers in a cache without an expiry date, "
                     f"so parts of this evidence may be older; Qloo has no opening dates, so a place that opened recently "
                     f"may be missing.",
        "limits": list(LIMITS) + (["Capacity is a planning estimate; the local code and the unit's certificate decide."]
                                  if design.get("capacity") else []),
        "basis": "How each number in this dossier is computed.",
    }
