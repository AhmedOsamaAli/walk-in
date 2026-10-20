"""Runs the Blank Space agent for a site: gather evidence, find gaps, propose and design concepts."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from . import engine, scoring
from .llm import LLM
from .qloo import QlooClient, QlooError

Emit = Callable[[str, dict], Awaitable[None]]

PRICE_WORDS = {1: "$", 2: "$$", 3: "$$$", 4: "$$$$"}


@dataclass
class Site:
    lat: float
    lon: float
    label: str
    focus: str = "any"
    notes: str = ""


@dataclass
class RunState:
    id: str
    site: Site
    block: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    genres: list[dict] = field(default_factory=list)
    cues: list[str] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    taste: dict = field(default_factory=dict)
    demographics: dict | None = None
    concepts: list[dict] = field(default_factory=list)


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
    return {
        "site": {"label": run.site.label, "focus": run.site.focus, "owner_notes": run.site.notes or None},
        "walkable_block": {
            "places_scanned": s.get("place_count"),
            "most_common_genres": s.get("top_genres", [])[:8],
            "average_rating": s.get("avg_rating"),
            "price_levels": s.get("price_levels"),
            "what_reviews_praise": [k for k, _ in s.get("praise", [])[:8]],
            "what_reviews_complain_about": [k for k, _ in s.get("complaints", [])[:6]],
            "rising_places": [name for name, _ in s.get("rising", [])[:4]],
            "fading_places": [name for name, _ in s.get("fading", [])[:4]],
        },
        "gap_table": [
            {
                "genre": g["genre"],
                "locals_rank": g["demand_rank"],
                "within_10_min_walk": f"{g['nearby_count']}{'+' if g['nearby_capped'] else ''}",
                "locals_favorites_beyond_walk": f"{g['favorites_far']}/{g['favorites_total']}",
                "median_distance_to_favorites_km": g["median_favorite_km"],
                "gap_score": g["gap_score"],
            }
            for g in run.gaps
        ],
        "taste_cues": run.cues,
        "local_brands": [b["name"] for b in run.taste.get("distinctive_brands", [])],
        "local_artists": [a["name"] for a in run.taste.get("distinctive_artists", [])],
        "crowd": describe_age(run.demographics),
    }


def gap_for(run: RunState, genre: str) -> dict | None:
    wanted = (genre or "").strip().lower()
    return next((g for g in run.gaps if g["genre"].lower() == wanted), None)


def inspect_payload(run: RunState, row: dict) -> dict:
    return {
        "genre": row["genre"],
        "competitors_within_walk": [
            {k: c.get(k) for k in ("name", "rating", "price_level", "praise", "complaints", "distance_m")}
            for c in row["competitors"][:6]
        ],
        "locals_favorites": [
            {"name": f["name"], "km_away": round((f.get("distance_m") or 0) / 1000, 1), "price_level": f.get("price_level"),
             "praise": f.get("praise")}
            for f in row["favorites"][:8]
        ],
        "design_dna_of_favorites": scoring.design_dna(row["_favorite_entities"]),
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
        favorites = {f["name"] for f in row["favorites"] if f.get("name")}
        concept["genre"] = row["genre"]
        concept["genre_id"] = row["genre_id"]
        concept["gap_score"] = row["gap_score"]
        concept["inspired_by"] = ground_names(concept.get("inspired_by"), favorites)[:4]
        try:
            concept["price_level"] = max(1, min(4, int(concept.get("price_level") or 2)))
        except (TypeError, ValueError):
            concept["price_level"] = 2
        concept["evidence"] = gap_evidence(row)
        cleaned.append(concept)
    return cleaned[:3]


def gap_evidence(row: dict) -> list[str]:
    nearby = f"{row['nearby_count']}{'+' if row['nearby_capped'] else ''}"
    lines = [
        f"Locals rank {row['genre']} #{row['demand_rank']} among the place types they engage with.",
        f"{nearby} {row['genre']} places within a 10-minute walk.",
    ]
    if row["favorites_total"]:
        lines.append(
            f"{row['favorites_far']} of locals' {row['favorites_total']} favorite {row['genre']} spots are beyond walking "
            f"distance (median {row['median_favorite_km']} km away)."
        )
    return lines


def rule_concepts(run: RunState) -> list[dict]:
    concepts = []
    for row in run.gaps[:3]:
        dna = scoring.design_dna(row["_favorite_entities"])
        complaints = [c for comp in row["competitors"] for c in comp.get("complaints", [])][:3]
        km = row["median_favorite_km"]
        concepts.append({
            "name": f"The Neighborhood {row['genre']}",
            "genre": row["genre"],
            "genre_id": row["genre_id"],
            "gap_score": row["gap_score"],
            "one_liner": (
                f"{row['genre']}, close to home: locals currently travel {km} km for their favorites."
                if km else f"The {row['genre']} this block is missing."
            ),
            "for_whom": describe_age(run.demographics) or "The people within a 10-minute walk",
            "price_level": dna.get("typical_price_level") or 2,
            "why_here": gap_evidence(row),
            "beat_competitors": (
                f"Nearby reviews flag: {', '.join(complaints)}. Design the service around avoiding these."
                if complaints else "Few direct competitors nearby; win on quality and atmosphere."
            ),
            "signature": dna.get("menu", [])[:3] or dna.get("offerings", [])[:3],
            "inspired_by": [f["name"] for f in row["favorites"][:3]],
            "risk": (
                f"{row['nearby_count']} competitors already nearby." if row["nearby_count"] >= 10
                else "Demand is inferred from taste signals, not foot traffic; validate on site."
            ),
            "evidence": gap_evidence(row),
        })
    return concepts


CONCEPT_SYSTEM = """You are Blank Space, a retail and hospitality strategist that designs businesses for empty storefronts.
You only reason from Qloo evidence about the people within a 10-minute walk of the site.
Use the tools to inspect the most promising gaps (at least two) before deciding.
Then call submit_concepts with exactly 3 distinct concepts, each built on a different genre from the gap table.
Rules: cite numbers from the evidence in why_here; never invent places, brands or statistics;
inspired_by must only contain names returned by inspect_gap; respect the owner's notes."""

CONCEPT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "inspect_gap",
            "description": "Competitors within walking distance (with review praise and complaints) and locals' favorite places of one genre, plus the design DNA of those favorites.",
            "parameters": {
                "type": "object",
                "properties": {"genre": {"type": "string", "description": "Genre exactly as written in the gap table"}},
                "required": ["genre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "local_taste",
            "description": "Brands and artists that over-index in this neighborhood versus the wider metro, plus crowd age skew.",
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
                                "genre": {"type": "string", "description": "Genre exactly as written in the gap table"},
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


async def agent_concepts(llm: LLM, run: RunState, emit: Emit) -> list[dict]:
    async def inspect(args: dict) -> dict:
        row = gap_for(run, args.get("genre", ""))
        return inspect_payload(run, row) if row else {"error": "Unknown genre. Use one from the gap table."}

    async def taste(_: dict) -> dict:
        return {
            "local_brands": [b["name"] for b in run.taste.get("brands", [])],
            "distinctive_brands": [b["name"] for b in run.taste.get("distinctive_brands", [])],
            "local_artists": [a["name"] for a in run.taste.get("distinctive_artists", [])],
            "crowd": describe_age(run.demographics),
        }

    async def on_call(name: str, args: dict, thought: str | None) -> None:
        if name != "submit_concepts":
            await emit("agent", {"tool": name, "args": args, "thought": thought})

    result = await llm.run_tools(
        CONCEPT_SYSTEM,
        "Evidence pack:\n" + json.dumps(evidence_brief(run), ensure_ascii=False),
        CONCEPT_TOOLS,
        {"inspect_gap": inspect, "local_taste": taste},
        final_tool="submit_concepts",
        on_call=on_call,
    )
    return clean_concepts(run, (result or {}).get("concepts", []))


async def analyze_site(q: QlooClient, llm: LLM, store: RunStore, site: Site, emit: Emit) -> RunState:
    run = RunState(id=uuid.uuid4().hex[:12], site=site)
    started, calls_before, hits_before = time.time(), q.calls, q.cache_hits
    await emit("run", {"run_id": run.id, "site": site.__dict__, "llm": llm.enabled, "image": bool(llm.image_model)})

    async def step(name: str, label: str, coro):
        await emit("status", {"step": name, "state": "running", "label": label})
        result = await coro
        await emit("status", {"step": name, "state": "done", "label": label})
        return result

    try:
        block, (genres, cues), taste = await asyncio.gather(
            step("block", "Reading every place within a 10-minute walk", engine.scan_block(q, site.lat, site.lon)),
            step("demand", "Learning what people around here engage with", engine.demand_genres(q, site.lat, site.lon)),
            step("taste", "Comparing local brands and artists with the wider city", engine.local_taste(q, site.lat, site.lon)),
        )
        run.block, run.genres, run.cues, run.taste = block, genres, cues, taste
        run.summary = scoring.summarize_block(block)
        await emit("block", {
            "summary": run.summary,
            "places": [scoring.place_card(p, (site.lat, site.lon)) for p in block],
        })
        await emit("demand", {"genres": genres[:12], "cues": cues})

        gaps, demographics = await asyncio.gather(
            step("gaps", "Checking supply nearby and where locals travel for their favorites",
                 engine.gap_table(q, site.lat, site.lon, genres, site.focus)),
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
                    concepts, mode = await agent_concepts(llm, run, emit), "agent"
                except Exception as exc:  # LLM outages must not break the demo
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
Ground every choice in the evidence: design DNA of the locals' favorite places, local artists, nearby places and local brands.
Return JSON with keys: name, tagline, concept_statement, interior {mood, materials (list), lighting, layout, seating},
offer (list of 4-6 items), price_level (1-4), hours, music {direction, artists (list, only from local_artists)},
partners (list of {name, why}; name only from nearby_places or local_brands), launch (string), image_prompt
(a photorealistic interior description with no text, logos or people's faces)."""


async def design_concept(llm: LLM, run: RunState, index: int) -> dict:
    concept = run.concepts[index]
    row = gap_for(run, concept["genre"])
    dna = scoring.design_dna(row["_favorite_entities"]) if row else {}
    local_artists = [a["name"] for a in run.taste.get("distinctive_artists", []) + run.taste.get("artists", [])]
    nearby = [p.get("name") for p in run.block if p.get("name")]
    brands = [b["name"] for b in run.taste.get("distinctive_brands", []) + run.taste.get("brands", [])]
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
                "local_brands": brands[:15],
                "taste_cues": run.cues,
                "crowd": describe_age(run.demographics),
            }, ensure_ascii=False))
            mode = "agent"
        except Exception:
            design = {}
    if not design:
        design = rule_design(run, concept, dna, local_artists, nearby, brands)
        mode = "rules"
    music = design.get("music") or {}
    music["artists"] = ground_names(music.get("artists"), set(local_artists))[:6]
    design["music"] = music
    allowed_partners = {name.lower(): name for name in set(nearby) | set(brands)}
    design["partners"] = [
        {**p, "name": allowed_partners[p["name"].lower()]}
        for p in design.get("partners") or []
        if isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"].lower() in allowed_partners
    ][:4]
    design["dna"] = dna
    design["mode"] = mode
    design["image"] = None
    if llm.image_model and design.get("image_prompt"):
        try:
            design["image"] = await llm.image(design["image_prompt"])
        except Exception:
            design["image"] = None
    return design


def partner_places(run: RunState, genre: str, limit: int = 2) -> list[str]:
    """Well-loved nearby places from other genres, so partners complement rather than compete."""
    candidates = [
        p for p in run.block
        if p.get("name") and genre not in {name for _, name in scoring.genre_tags(p)}
        and any(scoring.is_business_genre(name) for _, name in scoring.genre_tags(p))
    ]
    candidates.sort(key=lambda p: -(p.get("popularity") or 0))
    return [p["name"] for p in candidates[:limit]]


def rule_design(run: RunState, concept: dict, dna: dict, artists: list[str], nearby: list[str], brands: list[str]) -> dict:
    ambience = ", ".join(dna.get("ambience", [])[:3]).lower() or "warm and welcoming"
    decor = dna.get("decor", [])[:4]
    partners = [{"name": name, "why": "Popular within a 10-minute walk; cross-promote."} for name in partner_places(run, concept["genre"])]
    distinctive_brands = run.taste.get("distinctive_brands") or []
    if distinctive_brands:
        partners.append({"name": distinctive_brands[0]["name"], "why": "Over-indexes in this neighborhood."})
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
        "offer": (dna.get("menu") or dna.get("offerings") or [])[:6],
        "price_level": concept.get("price_level", 2),
        "hours": "To be set from local foot traffic",
        "music": {"direction": "Built from artists that over-index locally", "artists": artists[:5]},
        "partners": partners,
        "launch": f"Opening night themed around the neighborhood's love of {run.cues[0].lower()}." if run.cues
        else "Opening night with local partners.",
        "image_prompt": None,
    }


async def plain_llm_concepts(llm: LLM, site: Site) -> list[dict]:
    """What a language model suggests with no data, shown next to the evidence-based concepts."""
    data = await llm.json(
        "You are a retail strategy consultant.",
        f"There is an empty ground-floor storefront at {site.label} (lat {site.lat}, lon {site.lon}). "
        "Propose 3 business concepts likely to succeed there. Return JSON {\"concepts\": [{\"name\", \"genre\", \"one_liner\"}]}.",
        temperature=0.7,
    )
    return [c for c in data.get("concepts", []) if isinstance(c, dict)][:3]
