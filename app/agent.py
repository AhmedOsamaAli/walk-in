"""Runs the Blank Space agent for a site: gather evidence, find gaps, propose and design concepts."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from . import engine, scoring
from .catchment import Catchment, CatchmentService
from .images import ImageGen
from .llm import LLM
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
        "local_brands": [b["name"] for b in run.taste.get("distinctive_brands", [])],
        "local_artists": [a["name"] for a in run.taste.get("distinctive_artists", [])],
        "crowd": describe_age(run.demographics),
    }


def gap_summary(g: dict) -> dict:
    return {
        "genre": g["genre"],
        "locals_rank_here": g["demand_rank"] if g["demand_rank"] < scoring.UNRANKED else "outside their top 50",
        "median_rank_in_6_same_size_areas_around": g["ref_rank"],
        "places_within_walk": f"{g['nearby_count']}{'+' if g['nearby_capped'] else ''}",
        "typical_for_a_block_this_dense": g["expected_nearby"],
        "relative_supply": g["relative_supply"],
        "local_favorites_kind": g["favorites_kind"],
        "local_favorites_outside_walk": f"{g['favorites_far']}/{g['favorites_total']}",
        "median_distance_to_local_favorites_km": g["median_favorite_km"],
        "evidence": g["evidence"],
        "gap_score": g["gap_score"],
    }


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
    return {
        "genre": row["genre"],
        "competitors_within_walk": [
            {k: c.get(k) for k in ("name", "rating", "price_level", "praise", "complaints", "distance_m")}
            for c in row["competitors"][:6]
        ],
        "locals_favorites": [
            {"name": f["name"], "km_away": round((f.get("distance_m") or 0) / 1000, 1), "price_level": f.get("price_level"),
             "praise": f.get("praise"), "inside_walk": f.get("within_walk", False)}
            for f in cards[:8]
        ],
        "locals_favorites_kind": row.get("favorites_kind"),
        "city_famous_favorites": row.get("city_favorites", []),
        "design_dna_of_favorites": scoring.design_dna(entities),
    }


def ground_names(names: list[str] | None, allowed: set[str]) -> list[str]:
    allowed_lower = {a.lower(): a for a in allowed}
    return [allowed_lower[n.lower()] for n in names or [] if isinstance(n, str) and n.lower() in allowed_lower]


def clean_concepts(run: RunState, concepts: list[dict]) -> list[dict]:
    """Keep only concepts whose genre exists in the gap table, and only cite real places."""
    cleaned = []
    for concept in concepts or []:
        row = gap_for(run, concept.get("genre", ""))
        if not row:
            continue
        favorites = {card["name"] for card in storefront_favorites(row)[1] if card.get("name")}
        concept["genre"] = row["genre"]
        concept["genre_id"] = row["genre_id"]
        concept["gap_score"] = row["gap_score"]
        concept["inspired_by"] = ground_names(concept.get("inspired_by"), favorites)[:4]
        try:
            concept["price_level"] = max(1, min(4, int(concept.get("price_level") or 2)))
        except (TypeError, ValueError):
            concept["price_level"] = 2
        concept["evidence"] = gap_evidence(row, run.site.minutes)
        cleaned.append(concept)
    return cleaned[:3]


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
this dense would typically hold. Locals' favorites of kind "citywide" are just the city's famous places: do not treat
them as evidence that locals travel.
Work like an analyst:
1. Form at least one hypothesis the gap table does not cover, from the brands, artists and taste cues this area
   over-indexes on (sports teams suggest a sports bar; a list of design brands suggests a concept store), and test it
   with test_category, which queries Qloo live. You have at most 3 tests.
2. Ask fan_taste what people near the site who love a category also love. Overlap with the area's own signature
   brands and artists is evidence of fit; the names are material for programming, partners and music.
3. Inspect the gaps you will build on with inspect_gap (at least two).
4. Call submit_concepts with exactly 3 distinct concepts, each on a different genre from the gap table or your tests.
   Prefer evidence "ok". A weak test result is a finding: mention it in risk or move on.
Rules: cite numbers from the evidence in why_here; never invent places, brands or statistics;
inspired_by must only contain names returned by inspect_gap; respect the owner's notes."""

MAX_LIVE_TESTS = 3
MAX_FAN_CHECKS = 4

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
                "properties": {"category": {"type": "string", "description": "A storefront category, e.g. 'bakery' or 'sports bar'"}},
                "required": ["category"],
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
                "properties": {"category": {"type": "string", "description": "A genre from the gap table or a tested category"}},
                "required": ["category"],
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
                "properties": {"genre": {"type": "string", "description": "Genre exactly as written in the gap table or a test result"}},
                "required": ["genre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "local_taste",
            "description": "Brands and artists this neighborhood over-indexes on versus same-size areas around it, plus crowd age skew.",
            "parameters": {"type": "object", "properties": {}},
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
                                "why_here": {"type": "array", "items": {"type": "string"}},
                                "beat_competitors": {"type": "string"},
                                "signature": {"type": "array", "items": {"type": "string"}},
                                "inspired_by": {"type": "array", "items": {"type": "string"}},
                                "risk": {"type": "string"},
                            },
                            "required": ["name", "genre", "one_liner", "why_here", "signature"],
                        },
                    }
                },
                "required": ["concepts"],
            },
        },
    },
]


async def agent_concepts(llm: LLM, q: QlooClient, run: RunState, emit: Emit) -> list[dict]:
    fan_checks = 0

    async def inspect(args: dict) -> dict:
        row = gap_for(run, args.get("genre", ""))
        return inspect_payload(run, row) if row else {"error": "Unknown genre. Use one from the gap table or a test result."}

    async def taste(_: dict) -> dict:
        return {
            "local_brands": [b["name"] for b in run.taste.get("brands", [])],
            "distinctive_brands": [b["name"] for b in run.taste.get("distinctive_brands", [])],
            "local_artists": [a["name"] for a in run.taste.get("distinctive_artists", [])],
            "crowd": describe_age(run.demographics),
        }

    async def refuse(message: str) -> dict:
        await emit("finding", {"text": message})
        return {"error": message}

    async def resolve(query: str) -> dict | None:
        row = gap_for(run, query)
        if row:
            return {"id": row["genre_id"], "name": row["genre"]}
        return await engine.find_genre(q, run.genres, query)

    async def test_category(args: dict) -> dict:
        query = str(args.get("category") or "").strip()[:80]
        try:
            genre = await engine.find_genre(q, run.genres, query) if query else None
        except QlooError as exc:
            return await refuse(f"Qloo lookup for '{query}' failed: {exc}")
        if not genre:
            return await refuse(f"Qloo has no storefront category matching '{query}'.")
        existing = gap_for(run, genre["name"])
        if existing:
            return {"already_measured": True, **gap_summary(existing)}
        if not scoring.matches_focus(genre["name"], run.site.focus):
            return await refuse(f"{genre['name']} is outside the owner's focus.")
        if len(run.explored) >= MAX_LIVE_TESTS:
            return await refuse(f"Live test budget used ({MAX_LIVE_TESTS} per survey).")
        try:
            row = await engine.probe_genre(q, run.catchment, genre, run.gaps)
        except QlooError as exc:
            return await refuse(f"Qloo test of {genre['name']} failed: {exc}")
        row["source"] = "agent"
        run.explored.append(row)
        await emit("explored", {"row": public_gap(row)})
        return {"tested_live": True, **gap_summary(row), "evidence": gap_evidence(row, run.site.minutes)}

    async def fan_taste(args: dict) -> dict:
        nonlocal fan_checks
        query = str(args.get("category") or "").strip()[:80]
        if fan_checks >= MAX_FAN_CHECKS:
            return await refuse(f"Fan taste budget used ({MAX_FAN_CHECKS} per survey).")
        try:
            genre = await resolve(query) if query else None
            if not genre:
                return await refuse(f"Qloo has no storefront category matching '{query}'.")
            fan_checks += 1
            fans = await fans_of(q, run, genre["id"])
        except QlooError as exc:
            return await refuse(f"Qloo fan taste for '{query}' failed: {exc}")
        brands = [b["name"] for b in fans["brands"]]
        artists = [a["name"] for a in fans["artists"]]
        signature = {e["name"] for e in run.taste.get("distinctive_brands", []) + run.taste.get("distinctive_artists", [])}
        shared = [name for name in brands + artists if name in signature]
        text = f"Local fans of {genre['name']} also love {', '.join(brands[:4]) or 'no brands Qloo knows'}"
        text += f"; artists {', '.join(artists[:3])}." if artists else "."
        if shared:
            text += f" Shared with the area's signature taste: {', '.join(shared)}."
        await emit("finding", {"text": text})
        return {"category": genre["name"], "local_fans_also_love": {"brands": brands, "artists": artists},
                "shared_with_area_signature": shared}

    async def on_call(name: str, args: dict, thought: str | None) -> None:
        if name != "submit_concepts":
            await emit("agent", {"tool": name, "args": args, "thought": thought})

    result = await llm.run_tools(
        CONCEPT_SYSTEM,
        "Evidence pack:\n" + json.dumps(evidence_brief(run), ensure_ascii=False),
        CONCEPT_TOOLS,
        {"inspect_gap": inspect, "local_taste": taste, "test_category": test_category, "fan_taste": fan_taste},
        final_tool="submit_concepts",
        max_steps=10,
        on_call=on_call,
    )
    return clean_concepts(run, (result or {}).get("concepts", []))


async def analyze_site(
    q: QlooClient, walker: CatchmentService, llm: LLM, store: RunStore, site: Site, emit: Emit,
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
            concepts, mode = [], "rules"
            if llm.enabled:
                try:
                    concepts, mode = await agent_concepts(llm, q, run, emit), "agent"
                except Exception as exc:  # LLM outages must not break the demo
                    log.warning("Concept agent failed; falling back to evidence rules", exc_info=True)
                    await emit("notice", {"message": f"LLM unavailable ({type(exc).__name__}); using evidence rules."})
            if not concepts:
                concepts, mode = rule_concepts(run), "rules"
            run.concepts = concepts
            await emit("status", {"step": "concepts", "state": "done", "label": "Designing concepts from the gaps"})
            await emit("concepts", {"concepts": concepts, "mode": mode})
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


DESIGN_SYSTEM = """You are Blank Space's concept designer. Turn a business concept into a design brief for an empty storefront.
Ground every choice in the evidence: design DNA of the locals' favorite places, what local fans of this category also
love, local artists, nearby places and local brands.
Return JSON with keys: name, tagline, concept_statement, interior {mood, materials (list), lighting, layout, seating},
offer (list of 4-6 items), price_level (1-4), hours, music {direction, artists (list, only from local_artists)},
partners (list of {name, why}; name only from nearby_places or partner_brands), launch (string), image_prompt
(a photorealistic interior description with no text, logos or people's faces)."""


async def design_concept(llm: LLM, images: ImageGen, run: RunState, index: int, q: QlooClient | None = None) -> dict:
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
    mode = "rules"
    if llm.enabled:
        try:
            design = await llm.json(DESIGN_SYSTEM, json.dumps({
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
            }, ensure_ascii=False))
            mode = "agent"
        except Exception:
            log.warning("Design brief LLM call failed; using evidence rules", exc_info=True)
            design = {}
    if not design:
        design = rule_design(run, concept, dna, local_artists, fitting_brands, fan_led=bool(fan_artists))
        mode = "rules"
    music = design.get("music") or {}
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
    design["image"] = None
    if images.enabled:
        prompt = design.get("image_prompt") or interior_prompt(run, concept, dna)
        try:
            design["image"] = await images.generate(prompt)
        except Exception:
            log.warning("Interior image generation failed", exc_info=True)
            design["image"] = None
    return design


def interior_prompt(run: RunState, concept: dict, dna: dict) -> str:
    """Image prompt assembled from the favorites' design DNA, used when no LLM wrote one."""
    title = scoring.genre_title(concept["genre"]).lower()
    details = [
        ", ".join(dna.get("ambience", [])[:3]).lower(),
        ", ".join(dna.get("decor", [])[:3]).lower(),
        ", ".join(dna.get("setting", [])[:2]).lower(),
        ", ".join(a.lower() for a in dna.get("amenities", [])[:3]),
    ]
    mood = "; ".join(part for part in details if part)
    return (
        f"Photorealistic interior of a small street-level {title} in {short_label(run.site.label)}, seen from the doorway. "
        f"{mood}. Natural light, real materials, styled for opening day. Architectural photography, 35mm, "
        "no people, no text, no logos, no signage."
    )


def partner_places(run: RunState, genre: str, limit: int = 2) -> list[str]:
    """Well-loved nearby places from other genres, so partners complement rather than compete."""
    candidates = [
        p for p in run.block
        if p.get("name") and genre not in {name for _, name in scoring.genre_tags(p)}
        and any(scoring.is_business_genre(name) for _, name in scoring.genre_tags(p))
    ]
    candidates.sort(key=lambda p: -(p.get("popularity") or 0))
    return [p["name"] for p in candidates[:limit]]


def rule_design(
    run: RunState, concept: dict, dna: dict, artists: list[str], partner_brands: list[str], fan_led: bool = False,
) -> dict:
    ambience = ", ".join(dna.get("ambience", [])[:3]).lower() or "warm and welcoming"
    decor = dna.get("decor", [])[:4]
    minutes = run.site.minutes
    partners = [
        {"name": name, "why": f"Popular inside the {minutes}-minute walk and not a direct competitor; cross-promote."}
        for name in partner_places(run, concept["genre"])
    ]
    if partner_brands:
        partners.append({"name": partner_brands[0], "why": "A brand this area over-indexes on; a natural co-branded launch."})
    cue = run.cues[0].lower() if run.cues else ""
    if cue and not cue.endswith("s"):
        cue += "s"
    return {
        "name": concept["name"],
        "tagline": concept.get("one_liner"),
        "concept_statement": " ".join(concept.get("why_here", [])),
        "interior": {
            "mood": ambience,
            "materials": decor,
            "lighting": "Warm, layered lighting" if "romantic" in ambience or "cozy" in ambience else "Bright, natural light",
            "layout": ", ".join(dna.get("setting", [])[:2]) or "Street-facing, open to the sidewalk",
            "seating": ", ".join(a for a in dna.get("amenities", []) if "seating" in a.lower()) or "Mixed bar and table seating",
        },
        "offer": scoring.signature_items(concept["genre"], dna, limit=6),
        "price_level": concept.get("price_level", 2),
        "hours": "To be set from local foot traffic",
        "music": {
            "direction": (
                f"What local {scoring.genre_title(concept['genre'])} fans also listen to"
                if fan_led else "Built from artists that over-index locally"
            ),
            "artists": artists[:5],
        },
        "partners": partners,
        "launch": f"Opening night with a nod to the neighborhood's love of {cue}." if cue else "Opening night with local partners.",
        "image_prompt": None,
    }


async def plain_llm_concepts(llm: LLM, site: Site) -> list[dict]:
    """What a language model suggests with no data, shown next to the evidence-based concepts."""
    data = await llm.json(
        "You are a retail strategy consultant.",
        f"There is an empty ground-floor storefront at {site.label} (lat {site.lat}, lon {site.lon}). "
        "Propose 3 business concepts likely to succeed there. Return JSON {\"concepts\": [{\"name\", \"genre\", \"one_liner\"}]}.",
    )
    return [c for c in data.get("concepts", []) if isinstance(c, dict)][:3]
