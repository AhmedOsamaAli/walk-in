"""Business concepts for a site: the agent with live Qloo tools, the evidence rules behind it, and the
grounding that keeps both to what the evidence says."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .. import engine, scoring
from ..answers import AnswerCache, fingerprint
from ..llm import LLM, LLMUnavailable
from ..qloo import QlooClient, QlooError
from .evidence import (
    describe_age,
    evidence_brief,
    gap_evidence,
    gap_for,
    gap_summary,
    inspect_payload,
    public_gap,
    short_label,
    storefront_favorites,
)
from .experience import fans_of
from .models import Emit, RunState, Site

log = logging.getLogger("blankspace")


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
