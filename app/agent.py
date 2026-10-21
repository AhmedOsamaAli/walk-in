"""Runs the Blank Space agent for a site: gather evidence, find gaps, propose and design concepts."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from . import engine, scoring
from .answers import AnswerCache, fingerprint
from .catchment import Catchment, CatchmentService
from .images import Images
from .llm import LLM, LLMUnavailable
from .qloo import QlooClient, QlooError

log = logging.getLogger("blankspace")

Emit = Callable[[str, dict], Awaitable[None]]

PRICE_WORDS = {1: "$", 2: "$$", 3: "$$$", 4: "$$$$"}


@dataclass
class Site:
    lat: float
    lon: float
    label: str
    focus: str = "any"
    notes: str = ""
    minutes: int = 10


@dataclass
class RunState:
    id: str
    site: Site
    catchment: Catchment | None = None
    block: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    genres: list[dict] = field(default_factory=list)
    cues: list[str] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    explored: list[dict] = field(default_factory=list)  # genres the agent tested live, scored like the table
    fans: dict[str, dict] = field(default_factory=dict)  # genre id -> what local fans of that genre also love
    taste: dict = field(default_factory=dict)
    demographics: dict | None = None
    concepts: list[dict] = field(default_factory=list)
    designs: dict[int, dict] = field(default_factory=dict)
    renders: dict[tuple[int, str], asyncio.Future] = field(default_factory=dict)  # (concept, shot) -> render
    queued: set[tuple[int, str]] = field(default_factory=set)  # shots whose render is still waiting in a free queue
    created_at: float = field(default_factory=time.time)


class RunStore:
    def __init__(self, capacity: int = 100) -> None:
        self._runs: OrderedDict[str, RunState] = OrderedDict()
        self._capacity = capacity

    def add(self, run: RunState) -> None:
        self._runs[run.id] = run
        while len(self._runs) > self._capacity:
            self._runs.popitem(last=False)

    def get(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)


def public_gap(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def describe_age(demographics: dict | None) -> str | None:
    if not demographics or not demographics.get("age"):
        return None
    labels = {
        "24_and_younger": "under 25", "25_to_29": "25-29", "30_to_34": "30-34",
        "35_to_44": "35-44", "45_to_54": "45-54", "55_and_older": "55+",
    }
    leaning = sorted(demographics["age"].items(), key=lambda kv: -kv[1])
    over = [labels.get(bucket, bucket) for bucket, value in leaning if value > 0.05][:2]
    return f"skews {' and '.join(over)}" if over else "no strong age skew"


def evidence_brief(run: RunState) -> dict:
    """Compact evidence pack handed to the LLM."""
    s = run.summary
    walk = run.catchment
    return {
        "site": {"label": run.site.label, "focus": run.site.focus, "owner_notes": run.site.notes or None},
        "walk_catchment": {
            "minutes": run.site.minutes,
            "shape": walk.source if walk else "circle",
            "area_km2": round(walk.area_m2 / 1e6, 2) if walk else None,
        },
        "block_inside_the_walk": {
            "places_scanned": s.get("place_count"),
            "most_common_genres": s.get("top_genres", [])[:8],
            "average_rating": s.get("avg_rating"),
            "price_levels": s.get("price_levels"),
            "what_reviews_praise": [k for k, _ in s.get("praise", [])[:8]],
            "what_reviews_complain_about": [k for k, _ in s.get("complaints", [])[:6]],
            "rising_places": [name for name, _ in s.get("rising", [])[:4]],
            "fading_places": [name for name, _ in s.get("fading", [])[:4]],
        },
        "gap_table": [gap_summary(g) for g in run.gaps],
        "taste_cues": run.cues,
        "brands_this_area_over_indexes_on": [b["name"] for b in run.taste.get("distinctive_brands", [])],
        "artists_this_area_over_indexes_on": [a["name"] for a in run.taste.get("distinctive_artists", [])],
        "most_popular_brands_here": [b["name"] for b in run.taste.get("brands", [])[:10]],
        "crowd": describe_age(run.demographics),
    }


def gap_summary(g: dict) -> dict:
    """One gap row as the agent sees it: comparisons are stated in words, so they cannot be misread."""
    if g["favorites_kind"] == "local" and g["favorites_total"]:
        travel = (
            f"{g['favorites_far']} of the {g['favorites_total']} places locals love more than the city does are outside "
            f"the walk; median distance {g['median_favorite_km']} km"
        )
    else:
        travel = "no evidence: locals' favorites of this type are just the city's famous places"
    return {
        "genre": g["genre"],
        "locals_rank_here": g["demand_rank"] if g["demand_rank"] < scoring.UNRANKED else "outside their top 50",
        "median_rank_in_6_same_size_areas_around": g["ref_rank"],
        "demand_compared_with_areas_around": demand_comparison(g),
        "places_within_walk": f"{g['nearby_count']}{'+' if g['nearby_capped'] else ''}",
        "typical_for_a_block_this_dense": g["expected_nearby"],
        "relative_supply": g["relative_supply"],
        "do_locals_travel_for_it": travel,
        "evidence": g["evidence"],
        "gap_score": g["gap_score"],
    }


def demand_comparison(g: dict) -> str:
    """Rank 1 is the strongest, so a smaller number here than around means more demand here."""
    local, ref = g["demand_rank"], g.get("ref_rank")
    if ref is None:
        return "no comparison available"
    if local >= scoring.UNRANKED and ref >= scoring.UNRANKED:
        return "outside the top 50 both here and around"
    if ref - local >= 3:
        return "ranked higher here than in the areas around: stronger local demand"
    if local - ref >= 3:
        return "ranked lower here than in the areas around: weaker local demand"
    return "about the same as in the areas around"


def gap_for(run: RunState, genre: str) -> dict | None:
    wanted = (genre or "").strip().lower()
    return next((g for g in run.gaps + run.explored if g["genre"].lower() == wanted), None)


async def fans_of(q: QlooClient, run: RunState, genre_id: str) -> dict:
    """What people near the site who love a genre also love; fetched once per run."""
    if genre_id not in run.fans:
        run.fans[genre_id] = await engine.fan_taste(q, run.site.lat, run.site.lon, genre_id)
    return run.fans[genre_id]


def inspect_payload(run: RunState, row: dict) -> dict:
    entities, cards = storefront_favorites(row)
    # Only places locals love more than the city does say anything about travel; otherwise they are just the
    # city's famous places, and naming them that way keeps the agent from claiming that locals travel to them.
    favorites_key = (
        "places_locals_love_more_than_the_city_does" if row.get("favorites_kind") == "local"
        else "the_citys_famous_places_of_this_type"
    )
    return {
        "genre": row["genre"],
        "competitors_within_walk": [
            {k: c.get(k) for k in ("name", "rating", "price_level", "praise", "complaints", "distance_m")}
            for c in row["competitors"][:6]
        ],
        favorites_key: [
            {"name": f["name"], "km_away": round((f.get("distance_m") or 0) / 1000, 1), "price_level": f.get("price_level"),
             "praise": f.get("praise"), "inside_walk": f.get("within_walk", False)}
            for f in cards[:8]
        ],
        "do_locals_travel_for_it": gap_summary(row)["do_locals_travel_for_it"],
        "design_dna_of_these_places": scoring.design_dna(entities),
    }


def ground_names(names: list[str] | None, allowed: set[str]) -> list[str]:
    allowed_lower = {a.lower(): a for a in allowed}
    return [allowed_lower[n.lower()] for n in names or [] if isinstance(n, str) and n.lower() in allowed_lower]


def clean_concepts(run: RunState, concepts: list[dict]) -> list[dict]:
    """Keep only concepts whose genre exists in the evidence, one per genre, citing real places under original names."""
    cleaned = []
    known_places = place_names(run)
    for concept in concepts or []:
        if not isinstance(concept, dict):
            continue
        row = gap_for(run, str(concept.get("genre") or ""))
        if not row or any(c["genre_id"] == row["genre_id"] for c in cleaned):
            continue
        favorites = {card["name"] for card in storefront_favorites(row)[1] if card.get("name")}
        concept["genre"] = row["genre"]
        concept["genre_id"] = row["genre_id"]
        concept["gap_score"] = row["gap_score"]
        concept["inspired_by"] = ground_names(concept.get("inspired_by"), favorites)[:4]
        name = str(concept.get("name") or "").strip()
        taken = taken_name(name, known_places)
        if not name or taken:
            if taken:
                log.info("Concept name %r reuses the existing place %r; renamed", name, taken)
            name = f"{scoring.genre_title(row['genre'])}, {short_label(run.site.label)}"
        concept["name"] = name[:60]
        try:
            concept["price_level"] = max(1, min(4, int(concept.get("price_level") or 2)))
        except (TypeError, ValueError):
            concept["price_level"] = 2
        concept["evidence"] = gap_evidence(row, run.site.minutes)
        cleaned.append(concept)
    return cleaned[:3]


# Category words that are names of real places somewhere ("Diner", "Bakery") but are free for anyone to use.
COMMON_NAME_WORDS = {
    "bar", "cafe", "café", "coffee", "diner", "bakery", "deli", "grill", "kitchen", "tavern", "pub", "market",
    "wine", "tea", "bistro", "brasserie", "lounge", "club", "studio", "shop", "store", "gallery", "pizza",
    "pizzeria", "trattoria", "cantina", "taqueria", "restaurant", "eatery", "canteen", "corner", "local",
}


def place_names(run: RunState) -> set[str]:
    names = {p.get("name") for p in run.block}
    for row in run.gaps + run.explored:
        names |= {c.get("name") for c in row.get("competitors", [])}
        names |= {f.get("name") for f in row.get("favorites", [])}
        names |= set(row.get("city_favorites", []))
    return {name for name in names if isinstance(name, str) and name.strip()}


def _name_words(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9']+", text.lower().replace("&", " and ")) if word != "the"]


def taken_name(name: str, places: set[str]) -> str | None:
    """The existing place a concept name reuses, if any: 'Otis & Main' reuses the restaurant 'Otis'."""
    text = f" {' '.join(_name_words(name))} "
    for place in places:
        words = _name_words(place)
        if not words or len("".join(words)) < 3 or (len(words) == 1 and words[0] in COMMON_NAME_WORDS):
            continue
        if f" {' '.join(words)} " in text:
            return place
    return None


def short_label(label: str) -> str:
    """'Upper East Side, Manhattan' -> 'Upper East Side'; falls back to a neutral word for raw pins."""
    first = (label or "").split(",")[0].strip()
    if not first or first.lower() in {"selected site", "dropped pin"} or any(ch.isdigit() for ch in first[:3]):
        return "Corner"
    return first[:32]


def gap_evidence(row: dict, minutes: int = 10) -> list[str]:
    genre = row["genre"]
    nearby = f"{row['nearby_count']}{'+' if row['nearby_capped'] else ''}"
    lines = []
    ref = row.get("ref_rank")
    if row["demand_rank"] >= scoring.UNRANKED:
        lines.append(f"Locals do not rank {genre} among their top 50 place types here.")
    elif ref is not None:
        ref_text = "outside the top 50" if ref >= 51 else f"#{ref:g}"
        lines.append(f"Locals rank {genre} #{row['demand_rank']} here, versus a median {ref_text} in same-size areas around.")
    else:
        lines.append(f"Locals rank {genre} #{row['demand_rank']} among place types here.")
    expected = row.get("expected_nearby")
    if expected is not None:
        lines.append(
            f"Qloo lists {nearby} {genre} places inside the {minutes}-minute walk; a block this dense would typically have about {expected:g}."
        )
    if row.get("favorites_kind") == "local" and row["favorites_total"]:
        lines.append(
            f"{row['favorites_far']} of {row['favorites_total']} {genre} places that locals love more than the city does "
            f"are outside the walk (median {row['median_favorite_km']} km away)."
        )
    elif row["favorites_total"]:
        lines.append(f"Locals' favorite {genre} places are the city's famous ones, so where they travel says little here.")
    if row.get("evidence") == "thin":
        lines.append("Thin evidence: Qloo knows at most one such place around here.")
    elif row.get("evidence") == "atypical":
        lines.append("Atypical: locals' favorites of this type are mostly hotels or malls, not storefronts.")
    return lines


def one_liner(row: dict) -> str:
    title = scoring.genre_title(row["genre"])
    leakage = row.get("leakage")
    if leakage is not None and leakage >= 0.65 and row["favorites_far"] >= 3 and row["median_favorite_km"]:
        return f"{title}, close to home: locals travel {row['median_favorite_km']} km for the spots they love most."
    if row.get("lift", 0) >= 0.5:
        return f"{title} for a neighborhood that loves it more than the areas around it do."
    if row.get("relative_supply", 1) <= 0.8:
        return f"{title} where the block has fewer than its density predicts."
    return f"A sharper {title.lower()} for a crowd that already loves the category."


def concept_rows(run: RunState) -> list[dict]:
    solid = [row for row in run.gaps if row.get("evidence") == "ok"]
    return (solid or run.gaps)[:3]


def storefront_favorites(row: dict) -> tuple[list[dict], list[dict]]:
    """Locals' favorite places of a genre without hotels and malls, as (entities, cards)."""
    pairs = [
        (entity, card) for entity, card in zip(row["_favorite_entities"], row["favorites"]) if scoring.is_storefront_place(entity)
    ]
    return [entity for entity, _ in pairs], [card for _, card in pairs]


def crowd_phrase(demographics: dict | None, minutes: int) -> str:
    skew = describe_age(demographics)
    if not skew or skew == "no strong age skew":
        return f"Everyone within a {minutes}-minute walk; no strong age skew"
    return f"A crowd that {skew.replace('-', '–')}"


def rule_concepts(run: RunState) -> list[dict]:
    concepts = []
    minutes = run.site.minutes
    for row in concept_rows(run):
        entities, cards = storefront_favorites(row)
        dna = scoring.design_dna(entities)
        complaints = [c for comp in row["competitors"] for c in comp.get("complaints", [])][:3]
        title = scoring.genre_title(row["genre"])
        concepts.append({
            "name": f"{title}, {short_label(run.site.label)}",
            "genre": row["genre"],
            "genre_id": row["genre_id"],
            "gap_score": row["gap_score"],
            "one_liner": one_liner(row),
            "for_whom": crowd_phrase(run.demographics, minutes),
            "price_level": dna.get("typical_price_level") or 2,
            "why_here": gap_evidence(row, minutes),
            "beat_competitors": (
                f"Nearby reviews flag: {', '.join(complaints)}. Design the service around avoiding these."
                if complaints else "Few direct competitors nearby; win on quality and atmosphere."
            ),
            "signature": scoring.signature_items(row["genre"], dna),
            "inspired_by": [card["name"] for card in cards[:3]],
            "risk": (
                f"{row['nearby_count']} competitors already inside the walk." if row["nearby_count"] >= 10
                else "Demand is inferred from taste signals, not foot traffic; validate on site."
            ),
            "evidence": gap_evidence(row, minutes),
        })
    return concepts


CONCEPT_SYSTEM = """You are Blank Space, a retail and hospitality strategist that designs businesses for empty storefronts.
You only reason from Qloo evidence about the people inside the site's walking catchment.
Demand is compared with six same-size areas around the site, not the whole city; supply is compared with what a block
this dense would typically hold. Only claim that locals travel for something when the evidence says so; when it says
their favorites are just the city's famous places, there is no travel evidence. Distances are medians, not averages.
Work like an analyst, in as few turns as possible. Tools called in the same turn run in parallel, so batch them:
1. First turn: test_category for up to 3 hunches the gap table does not cover, drawn from the brands, artists and
   taste cues this area over-indexes on (sports teams suggest a sports bar; design brands suggest a concept store);
   in the same turn, inspect_gap and fan_taste for the 2 or 3 strongest gaps. Fan taste that overlaps the area's
   own signature brands and artists is evidence of fit, and its names are material for programming and partners.
2. Second turn, only if needed: inspect_gap or fan_taste for a tested category you now want to build on.
3. Then call submit_concepts with exactly 3 concepts, each on a different genre from the gap table or your tests.
   Prefer evidence "ok". A weak test result is a finding: say so in risk, or move on.
Give every tool call a one-sentence reason that names the evidence behind it.
Rules: why_here cites numbers exactly as they appear in the evidence; never invent places, brands or statistics;
inspired_by only contains names returned by inspect_gap; concept names are original and never reuse or echo the
name of an existing place; respect the owner's notes."""

MAX_LIVE_TESTS = 3
MAX_FAN_CHECKS = 4

REASON = {"type": "string", "description": "One sentence: why you are checking this, naming the evidence behind it"}

CONCEPT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "test_category",
            "description": "Test a business category that is not in the gap table, live against Qloo: places inside the walk, "
                           "what the surroundings predict, places locals love versus the city's, and a gap score on the same "
                           "scale as the table. At most 3 per survey.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "A storefront category, e.g. 'bakery' or 'sports bar'"},
                    "reason": REASON,
                },
                "required": ["category", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fan_taste",
            "description": "Live Qloo cross-domain check: brands and artists that people near the site who love a category also "
                           "love, and which of them belong to the area's own signature taste.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "A genre from the gap table or a tested category"},
                    "reason": REASON,
                },
                "required": ["category", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_gap",
            "description": "Competitors within walking distance (with review praise and complaints) and locals' favorite places of one genre, plus the design DNA of those favorites.",
            "parameters": {
                "type": "object",
                "properties": {
                    "genre": {"type": "string", "description": "Genre exactly as written in the gap table or a test result"},
                    "reason": REASON,
                },
                "required": ["genre", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_concepts",
            "description": "Submit the final 3 concepts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "concepts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "A memorable venue name"},
                                "genre": {"type": "string", "description": "Genre exactly as written in the gap table or a test result"},
                                "one_liner": {"type": "string"},
                                "for_whom": {"type": "string"},
                                "price_level": {"type": "integer", "minimum": 1, "maximum": 4},
                                "why_here": {"type": "array", "items": {"type": "string"},
                                             "description": "2-3 lines, each citing numbers exactly as they appear in the evidence"},
                                "beat_competitors": {"type": "string"},
                                "signature": {"type": "array", "items": {"type": "string"},
                                              "description": "3-4 specific things people would come for, not amenities"},
                                "inspired_by": {"type": "array", "items": {"type": "string"}},
                                "risk": {"type": "string", "description": "The biggest risk the evidence shows"},
                            },
                            "required": ["name", "genre", "one_liner", "for_whom", "why_here", "signature", "risk"],
                        },
                    }
                },
                "required": ["concepts"],
            },
        },
    },
]


AGENT_VERSION = fingerprint(CONCEPT_SYSTEM, CONCEPT_TOOLS, MAX_LIVE_TESTS, MAX_FAN_CHECKS)


@dataclass
class AgentResult:
    concepts: list[dict]
    raw_concepts: list[dict]
    model: str | None
    trail: list[list]  # replayable record of what the agent did: [event, data] pairs


async def agent_concepts(llm: LLM, q: QlooClient, run: RunState, emit: Emit) -> AgentResult:
    trail: list[list] = []
    testing: dict[str, asyncio.Future] = {}  # genre id -> live measurement, shared by concurrent calls
    announced: set[tuple[str, str]] = set()
    results: dict[tuple[str, str], asyncio.Future] = {}
    fan_checks = 0

    def call_key(name: str, args: dict) -> tuple[str, str]:
        return name, str(args.get("category") or args.get("genre") or "").strip().lower()

    async def record(event: str, data: dict) -> None:
        trail.append([event, data])
        await emit(event, data)

    async def refuse(message: str) -> dict:
        await record("finding", {"text": message})
        return {"error": message}

    async def inspect(args: dict) -> dict:
        row = gap_for(run, str(args.get("genre") or ""))
        return inspect_payload(run, row) if row else {"error": "Unknown genre. Use one from the gap table or a test result."}

    async def resolve(query: str) -> tuple[dict | None, str | None]:
        row = gap_for(run, query)
        if row:
            return {"id": row["genre_id"], "name": row["genre"]}, None
        return await engine.find_genre(q, run.genres, query)

    async def measure(genre: dict) -> dict:
        row = await engine.probe_genre(q, run.catchment, genre, run.gaps)
        row["source"] = "agent"
        run.explored.append(row)
        trail.append(["explored", {"genre": genre}])
        await emit("explored", {"row": public_gap(row)})
        return row

    async def test_category(args: dict) -> dict:
        query = str(args.get("category") or "").strip()[:80]
        try:
            genre, why_not = await engine.find_genre(q, run.genres, query) if query else (None, "No category given.")
        except QlooError as exc:
            return await refuse(f"Qloo lookup for '{query}' failed: {exc}")
        if not genre:
            return await refuse(why_not or f"Qloo has no storefront category matching '{query}'.")
        if genre["id"] not in testing:
            existing = gap_for(run, genre["name"])
            if existing:
                await record("finding", {"text": f"{existing['genre']} is already in the gap table (gap {existing['gap_score']})."})
                return {"already_measured": True, **gap_summary(existing)}
            if not scoring.matches_focus(genre["name"], run.site.focus):
                return await refuse(f"{genre['name']} is outside the owner's focus.")
            if len(testing) >= MAX_LIVE_TESTS:
                return await refuse(f"Live test budget used ({MAX_LIVE_TESTS} per survey).")
            testing[genre["id"]] = asyncio.ensure_future(measure(genre))
        try:
            row = await asyncio.shield(testing[genre["id"]])
        except QlooError as exc:
            return await refuse(f"Qloo test of {genre['name']} failed: {exc}")
        return {"tested_live": True, **gap_summary(row), "evidence": gap_evidence(row, run.site.minutes)}

    async def fan_taste(args: dict) -> dict:
        nonlocal fan_checks
        query = str(args.get("category") or "").strip()[:80]
        if fan_checks >= MAX_FAN_CHECKS:
            return await refuse(f"Fan taste budget used ({MAX_FAN_CHECKS} per survey).")
        fan_checks += 1
        try:
            genre, why_not = await resolve(query) if query else (None, "No category given.")
            if not genre:
                return await refuse(why_not or f"Qloo has no storefront category matching '{query}'.")
            fans = await fans_of(q, run, genre["id"])
        except QlooError as exc:
            return await refuse(f"Qloo fan taste for '{query}' failed: {exc}")
        brands = [b["name"] for b in fans["brands"]]
        artists = [a["name"] for a in fans["artists"]]
        signature = {e["name"] for e in run.taste.get("distinctive_brands", []) + run.taste.get("distinctive_artists", [])}
        shared = [name for name in brands + artists if name in signature]
        text = f"Local fans of {genre['name']} also love {', '.join(brands[:4]) or 'no brands Qloo knows'}"
        text += f"; artists {', '.join(artists[:3])}" if artists else ""
        text = text.rstrip(".") + "."
        if shared:
            text += f" Shared with the area's signature taste: {', '.join(shared)}".rstrip(".") + "."
        await record("finding", {"text": text})
        return {"category": genre["name"], "local_fans_also_love": {"brands": brands, "artists": artists},
                "shared_with_area_signature": shared}

    async def on_call(name: str, args: dict, thought: str | None) -> None:
        if name == "submit_concepts":
            return
        key = call_key(name, args)
        if key in announced:  # a repeated check adds nothing new to the log
            return
        announced.add(key)
        await record("agent", {"tool": name, "args": args, "thought": thought})

    def once(name: str, handler: Callable[[dict], Awaitable[dict]]) -> Callable[[dict], Awaitable[dict]]:
        """Runs each distinct check once; a repeat gets the earlier result back, saying so."""
        async def checked(args: dict) -> dict:
            key = call_key(name, args)
            if key in results:
                result = await asyncio.shield(results[key])
                return {**result, "note": "You already ran this check in this survey; this is the same result."}
            results[key] = asyncio.ensure_future(handler(args))
            return await asyncio.shield(results[key])
        return checked

    async def on_step(step: int, phase: str) -> None:
        label = "Agent reads the evidence and plans what to check" if step == 0 else "Agent weighs what it found"
        state = {"start": "running", "end": "done"}.get(phase, phase)
        await emit("status", {"step": f"agent-{step}", "state": state, "label": label})

    result, model = await llm.run_tools(
        CONCEPT_SYSTEM,
        "Evidence pack:\n" + json.dumps(evidence_brief(run), ensure_ascii=False),
        CONCEPT_TOOLS,
        {
            "inspect_gap": once("inspect_gap", inspect),
            "test_category": once("test_category", test_category),
            "fan_taste": once("fan_taste", fan_taste),
        },
        final_tool="submit_concepts",
        max_steps=6,
        on_call=on_call,
        on_step=on_step,
    )
    raw = [c for c in (result or {}).get("concepts") or [] if isinstance(c, dict)]
    return AgentResult(clean_concepts(run, copy.deepcopy(raw)), raw, model, trail)


async def replay_agent(q: QlooClient, run: RunState, saved: dict, emit: Emit) -> list[dict]:
    """Re-emits a saved investigation for identical evidence; live tests are re-measured from the Qloo cache."""
    for event, data in saved.get("trail", []):
        if event == "explored":
            row = await engine.probe_genre(q, run.catchment, data["genre"], run.gaps)
            row["source"] = "agent"
            run.explored.append(row)
            await emit("explored", {"row": public_gap(row)})
        else:
            await emit(event, data)
    return clean_concepts(run, copy.deepcopy(saved.get("raw_concepts", [])))


async def analyze_site(
    q: QlooClient, walker: CatchmentService, llm: LLM, store: RunStore, site: Site, emit: Emit,
    answers: AnswerCache | None = None,
) -> RunState:
    run = RunState(id=uuid.uuid4().hex[:12], site=site)
    started, calls_before, hits_before = time.time(), q.calls, q.cache_hits
    await emit("run", {"run_id": run.id, "site": site.__dict__, "llm": llm.enabled})

    async def step(name: str, label: str, coro):
        await emit("status", {"step": name, "state": "running", "label": label})
        result = await coro
        await emit("status", {"step": name, "state": "done", "label": label})
        return result

    minutes = site.minutes
    try:
        catchment = await step(
            "walk", f"Tracing a {minutes}-minute walk over the street network", walker.walk(site.lat, site.lon, minutes)
        )
        run.catchment = catchment
        await emit("catchment", catchment.public())
        block, (genres, cues), taste = await asyncio.gather(
            step("block", f"Reading every place inside the {minutes}-minute walk", engine.scan_block(q, catchment)),
            step("demand", "Ranking what locals engage with against six same-size areas around",
                 engine.demand_genres(q, catchment)),
            step("taste", "Finding brands and artists this area over-indexes on", engine.local_taste(q, site.lat, site.lon)),
        )
        run.block, run.genres, run.cues, run.taste = block, genres, cues, taste
        run.summary = scoring.summarize_block(block)
        await emit("block", {
            "summary": run.summary,
            "places": [scoring.place_card(p, (site.lat, site.lon)) for p in block],
        })
        await emit("demand", {"genres": genres[:12], "cues": cues})

        gaps, demographics = await asyncio.gather(
            step("gaps", "Comparing supply with the surroundings and finding places locals love more than the city",
                 engine.gap_table(q, catchment, genres, site.focus)),
            step("crowd", "Reading the crowd's age and gender skew", engine.crowd_demographics(q, block)),
        )
        run.gaps, run.demographics = gaps, demographics
        await emit("gaps", {"rows": [public_gap(g) for g in gaps]})
        await emit("taste", {**taste, "demographics": demographics, "crowd": describe_age(demographics)})

        if not gaps:
            await emit("concepts", {"concepts": [], "mode": "none", "note": "Not enough Qloo data around this site."})
        else:
            await emit("status", {"step": "concepts", "state": "running", "label": "Designing concepts from the gaps"})
            concepts, mode, about = [], "rules", {}
            if llm.enabled:
                concepts, about = await concepts_from_agent(llm, q, run, emit, answers)
                mode = "agent" if concepts else "rules"
            if not concepts:
                concepts, mode, about = rule_concepts(run), "rules", {}
            run.concepts = concepts
            await emit("status", {"step": "concepts", "state": "done", "label": "Designing concepts from the gaps"})
            await emit("concepts", {"concepts": concepts, "mode": mode, **about})
    except QlooError as exc:
        await emit("error", {"message": str(exc)})
    finally:
        store.add(run)
        await emit("done", {
            "run_id": run.id,
            "seconds": round(time.time() - started, 1),
            "qloo_calls": q.calls - calls_before,
            "cache_hits": q.cache_hits - hits_before,
        })
    return run


async def concepts_from_agent(
    llm: LLM, q: QlooClient, run: RunState, emit: Emit, answers: AnswerCache | None,
) -> tuple[list[dict], dict]:
    """The agent's concepts and how they were made; an empty list means the evidence rules must step in."""
    key = fingerprint("concepts", AGENT_VERSION, evidence_brief(run))
    saved = answers.get("concepts", key) if answers else None
    try:
        if saved:
            await emit("replay", {"saved_at": saved.get("saved_at"), "model": saved.get("model")})
            concepts = await replay_agent(q, run, saved, emit)
            return concepts, {"model": saved.get("model"), "replayed_from": saved.get("saved_at")}
        result = await agent_concepts(llm, q, run, emit)
    except LLMUnavailable:
        log.warning("Every LLM model is resting; falling back to evidence rules", exc_info=True)
        await emit("notice", {"message": "Every free AI model is busy or out of quota right now, so these concepts come from the evidence rules."})
        return [], {}
    except Exception as exc:  # LLM outages must not break the demo
        log.warning("Concept agent failed; falling back to evidence rules", exc_info=True)
        await emit("notice", {"message": f"The AI agent failed ({type(exc).__name__}), so these concepts come from the evidence rules."})
        return [], {}
    if result.concepts and answers:
        answers.put("concepts", key, {"trail": result.trail, "raw_concepts": result.raw_concepts, "model": result.model})
    return result.concepts, {"model": result.model}


DESIGN_SYSTEM = """You are Blank Space's concept designer. Turn a business concept into a design brief for an empty storefront.
Ground every choice in the evidence: design DNA of the locals' favorite places, what local fans of this category also
love, local artists, nearby places and local brands.
Return JSON with keys: name, tagline, concept_statement, interior {mood, materials (list), lighting, layout, seating},
offer (list of 4-6 items), price_level (1-4), hours, music {direction, artists (list, only from local_artists)},
partners (list of {name, why}; name only from nearby_places or partner_brands), launch (an opening-night idea; never
mention dates or years), image_prompt (a photorealistic wide view of the whole interior: layout, materials, lighting
and seating; no people, text or logos), facade_prompt (the shopfront seen from a typical street of this neighborhood,
with a sign that reads exactly the concept name; no people)."""


async def design_concept(
    llm: LLM, images: Images, run: RunState, index: int, q: QlooClient | None = None,
    answers: AnswerCache | None = None,
) -> dict:
    concept = run.concepts[index]
    row = gap_for(run, concept["genre"])
    dna = scoring.design_dna(storefront_favorites(row)[0]) if row else {}
    fans: dict = {"brands": [], "artists": []}
    if row and q is not None:
        try:
            fans = await fans_of(q, run, row["genre_id"])
        except QlooError:
            log.warning("Fan taste lookup failed; designing from the area's taste only", exc_info=True)
    fan_artists = [a["name"] for a in fans["artists"]]
    area_artists = [a["name"] for a in run.taste.get("distinctive_artists", []) + run.taste.get("artists", [])]
    # Artists loved by people near the site who love this category come first; the area's favorites fill in.
    local_artists = list(dict.fromkeys(fan_artists + area_artists))
    nearby = [p.get("name") for p in run.block if p.get("name")]
    area_brands = run.taste.get("distinctive_brands", []) + run.taste.get("brands", [])
    brand_cards = list({b["name"]: b for b in area_brands + fans["brands"]}.values())
    fitting_brands = [b["name"] for b in scoring.partner_brands(brand_cards, concept["genre"])]
    design: dict[str, Any] = {}
    mode, model = "rules", None
    if llm.enabled:
        payload = json.dumps({
            "site": run.site.label,
            "owner_notes": run.site.notes or None,
            "concept": {k: concept.get(k) for k in ("name", "genre", "one_liner", "for_whom", "price_level", "signature")},
            "design_dna_of_locals_favorites": dna,
            "local_artists": local_artists[:15],
            "nearby_places": nearby[:40],
            "local_brands": [{"name": b["name"], "type": b.get("kind")} for b in brand_cards[:15]],
            "local_fans_of_this_category_also_love": {"brands": [b["name"] for b in fans["brands"]], "artists": fan_artists},
            "partner_brands": fitting_brands[:8],
            "taste_cues": run.cues,
            "crowd": describe_age(run.demographics),
        }, ensure_ascii=False)
        key = fingerprint("design", DESIGN_SYSTEM, payload)
        saved = answers.get("design", key) if answers else None
        try:
            if saved:
                design, model = saved["design"], saved.get("model")
            else:
                design, model = await llm.complete_json(DESIGN_SYSTEM, payload)
                if design and answers:
                    answers.put("design", key, {"design": design, "model": model})
            design = copy.deepcopy(design) if isinstance(design, dict) else {}
            mode = "agent"
        except Exception:
            log.warning("Design brief LLM call failed; using evidence rules", exc_info=True)
            design = {}
    if not design:
        design = rule_design(run, concept, dna, local_artists, fitting_brands, fan_led=bool(fan_artists))
        mode, model = "rules", None
    music = design.get("music") if isinstance(design.get("music"), dict) else {}
    music["artists"] = ground_names(music.get("artists"), set(local_artists))[:6]
    design["music"] = music
    allowed_partners = {name.lower(): name for name in set(nearby) | set(fitting_brands)}
    design["partners"] = [
        {**p, "name": allowed_partners[p["name"].lower()]}
        for p in design.get("partners") or []
        if isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"].lower() in allowed_partners
    ][:4]
    design["dna"] = dna
    design["mode"] = mode
    design["model"] = model
    design["shots"] = design_shots(run, concept, design, dna)
    design["renders"] = {"enabled": images.enabled, "model": images.model}
    return design


INTERIOR_STYLE = (
    "Photorealistic architectural photograph, wide-angle at eye level, the whole room visible from the entrance, "
    "real materials, balanced daylight and warm interior light, styled for opening day. No people, no text, no logos."
)
FACADE_STYLE = (
    "Photorealistic street photograph, straight-on view of the ground-floor shopfront in late-afternoon light, part of "
    "the building above visible, a believable street of this neighborhood. No people, no logos, no other readable text."
)


def design_shots(run: RunState, concept: dict, design: dict, dna: dict) -> list[dict]:
    """Prompts for the two renders. The server keeps them, so a client can only render the shots it was given."""
    sign = sign_text(str(design.get("name") or concept["name"]))
    interior = design.get("image_prompt")
    facade = design.get("facade_prompt")
    interior = f"{interior.strip()} {INTERIOR_STYLE}" if isinstance(interior, str) and interior.strip() else interior_prompt(run, concept, dna, design)
    if isinstance(facade, str) and facade.strip():
        facade = facade.strip()
        if sign.lower() not in facade.lower():
            facade += f' The sign above the entrance reads "{sign}".'
        facade = f"{facade} {FACADE_STYLE}"
    else:
        facade = facade_prompt(run, concept, dna, design, sign)
    return [
        {"kind": "interior", "label": "Interior", "aspect": "16:9", "prompt": interior[:3500]},
        {"kind": "exterior", "label": "From the street", "aspect": "16:9", "prompt": facade[:3500]},
    ]


def sign_text(name: str) -> str:
    """What the sign says: rule-made names end with the neighborhood ("Seafood, Williamsburg"), which a sign would not."""
    return name.split(",")[0].strip()[:40] or "Opening soon"


PLACE_NOUNS = {
    "restaurant", "bakery", "cafe", "café", "shop", "store", "bar", "house", "deli", "diner", "pizzeria", "bistro",
    "grill", "kitchen", "lounge", "pub", "venue", "brewery", "club", "studio", "gallery", "market", "salon", "spa",
    "gym", "boutique", "parlor", "parlour", "taproom", "hall", "room", "eatery", "bookstore", "theater", "theatre",
}


def place_noun(genre: str) -> str:
    """'Seafood' -> 'seafood restaurant', 'Wine Bar' -> 'wine bar', 'Fashion accessories' -> 'fashion accessories shop'."""
    title = scoring.genre_title(genre).lower()
    if title.split()[-1] in PLACE_NOUNS:
        return title
    kind = scoring.genre_kind(genre)
    return f"{title} restaurant" if kind == "food" else f"{title} shop" if kind == "retail" else title


def interior_prompt(run: RunState, concept: dict, dna: dict, design: dict | None = None) -> str:
    """Render prompt assembled from the design sheet and the favorites' design DNA, used when no LLM wrote one."""
    noun = place_noun(concept["genre"])
    interior = (design or {}).get("interior") if isinstance((design or {}).get("interior"), dict) else {}
    raw_materials = interior.get("materials") or dna.get("decor", [])[:3]
    materials = [raw_materials] if isinstance(raw_materials, str) else [str(m) for m in raw_materials]
    details = [
        f"Mood: {interior.get('mood') or ', '.join(dna.get('ambience', [])[:3]).lower()}",
        f"materials and style: {', '.join(materials).lower()}" if materials else "",
        f"layout: {interior['layout']}" if interior.get("layout") else "",
        f"seating: {interior['seating']}" if interior.get("seating") else "",
        f"lighting: {interior['lighting']}" if interior.get("lighting") else "",
    ]
    described = ". ".join(part for part in details if part and not part.endswith(": "))
    return f"Interior of a small street-level {noun} in {run.site.label}. {described}. {INTERIOR_STYLE}"


def facade_prompt(run: RunState, concept: dict, dna: dict, design: dict, sign: str) -> str:
    noun = place_noun(concept["genre"])
    style = ", ".join(dna.get("decor", [])[:2]).lower()
    mood = ", ".join(dna.get("ambience", [])[:2]).lower() or "welcoming"
    return (
        f"Street-level view of a newly opened {noun} on a typical street of {run.site.label}. A sign above the entrance "
        f'reads "{sign}" in clear, well-designed lettering. {"Shopfront style: " + style + ". " if style else ""}'
        f"Large windows show a {mood} interior. {FACADE_STYLE}"
    )


def render_key(images: Images, shot: dict) -> str:
    return fingerprint("image", images.provider, images.model, shot["aspect"], shot["prompt"])


def saved_render(images: Images, shot: dict, answers: AnswerCache | None) -> tuple[str, str | None] | None:
    saved = answers.get("image", render_key(images, shot)) if answers else None
    return (saved["image"], saved.get("model") or images.model) if saved and saved.get("image") else None


async def render(images: Images, shot: dict, answers: AnswerCache | None) -> tuple[str | None, str | None]:
    """The image and the model that made it; the first provider that answers renders it."""
    image, model = await images.render(shot["prompt"], shot["aspect"])
    if image and answers:
        answers.put("image", render_key(images, shot), {"image": image, "model": model})
    return image, model


PARTNER_KINDS = {
    "food": ("bar", "venue", "retail"),
    "bar": ("food", "venue"),
    "venue": ("food", "bar"),
    "retail": ("food", "bar"),
    "wellness": ("food", "retail"),
}

LAYOUTS = {
    "food": "Open dining room with a window counter onto the street",
    "bar": "Long bar along one wall, low tables by the window",
    "venue": "Screen or stage at the back, bar to one side, standing room up front",
    "retail": "Open floor behind a front display window, counter at the back",
    "wellness": "Calm front reception with private rooms behind",
}


def partner_places(run: RunState, genre: str, limit: int = 2) -> list[str]:
    """Well-loved nearby places that complement the concept (dinner, then drinks) rather than compete with it."""
    wanted = PARTNER_KINDS.get(scoring.genre_kind(genre), ())
    candidates = []
    for place in run.block:
        names = [name for _, name in scoring.genre_tags(place)]
        business = [name for name in names if scoring.is_business_genre(name)]
        if not place.get("name") or genre in names or not business:
            continue
        kind = scoring.genre_kind(business[0])
        order = wanted.index(kind) if kind in wanted else len(wanted)
        candidates.append((order, -(place.get("popularity") or 0), place["name"]))
    return [name for _, _, name in sorted(candidates)[:limit]]


def rule_design(
    run: RunState, concept: dict, dna: dict, artists: list[str], partner_brands: list[str], fan_led: bool = False,
) -> dict:
    ambience = ", ".join(dna.get("ambience", [])[:3]).lower() or "warm and welcoming"
    decor = dna.get("decor", [])[:4]
    minutes = run.site.minutes
    title = scoring.genre_title(concept["genre"])
    layout = LAYOUTS.get(scoring.genre_kind(concept["genre"]), LAYOUTS["food"])
    if any("outdoor" in amenity.lower() for amenity in dna.get("amenities", [])):
        layout += ", plus sidewalk seating"
    partners = [
        {"name": name, "why": f"Popular inside the {minutes}-minute walk and complements rather than competes; cross-promote."}
        for name in partner_places(run, concept["genre"])
    ]
    if partner_brands:
        partners.append({"name": partner_brands[0], "why": "A brand this area over-indexes on; a natural co-branded launch."})
    if partners and fan_led and artists:
        launch = f"Opening night co-hosted with {partners[0]['name']}, playing artists local {title} fans love ({', '.join(artists[:2])})."
    elif partners:
        launch = f"Opening night co-hosted with {partners[0]['name']}."
    else:
        launch = f"Opening night for the neighbors within a {minutes}-minute walk."
    return {
        "name": concept["name"],
        "tagline": concept.get("one_liner"),
        "concept_statement": " ".join(concept.get("why_here", [])),
        "interior": {
            "mood": ambience,
            "materials": decor,
            "lighting": "Warm, layered lighting" if "romantic" in ambience or "cozy" in ambience else "Bright, natural light",
            "layout": layout,
            "seating": ", ".join(
                a for a in dna.get("amenities", []) if "seating" in a.lower() and "outdoor" not in a.lower()
            ) or "Mixed bar and table seating",
        },
        "offer": scoring.signature_items(concept["genre"], dna, limit=6),
        "price_level": concept.get("price_level", 2),
        "hours": "To be set from local foot traffic",
        "music": {
            "direction": f"What local {title} fans also listen to" if fan_led else "Built from artists that over-index locally",
            "artists": artists[:5],
        },
        "partners": partners,
        "launch": launch,
        "image_prompt": None,
    }


BASELINE_SYSTEM = "You are a retail strategy consultant."


async def baseline_concepts(llm: LLM, site: Site, answers: AnswerCache | None = None) -> list[dict]:
    """What a language model suggests with no data, shown next to the evidence-based concepts."""
    prompt = (
        f"There is an empty ground-floor storefront at {site.label} (lat {site.lat}, lon {site.lon}). "
        "Propose 3 business concepts likely to succeed there. Return JSON {\"concepts\": [{\"name\", \"genre\", \"one_liner\"}]}."
    )
    key = fingerprint("baseline", BASELINE_SYSTEM, prompt)
    saved = answers.get("baseline", key) if answers else None
    if saved:
        return saved.get("concepts", [])
    data, model = await llm.complete_json(BASELINE_SYSTEM, prompt)
    concepts = [c for c in data.get("concepts") or [] if isinstance(c, dict)][:3]
    if concepts and answers:
        answers.put("baseline", key, {"concepts": concepts, "model": model})
    return concepts
