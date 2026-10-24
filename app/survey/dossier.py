"""A concept's dossier: the case for one storefront business, ready to hand to a landlord, a lender or a partner.

Nothing here is computed by a model. Every number is quoted from the survey's evidence, or worked out from it, and
every section carries a basis saying where it comes from, so a reader can check it; a section the evidence cannot
support is left out, not padded. The design sheet's own words (its tagline, its interior) are kept only when they state
no number, so no figure a model wrote stands beside a measured one. No price level appears: Qloo's are dollar signs with
no amounts behind them, which tell an owner nothing to charge.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime

from .. import engine, scoring, space
from ..catchment import DRIVE_M_PER_MIN, ROAD_FACTOR, WALK_M_PER_MIN
from ..geo import distance_m
from . import launch
from .concepts import (
    COMMON_NAME_WORDS,
    TOO_BROAD,
    caution,
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
    aged,
    area_noun,
    areas_text,
    competitor_places,
    count_of,
    example_places,
    gap_evidence,
    gap_for,
    gap_reading,
    is_walk,
    number,
    offer_items,
    people_here,
    plural,
    risk,
    singular,
    storefront_favorites,
)
from .experience import BASIS as TASTE_BASIS
from .experience import basis as taste_basis
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
    streets: dict | None = None,
) -> dict:
    """The dossier for concept `index` and its design sheet; `copy` is the launch kit's checked ad copy, once made, and
    `streets` the street map around the walk (app.basemap), for the cover's map."""
    concept = concept_at(run, index)
    row = gap_for(run, concept["genre"])
    name = business_name(run, concept, design)
    parts = {
        "cover": cover(run, concept, design, row, name, prepared, streets),
        "case": case(run, concept, design, row) if row else None,
        "alternatives": alternatives(run, concept, row),
        "competition": competition(run, row) if row else None,
        "travel": travel(run, row) if row else None,
        "offer": offer(run, design, row) if row else None,
        "room": room(design),
        "experience": experience(design),
        "launch": launch_section(concept, design, copy),
        "first_90_days": first_90_days(run, concept, design, row, name),
        "before_you_sign": before_you_sign(run, concept, design, row),
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


def usable_claims(concept: dict, design: dict) -> tuple[list[dict], list[str]]:
    """The launch plan's claims with ids ('only', 'new-1', 'new-2', 'closer'…), and notes on any left out.

    A sheet saved before prices were dropped may carry an 'only' claim about a price level ('The only $$ bakery…'). Its
    proof only covers places that list a price, and the ads now leave the level out, which would widen it to every
    place of the kind; so it is left out, with a note."""
    plan = design.get("launch") or {}
    raw = [c for c in plan.get("claims") or [] if isinstance(c, dict) and c.get("line") and c.get("proof")]
    kept, notes = [], []
    for claim in raw:
        if claim.get("kind") == "only" and "$" in str(claim["line"]):
            notes.append(f'Left out "{claim["line"]}": it is about a price level, which Walk-in no longer uses.')
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

def cover(
    run: RunState, concept: dict, design: dict, row: dict | None, name: str, prepared: date | None,
    streets: dict | None = None,
) -> dict:
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
        "area_label": site.area,
        "walk_source": catchment.source if catchment else None,
        "area_km2": round(catchment.area_m2 / 1e6, 2) if catchment else None,
        "reach_m": walk["reach_m"],
        "ring": walk_outline(run),
        "neighborhoods": walk["neighborhoods"],
        "map": site_map(run, row, streets),
        "evidence_date": evidence_date(run),
        "prepared_date": (prepared or datetime.now(UTC).date()).isoformat(),
        "sources": sources(run, design),
        "basis": f"The site and the {site.area} the survey measured on {evidence_date(run)}; "
                 f"neighborhoods are those Qloo gives for the places inside the {area_noun(site.area)}.",
    }


def site_map(run: RunState, row: dict | None, streets: dict | None) -> dict:
    """The cover's map of what the report recommends: the street map around the survey's area (app.basemap; None when
    OpenStreetMap did not answer), the places of the kind inside the area in the competition table's order, those the
    survey numbers carrying its numbers, the places people here love of that kind outside it lettered as 'Where
    customers go now' lists them, and the claim the two make, in one line."""
    area = area_name(run)
    basis = (f"Pins: the places of this kind Qloo lists inside the {area}; the first {NUMBERED} the survey lists carry "
             f"the numbers its map gives them, and the competition table shows them. Letters: the places of this kind "
             f"{people_here(run.site.ages)} love more than the city does, outside the {area}, at their straight-line "
             f"distance (Qloo).")
    if streets:
        basis += streets_basis(streets)
    return {
        "streets": streets,
        "pins": map_pins(run, row) if row else [],
        "trips": map_trips(run, row) if row else [],
        "caption": map_caption(run, row),
        "basis": basis,
    }


def streets_basis(streets: dict) -> str:
    """The cover map's note on its streets and water: OpenStreetMap's, read from its Overpass servers or from
    OpenFreeMap's vector tiles of it (app.vectortiles), and the date of the data."""
    as_of = str(streets.get("as_of") or "")[:10]
    via = " (OpenFreeMap's vector tiles)" if "openfreemap" in str(streets.get("source") or "") else ""
    return f" Streets and water: OpenStreetMap{via}{f', data of {as_of}' if as_of else ''}."


def area_name(run: RunState) -> str:
    """The survey's area as the maps name it, '10-minute walk', '30-minute drive', '25 km drive': the area the survey
    traced (the catchment's label), else the one the owner asked for."""
    label = getattr(run.catchment, "label", None)
    return label if isinstance(label, str) and label else run.site.area


# The places of a kind the survey numbers on its map: the first it lists (frontend map/pins.ts, LISTED).
NUMBERED = 6


def listed_numbers(row: dict) -> dict[str, int]:
    """The numbers the survey's map gives the places of a kind, by Qloo id: 1, 2, 3… for those of the first NUMBERED
    it lists (row['competitors']) that have a location."""
    numbers: dict[str, int] = {}
    count = 0
    for card in (row.get("competitors") or [])[:NUMBERED]:
        if card_location(card) is None:
            continue
        count += 1
        if card.get("id"):
            numbers[str(card["id"])] = count
    return numbers


def map_pins(run: RunState, row: dict) -> list[dict]:
    """The places of the kind inside the area with a location, in the competition table's order and no more than it
    lists (a big area can hold many). Those the survey numbers on its map keep its number ('n'), so a place has one
    number on screen and on paper; the others have none and are drawn as dots."""
    site = (run.site.lat, run.site.lon)
    numbers = listed_numbers(row)
    entities = row.get("_nearby_entities")
    if entities is None:  # as competition() does: the cards stand in for places a saved row no longer holds
        named = [card for card in row.get("competitors") or [] if card.get("name")]
        located = [(card_location(card), True, card.get("id")) for card in named]
    else:
        earnest = {scoring.item_id(place) for place in competitor_places(row)}
        named = [place for place in entities if place.get("name")]
        located = [(scoring.place_location(place), scoring.item_id(place) in earnest, scoring.item_id(place))
                   for place in named]
    listed = len((competition(run, row) or {}).get("places") or [])
    pins = []
    for place, (where, main, place_id) in list(zip(named, located, strict=True))[:listed]:
        if where is None:
            continue
        lat, lon = where
        pins.append({"n": numbers.get(str(place_id)) if place_id else None, "name": place["name"], "lat": round(lat, 5),
                     "lon": round(lon, 5), "main": main, "distance_m": round(distance_m(*site, lat, lon))})
    return pins


def card_location(card: dict) -> tuple[float, float] | None:
    lat, lon = card.get("lat"), card.get("lon")
    return (float(lat), float(lon)) if lat is not None and lon is not None else None


def map_trips(run: RunState, row: dict) -> list[dict]:
    """The places people here love of the kind outside the area, lettered in the order 'Where customers go now' lists
    them, with their straight-line distance and bearing from the site; a place without a location keeps its letter and
    is left off the map. None unless the favorites are the neighbors' own (as travel() requires)."""
    if row.get("favorites_kind") != "local":
        return []
    site = run.site
    trips = []
    listed = [card for card in storefront_favorites(row)[1] if card.get("name") and not card.get("within_walk")]
    for position, card in enumerate(listed[:26]):
        where = card_location(card)
        if where is None:
            continue
        lat, lon = where
        meters = card.get("distance_m")
        if meters is None:
            meters = distance_m(site.lat, site.lon, lat, lon)
        trips.append({"key": chr(65 + position), "name": card["name"], "lat": round(lat, 5), "lon": round(lon, 5),
                      "km": round(meters / 1000, 1), "bearing": round(bearing(site.lat, site.lon, lat, lon))})
    return trips


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """The direction from the first point to the second, in degrees clockwise from north."""
    phi1, phi2, d_lambda = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return math.degrees(math.atan2(y, x)) % 360


def map_caption(run: RunState, row: dict | None) -> str:
    """The map's claim in one line, in the case's own numbers: 'No bakery inside the 10-minute walk; people here
    travel a median 2.8 km for the 3 they love'."""
    area = area_name(run)
    if not row:
        return f"The {area} around the site"
    text = f"{count_of(row['genre'], row['nearby_count'], bool(row.get('nearby_capped')))} inside the {area}"
    km, far, total = row.get("median_far_km"), row.get("favorites_far") or 0, row.get("favorites_total") or 0
    if row.get("favorites_kind") == "local" and km is not None and far:
        text += (f"; {people_here(run.site.ages)} travel a median {number(km)} km for the {far} they love"
                 + ("" if far >= total else " outside it"))
    return text


def tagline_of(run: RunState, concept: dict, design: dict, row: dict | None) -> str | None:
    """The sheet's tagline, unless it states a number; then the evidence's own one-line case, whose numbers are all
    in the case below."""
    for text in (design.get("tagline"), concept.get("one_liner")):
        if isinstance(text, str) and text.strip() and not re.search(r"\d", text):
            return " ".join(text.split())
    return one_liner(row, run.site.area, run.site.ages) if row else None


def circle_rule(run: RunState) -> str:
    """The rule the circle is drawn by when street routing fails: '80 m per minute' of a walk, 400 m per minute of a
    drive (city traffic), 0.7 of a road distance (roads wind, so a straight line reaches less far)."""
    reach = run.site.reach
    if reach.travel == "distance":
        return f"{ROAD_FACTOR:g} times the road distance, as roads wind"
    if reach.travel == "drive":
        return f"{DRIVE_M_PER_MIN} m per minute of driving, for city traffic"
    return f"{WALK_M_PER_MIN} m per minute"


def circle_size(run: RunState) -> str:
    """The fallback circle's radius: '800 m' for a walk, as always; a drive's in km once it is that big ('12 km')."""
    radius = round(run.site.reach.fallback_radius_m)
    return f"{radius} m" if radius < 1000 or is_walk(run.site.area) else f"{radius / 1000:g} km"


def sources(run: RunState, design: dict) -> list[dict]:
    site = run.site
    noun = area_noun(site.area)
    out = [{"name": "Qloo Insights API", "used_for": f"Places inside the {noun} and around it, what locals engage with "
            "and love, their taste in brands, artists, films, shows and podcasts, review keywords and hours"}]
    catchment = run.catchment
    if catchment and catchment.source == "circle":
        rule = f"{WALK_M_PER_MIN} m per minute of walking" if is_walk(site.area) else circle_rule(run)
        out.append({"name": f"A circle of {rule}", "used_for": f"The {noun}, because street routing was unavailable"})
    elif catchment:
        # The trip supply is compared with ('the 20-minute walk'), or the circle that stands in without its outline.
        used = f"The {noun}, traced over the streets, and the {catchment.around_label} that supply is compared with"
        out.append({"name": "Valhalla routing on OpenStreetMap data (FOSSGIS)", "used_for": used})
    if design.get("capacity"):
        out.append({"name": "International Building Code, Table 1004.5", "used_for": "Capacity: occupant load factors"})
    return out


# ---------- The case ----------

WHO_BASIS = ("Neighbors inside the walk, the trips they make to places of this kind (Qloo), and Qloo's crowd tags on the "
             "places locals love.")
RISK_BASIS = "The biggest risk the measurements show, stated with its numbers."


def who_basis(run: RunState) -> str:
    """WHO_BASIS for this survey: the people inside a drive or a road distance rather than a walk's neighbors, and of
    the owner's age focus when there is one."""
    area, ages = run.site.area, run.site.ages
    if is_walk(area) and not aged(ages):
        return WHO_BASIS
    who = f"{'Neighbors' if is_walk(area) else 'People'}{aged(ages)} inside the {area_noun(area)}"
    return f"{who}, the trips they make to places of this kind (Qloo), and Qloo's crowd tags on the places they love."


def case(run: RunState, concept: dict, design: dict, row: dict) -> dict:
    """The one-page pitch: the decision, the numbers behind it, who it is for and what could sink it."""
    area, ages = run.site.area, run.site.ages
    numbers = [demand_number(row, run), supply_number(run, row), pull_number(row, area, ages),
               capacity_number(run, design, row)]
    out = {
        "decision": decision(run, concept, row),
        "numbers": [n for n in numbers if n],
        "who": {"text": for_whom(row, area, ages), "basis": who_basis(run)},
        "risk": {"text": risk(row, area, ages), "check": risk_check(row, area), "basis": RISK_BASIS},
        "basis": f"Qloo measurements of {plural(row['genre'])} for this site's {area_noun(area)} and the "
                 f"{areas_text(row)} around it.",
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


def comparison_km(run: RunState | None) -> int | None:
    """How far away the same-size comparison areas lie (engine.reference_distance), when the area is too big for 'a few
    kilometres'; None for a walk-sized survey."""
    catchment = run.catchment if run else None
    away = engine.reference_distance(catchment.radius_m) if catchment else 0
    return round(away / 1000) if away > 6000 else None


def demand_number(row: dict, run: RunState | None = None) -> dict:
    rank, ref = row["demand_rank"], row.get("ref_rank")
    value = "outside the top 50 here" if rank >= scoring.UNRANKED else f"#{rank} here"
    if ref is not None:
        value += ", outside the top 50 around" if ref >= scoring.UNRANKED else f", #{number(ref)} in the areas around"
    area, ages = (run.site.area, run.site.ages) if run else (10, None)
    km = comparison_km(run)
    return {
        "label": "Demand", "value": value, "data": {"here": rank, "around": ref},
        "basis": f"Where people{aged(ages)} inside the {area_noun(area)} rank this place type among those they engage "
                 f"with (Qloo; #1 is the strongest), against its median rank in {areas_text(row)} "
                 f"{f'about {km} km away' if km else 'a few kilometres around'}.",
    }


def around_text(run: RunState) -> str:
    """What supply is compared with, in words: the longer trip over the streets, or a circle when there is none (only
    an area that is itself a circle says that routing was unavailable)."""
    catchment = run.catchment
    noun = area_noun(run.site.area)
    if catchment and catchment.around:
        return (f"the count inside the area a {catchment.around_label} reaches over the streets "
                f"({catchment.around_area_m2 / 1e6:.2f} km², so rivers and the sea count only where a bridge crosses them)")
    if catchment and catchment.source == "circle":
        return f"the count in a circle twice the {noun}'s radius (street routing was unavailable)"
    return f"the count in a circle twice the {noun}'s radius"


def supply_number(run: RunState, row: dict) -> dict:
    area = run.site.area
    noun = area_noun(area)
    nearby, expected = row["nearby_count"], row.get("expected_nearby")
    value = f"{nearby}{'+' if row.get('nearby_capped') else ''} inside the {noun}"
    if expected is not None:
        value += f", {'at least' if row.get('around_capped') else 'about'} {number(expected)} typical"
    return {
        "label": "Supply", "value": value, "data": {"inside": nearby, "typical": expected},
        "basis": f"Places of this kind Qloo lists inside the {area}, against what a block this dense holds: "
                 f"{around_text(run)}, scaled to the {noun}'s area and to this site's median supply across categories.",
    }


def pull_number(row: dict, area: str | int = 10, ages: str | None = None) -> dict | None:
    """How far locals travel for the places of this kind they love: the median trip to those outside the area (the
    trip a place inside it would save them), or no distance at all when it is not known."""
    total, far, km = row.get("favorites_total") or 0, row.get("favorites_far") or 0, row.get("median_far_km")
    if row.get("favorites_kind") != "local" or total < 3:
        return None
    noun = area_noun(area)
    return {
        "label": "Pull",
        "value": f"{far} of {total} loved places outside the {noun}" + (f"; median distance {number(km)} km" if km is not None else ""),
        "data": {"outside": far, "of": total, "median_km": km},
        "basis": f"Places of this kind that people{aged(ages)} inside the {noun} love more than the city does (Qloo)"
                 + (f", and the median straight-line distance from the site of the {far} outside the {noun}." if km is not None
                    else "."),
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


def risk_check(row: dict, area: str | int = 10) -> str:
    """How to test the risk evidence.risk names, branch for branch, before signing."""
    noun = area_noun(area)
    if row.get("evidence") == "thin":
        return ("Visit the nearest places of this kind at a busy hour and count their customers: Qloo knows too few "
                "around here to judge demand.")
    if row.get("evidence") == "atypical":
        return ("Check whether the places locals love of this kind sit in hotels or malls; if most do, test demand with "
                "a pop-up before signing.")
    if (row.get("relative_supply") or 0) >= OVER and not row.get("around_capped"):
        return (f"Count the customers of the places inside the {noun} at their busy hours: full rooms leave space for one "
                f"more, half-empty ones do not.")
    if (row.get("lift") or 0) <= -STRONGER:
        return "Test demand before committing, with a pop-up, a market stall or pre-orders: locals rank it lower here."
    if row["nearby_count"] >= 8:
        return (f"Visit the competitors inside the {noun} at their busy hours and note what all of them miss: that is the "
                f"opening.")
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
        "basis": "The site's gap table, 0 to 100, by gap score: demand against same-size areas around, supply "
                 f"against what a block this dense holds, and the trips {people_here(run.site.ages)} make; the unit and "
                 "your notes decide what fits. Categories the agent tested live are scored on the same scale.",
    }


def why_line(run: RunState, row: dict) -> str:
    fit = row.get("fit") or {}
    if row.get("ruled_out"):
        return f"Your notes rule it out: it {row['ruled_out']}."
    if not fit.get("fits", True):
        return f"The unit cannot host it: it {fit['reason']}."
    if row.get("evidence") in ("thin", "atypical"):
        return gap_evidence(row, run.site.area, run.site.ages)[-1]
    return one_liner(row, run.site.area, run.site.ages)


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
    """Every place of the kind inside the area, what its reviews hold against it, and the promises that answer that."""
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
    out = {
        "places": rivals,
        "count": row["nearby_count"],
        "capped": bool(row.get("nearby_capped")),
        "themes": ordered,
        "basis": f"Every place of this kind Qloo lists inside the {run.site.area}, the main ones first; ratings from "
                 f"their Qloo records. Complaints are their review keywords grouped into themes; "
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
        "known_for": card.get("known_for") or [], "complaints": listed, "distance_m": card.get("distance_m"), "main": main,
    }


# ---------- Where customers go now ----------

def travel(run: RunState, row: dict) -> dict | None:
    """The places locals love outside the area. Only places they love more than the city does count: the city's famous
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
            "km": round(meters / 1000, 1) if meters is not None else None,
            "known_for": (card.get("known_for") or [])[:3],
        })
    if not places:
        return None
    km = row.get("median_far_km")
    noun = area_noun(run.site.area)
    median = f"; the median is over the {row['favorites_far']} outside the {noun}" if km is not None else ""
    return {
        "places": places, "outside": row["favorites_far"], "of": row["favorites_total"], "median_km": km,
        "basis": f"Places of this kind that people{aged(run.site.ages)} inside the {noun} love more than the city does "
                 f"(Qloo), outside the {noun}, with their straight-line distance from the site{median}. Hotels and malls "
                 f"are left out.",
    }


# ---------- Offer ----------

def offer(run: RunState, design: dict, row: dict) -> dict | None:
    """What to sell, from what the places locals love are known for."""
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
    if not items and not sheet:
        return None
    return {
        "items": items,
        "sheet": sheet,
        "basis": f"What the {loved} {plural(row['genre'])} locals love are known for (Qloo tags and review keywords), "
                 f"each marked new when no place inside the {area_noun(run.site.area)} is known for it; the sheet's offer "
                 f"is matched against them.",
    }


# ---------- The room ----------

def room(design: dict) -> dict | None:
    """The unit, what it holds and when to open: the owner's own figures, the building code's estimate and the hours the
    places locals love keep. A sheet saved before the cuts may still carry an interior or design DNA; neither is shown."""
    out: dict = {}
    if design.get("unit"):
        out["unit"] = design["unit"]
    if design.get("capacity"):
        out["capacity"], out["capacity_basis"] = design["capacity"], design.get("capacity_basis") or CAPACITY_BASIS
    if design.get("hours"):
        out["hours"], out["hours_basis"] = design["hours"], design.get("hours_basis")
    if not out:
        return None
    out["basis"] = ("The unit as you described it; capacity is a building-code planning estimate; hours are the median "
                    "hours of the places locals love of this kind.")
    return out


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

# The area first, then the city, then the people who now travel elsewhere for it; {area} is the survey's ('walk').
CHANNEL_STEPS = (
    ("Nextdoor", "Opening week", "Nextdoor, for the neighborhoods of the {area}"),
    ("Meta or Google local ads", "Opening week", "A radius ad that covers the {area}"),
    ("Spotify Ads", "Weeks 2–4", "Spotify, for awareness across the city"),
    ("Google Ads custom segment", "Weeks 2–4", "The Google segment, for people who now travel to places like it"),
)


def step(when: str, do: str, basis: str) -> dict:
    return {"when": when, "do": do, "basis": basis}


def first_90_days(run: RunState, concept: dict, design: dict, row: dict | None, name: str) -> dict | None:
    """Steps keyed to the evidence; a step whose evidence is missing is left out."""
    area = run.site.area
    noun = area_noun(area)
    plan = design.get("launch") if isinstance(design.get("launch"), dict) else {}
    claims, _ = usable_claims(concept, design)
    when = plan.get("when") or {}
    times = [t for t in when.get("times") or [] if t.get("label")]
    steps = []
    checked = [c for c in claims if c["kind"] in ("only", "new")]
    if checked:
        # A walk is walked; a drive or a road distance is too big to walk, so it is checked on maps and on the ground.
        recheck = f"Walk the {area}" if is_walk(area) else f"Check the {area} on maps and on the ground"
        steps.append(step(
            "Before signing",
            f"{recheck} and re-check what the ads will claim: "
            + "; ".join(f'"{c["line"]}"' for c in checked) + ".",
            f"True of the places Qloo knows as of {evidence_date(run)}; a place may have opened since. "
            + " ".join(c["proof"] for c in checked),
        ))
    busy = f", at the times the places locals love are tagged for ({', '.join(t['label'].lower() for t in times)})" if times else ""
    steps.append(step(
        "Before signing", f"Count passers-by at the door on a weekday and on a weekend{busy}.",
        "Qloo measures taste, not foot traffic: nothing in this dossier counts people walking past.",
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
            steps.append(step(period, f"{label.format(area=noun)}: {scoring.inline_label(found['setting'])}", found["why"]))
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
            "Day 60", f"Run Walk-in again on the same pin and {noun} to see whether the gap closed.",
            f"Today: {supply_number(run, row)['value']}; gap score {row['gap_score']} of 100.",
        ))
    return {"steps": steps, "basis": "Each step answers something this survey measured, or could not measure."}


# ---------- Before you sign ----------

OUTDOOR = re.compile(r"\b(outdoor|patio|terrace|sidewalk|garden|rooftop)\b", re.IGNORECASE)
OUTDOOR_FAMILIES = (scoring.DESIGN_FAMILIES["amenities"], scoring.DESIGN_FAMILIES["setting"])


def question(ask: str, basis: str) -> dict:
    return {"ask": ask, "basis": basis}


def before_you_sign(run: RunState, concept: dict, design: dict, row: dict | None) -> dict:
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
        checks.append({"risk": risk(row, run.site.area, run.site.ages), "check": risk_check(row, run.site.area),
                       "basis": RISK_BASIS})
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


def limits(run: RunState) -> list[str]:
    """LIMITS for this survey: beside a drive or a road distance, the straight lines are not routes by road either."""
    if is_walk(run.site.area):
        return list(LIMITS)
    return [line.replace("not walking routes", "not routes by road") for line in LIMITS]


def area_method(run: RunState) -> dict | None:
    """How the area was drawn: over the street network on foot or by car, or within a road distance; a circle by the
    travel mode's rule when street routing was unavailable."""
    site, catchment = run.site, run.catchment
    if not catchment:
        return None
    topic = f"The {area_noun(site.area)}"
    if catchment.source == "circle":
        return {"topic": topic, "how": f"A circle of {circle_size(run)} around the pin ({circle_rule(run)}), because "
                                       f"street routing was unavailable."}
    far = launch.walk_reach_m(run)
    if is_walk(site.area):
        return {"topic": topic, "how": (
            f"The area reachable in {site.minutes} minutes on foot over the street network (Valhalla on OpenStreetMap "
            f"data), so rivers, parks and highways cut it: {catchment.area_m2 / 1e6:.2f} km², reaching {far} m at its "
            f"farthest point."
        )}
    reach = site.reach
    trip = f"within {reach.km:g} km by road" if reach.travel == "distance" else f"reachable in {site.minutes} minutes by car"
    farthest = f"{far} m" if far is None or far < 1000 else f"{far / 1000:.1f} km"
    return {"topic": topic, "how": (
        f"The area {trip} over the street network (Valhalla on OpenStreetMap data), so rivers and the sea cut it where "
        f"no bridge crosses: {catchment.area_m2 / 1e6:.2f} km², reaching {farthest} at its farthest point."
    )}


def method(run: RunState, design: dict) -> dict:
    """How each number is computed, how fresh the data is and where it stops."""
    area, ages = run.site.area, run.site.ages
    noun, people = area_noun(area), f"people{aged(ages)}"
    km = comparison_km(run)
    metro = round(engine.metro_m(run.catchment) / 1000) if run.catchment else round(engine.METRO_M / 1000)
    drawn = area_method(run)
    items = [drawn] if drawn else []
    items += [
        {"topic": "Demand", "how": f"Qloo ranks the place types {people} inside the {noun} engage with. The same ranking "
                                   f"for six same-size areas {f'about {km} km' if km else 'a few kilometres'} away gives a "
                                   f"median rank to compare with: comparing a neighborhood with a whole city is biased by "
                                   f"scale. An area where Qloo lists almost no place (open water, a rail yard) is moved "
                                   f"nearer, farther or a little to the side, or left out."},
        {"topic": "Supply", "how": f"Places of the type inside the {noun}, against {around_text(run)}, scaled to the "
                                   f"{noun}'s area, then set against this site's median across categories so parks and "
                                   f"rivers around do not bias every category."},
        {"topic": "Pull", "how": f"Places of the type that {people} inside the {noun} love more than the city does: Qloo "
                                 f"ranks places for the {noun} and for a {metro} km circle, and the shared favorites are set "
                                 f"aside; locals' favorites count as their own only when at least four remain. Distances "
                                 f"are medians."},
        {"topic": "Gap score", "how": "0 to 100, from demand, supply and pull, each discounted when the data is thin or "
                                      "atypical."},
        {"topic": "Review themes", "how": "Qloo's review keywords grouped into themes, so one complaint written five ways "
                                          "counts once; mentions are how often reviews use the keywords, without polarity."},
        {"topic": "Hours", "how": "The median opening and closing hours, by day group, of the places locals love that list "
                                  "them; places listed as closed every day count as unknown."},
    ]
    if design.get("capacity"):
        items.append({"topic": "Capacity", "how": design.get("capacity_basis") or CAPACITY_BASIS})
    if design.get("experience") or design.get("launch"):
        items.append({"topic": "Taste and audiences", "how": taste_basis(run)})
    return {
        "items": items,
        "freshness": f"Surveyed on {evidence_date(run)}. The server reuses Qloo's answers for up to a week, and an older "
                     f"one only when Qloo cannot answer, so parts of this evidence may be a few days older; Qloo has no "
                     f"opening dates, so a place that opened recently may be missing.",
        "limits": limits(run) + (["Capacity is a planning estimate; the local code and the unit's certificate decide."]
                                 if design.get("capacity") else []),
        "basis": "How each number in this dossier is computed.",
    }
