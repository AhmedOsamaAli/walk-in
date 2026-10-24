"""Head-to-head: a plain chatbot's top pick versus Walk-in's top gap, on 15 real storefronts.

Run from the repo root, with PYTHONPATH set to it and PYTHONIOENCODING=utf-8:

    .venv\\Scripts\\python.exe <this file> [sites|chat|data|osm|report|all] [--force] [--only SITE_ID]

  sites   geocodes the 15 pre-registered storefront addresses (OpenStreetMap Nominatim)    -> sites.json
  chat    one plain-chatbot call per site on the app's own LLM settings, no system prompt -> _cache/chat.json
          (at most 40 LLM calls in total, counted across reruns; answers are reused)
  data    Walk-in's data pipeline with no LLM; both sides' picks measured the same way     -> _cache/data/<site>.json
  osm     OpenStreetMap's count of each measured kind inside the walk, with retries        -> _cache/osm/<site>.json
  report  the metrics                                                                     -> results.json, report.md

Nothing in the repo changes: Qloo, Valhalla and Overpass answers land in the app's own caches (.cache/). The LLM keys
are read through app.config.settings and are never printed or written.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median

REPO = Path.cwd()
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import httpx  # noqa: E402
from openai import APIConnectionError, APIStatusError, AsyncOpenAI  # noqa: E402

from app import engine, osm  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import default_services  # noqa: E402
from app.qloo import QlooError  # noqa: E402

OUT = Path(__file__).resolve().parent
CACHE = OUT / "_cache"
STATUS = OUT / "STATUS.md"

MINUTES = 10
MAX_LLM_CALLS = 40
PACE_S = 6.0  # between chatbot calls, to stay under per-minute free-tier limits
OVER, UNDER = 1.2, 0.8  # relative supply: over-supplied at or above, under-supplied at or below
TOP_DEMAND = 15  # "people here rank it in their top 15 place types"
OSM_MAX_M2 = 30e6  # the app's own limit for asking Overpass about an area
# The app's public Overpass instances, plus the French community instance (worldwide data), which was the only one
# answering during this run; each scan records which instance answered and how fresh its data was.
OVERPASS = ("https://overpass.openstreetmap.fr/api/interpreter", *osm.ENDPOINTS)

PROMPT = (
    "I have an empty storefront at {address}. What kind of business should open there? Give your single top pick as a "
    "short business category, then two alternatives, one line each."
)

# ---------------------------------------------------------------------------------------------------------------------
# The sites, fixed before any chatbot answer or Walk-in result was seen. Each is a storefront address on a commercial
# street; 'search' is geocoded forward, 'reverse' is a point on the street whose nearest address Nominatim names, and
# 'number' must come back as the house number. The streets are a deliberate mix: trendy strips, immigrant and
# working-class high streets, a Tokyo shotengai, a Cairo commercial road.
# ---------------------------------------------------------------------------------------------------------------------
SITES = [
    dict(id="chicago", name="Milwaukee Ave, Wicker Park", city="Chicago", country="United States",
         continent="North America", street="trendy shopping and nightlife strip",
         address="1550 N Milwaukee Ave, Chicago, IL 60622, USA",
         search="1550 N Milwaukee Ave, Chicago, IL 60622, USA", number="1550"),
    dict(id="new-york", name="37th Ave, Jackson Heights", city="New York", country="United States",
         continent="North America", street="immigrant commercial avenue (Queens)",
         address="82-12 37th Ave, Jackson Heights, Queens, NY 11372, USA",
         reverse=(40.74975, -73.88380), number="82-12", road="37th Avenue"),
    dict(id="austin", name="South Congress Ave", city="Austin", country="United States",
         continent="North America", street="tourist and boutique strip",
         address="1600 S Congress Ave, Austin, TX 78704, USA",
         search="1600 S Congress Ave, Austin, TX 78704, USA", number="1600"),
    dict(id="los-angeles", name="Cesar E Chavez Ave, Boyle Heights", city="Los Angeles", country="United States",
         continent="North America", street="Latino neighbourhood commercial avenue",
         address="1900 E Cesar E Chavez Ave, Los Angeles, CA 90033, USA",
         search="1900 E Cesar E Chavez Ave, Los Angeles, CA 90033, USA", number="1900"),
    dict(id="mexico-city", name="Av. Álvaro Obregón, Roma Norte", city="Mexico City", country="Mexico",
         continent="North America", street="trendy avenue",
         address="Avenida Álvaro Obregón 130, Roma Norte, 06700 Mexico City, Mexico",
         search="Avenida Álvaro Obregón 130, Roma Norte, 06700 Ciudad de México, Mexico", number="130"),
    dict(id="london", name="Upper Street, Islington", city="London", country="United Kingdom",
         continent="Europe", street="affluent high street",
         address="150 Upper Street, Islington, London N1, UK",
         search="150 Upper Street, London N1 1RA, UK", number="150"),
    dict(id="paris", name="Rue Oberkampf, 11e", city="Paris", country="France",
         continent="Europe", street="nightlife street",
         address="110 Rue Oberkampf, 75011 Paris, France",
         search="110 Rue Oberkampf, 75011 Paris, France", number="110"),
    dict(id="berlin", name="Karl-Marx-Straße, Neukölln", city="Berlin", country="Germany",
         continent="Europe", street="working-class high street",
         address="Karl-Marx-Straße 100, 12043 Berlin, Germany",
         search="Karl-Marx-Straße 100, 12043 Berlin, Germany", number="100"),
    dict(id="madrid", name="Calle de Fuencarral, Malasaña", city="Madrid", country="Spain",
         continent="Europe", street="shopping street",
         address="Calle de Fuencarral 100, 28004 Madrid, Spain",
         search="Fuencarral 100, 28004 Madrid, Spain", number="100"),
    dict(id="cairo", name="Road 9, Maadi", city="Cairo", country="Egypt",
         continent="Africa", street="neighbourhood commercial road",
         address="96 Road 9, Maadi, Cairo, Egypt",
         reverse=(29.9618210, 31.2571530), number="96", road="Street 9"),
    dict(id="singapore", name="Joo Chiat Road", city="Singapore", country="Singapore",
         continent="Asia", street="shophouse street",
         address="263 Joo Chiat Road, Singapore",
         search="263 Joo Chiat Road, Singapore", number="263"),
    dict(id="tokyo", name="Togoshi Ginza shopping street", city="Tokyo", country="Japan",
         continent="Asia", street="traditional shopping street (shotengai)",
         address="Togoshi Ginza Street, 2-chōme Hiratsuka, Shinagawa City, Tokyo 142-0051, Japan",
         reverse=(35.61618, 139.71300), number=None, road="Togoshi Ginza Street"),
    dict(id="sydney", name="King Street, Newtown", city="Sydney", country="Australia",
         continent="Oceania", street="inner-city main street",
         address="280 King Street, Newtown NSW 2042, Australia",
         reverse=(-33.8961041, 151.1806814), number="280", road="King Street"),
    dict(id="melbourne", name="Sydney Road, Brunswick", city="Melbourne", country="Australia",
         continent="Oceania", street="multicultural strip",
         address="400 Sydney Road, Brunswick VIC 3056, Australia",
         search="400 Sydney Road, Brunswick VIC 3056, Australia", number="400"),
    dict(id="buenos-aires", name="Honduras, Palermo Soho", city="Buenos Aires", country="Argentina",
         continent="South America", street="boutique and nightlife district",
         address="Honduras 4800, Palermo Soho, Buenos Aires, Argentina",
         search="Honduras 4800, Palermo, Buenos Aires, Argentina", number="4800"),
]

NOMINATIM = "https://nominatim.openstreetmap.org"
USER_AGENT = "Walk-in-eval/0.1 (hackathon evaluation; +https://github.com/AhmedOsamaAli/walk-in)"


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def status(message: str) -> None:
    with STATUS.open("a", encoding="utf-8") as handle:
        handle.write(f"- {datetime.now().strftime('%H:%M')} {message}\n")
    print(f"[status] {message}", flush=True)


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------------------------------------------------
# 1. Sites
# ---------------------------------------------------------------------------------------------------------------------

def _number_matches(expected: str | None, found: str | None) -> bool:
    """Whether the geocoder's house number is the one asked for: the same, one of a list, or a range around it
    ('298-300' for 300)."""
    if expected is None:
        return True
    if not found:
        return False
    if found == expected or expected in re.split(r"\s*[;,/]\s*", found):
        return True
    span = re.fullmatch(r"(\d+)\s*-\s*(\d+)", found)
    return bool(span and expected.isdigit() and int(span.group(1)) <= int(expected) <= int(span.group(2)))


async def run_sites(force: bool) -> list[dict]:
    path = OUT / "sites.json"
    if path.exists() and not force:
        return load(path, [])
    out = []
    async with httpx.AsyncClient(base_url=NOMINATIM, headers={"User-Agent": USER_AGENT}, timeout=20) as http:
        for spec in SITES:
            if "search" in spec:
                response = await http.get("/search", params={
                    "q": spec["search"], "format": "jsonv2", "limit": 5, "addressdetails": 1, "accept-language": "en",
                })
                response.raise_for_status()
                hits = [h for h in response.json() if _number_matches(spec["number"], (h.get("address") or {}).get("house_number"))]
                hit, method = (hits[0] if hits else None), "search"
            else:
                lat, lon = spec["reverse"]
                response = await http.get("/reverse", params={
                    "lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18, "addressdetails": 1, "accept-language": "en",
                })
                response.raise_for_status()
                hit, method = response.json(), "reverse"
                address = hit.get("address") or {}
                if (spec.get("road") and spec["road"] not in (address.get("road") or "")) or not _number_matches(
                    spec["number"], address.get("house_number")
                ):
                    hit = None
            if not hit:
                raise SystemExit(f"{spec['id']}: the geocoder did not confirm {spec['address']!r}; fix the site list first")
            address = hit.get("address") or {}
            out.append({
                "id": spec["id"], "name": spec["name"], "city": spec["city"], "country": spec["country"],
                "continent": spec["continent"], "street": spec["street"], "address": spec["address"],
                "lat": round(float(hit["lat"]), 7), "lon": round(float(hit["lon"]), 7),
                "geocoder": {
                    "service": "OpenStreetMap Nominatim", "method": method,
                    "query": spec.get("search") or list(spec["reverse"]),
                    "label": hit.get("display_name"), "house_number": address.get("house_number"),
                    "road": address.get("road"), "osm": f"{hit.get('osm_type')}/{hit.get('osm_id')}",
                    "what": f"{hit.get('category')}={hit.get('type')}",
                },
            })
            print(f"{spec['id']:13} {out[-1]['lat']:.6f},{out[-1]['lon']:.6f}  {hit.get('display_name', '')[:90]}", flush=True)
            await asyncio.sleep(1.2)  # Nominatim's policy: at most one request a second
    save(path, out)
    status(f"sites.json written: {len(out)} storefronts, {len({s['city'] for s in out})} cities, "
           f"{len({s['continent'] for s in out})} continents (fixed before any result was seen).")
    return out


# ---------------------------------------------------------------------------------------------------------------------
# 2. The plain chatbot
# ---------------------------------------------------------------------------------------------------------------------

RETRY_IN = re.compile(r"(?:retry in|try again in|retryDelay\W+)\s*((?:\d+(?:\.\d+)?(?:ms|h|m|s))+)")
DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
SECONDS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def failure(exc: Exception) -> tuple[str, float | None]:
    """A short description that carries nothing from the request, and how long the model should rest (None: not again
    in this run)."""
    if isinstance(exc, APIStatusError):
        code, text = exc.status_code, str(exc)
        if code == 429:
            if re.search(r"PerDay|per day", text, re.IGNORECASE):
                return "HTTP 429 (daily quota)", None
            match = RETRY_IN.search(text)
            delay = sum(float(a) * SECONDS[u] for a, u in DURATION.findall(match.group(1))) if match else 60.0
            return "HTTP 429 (rate limit)", min(300.0, delay + 1.0)
        if code in (403, 404):
            return f"HTTP {code} (model not offered)", None
        if code >= 500:
            return f"HTTP {code} (overloaded)", 120.0
        return f"HTTP {code}", None
    return type(exc).__name__, 30.0


def chat_routes() -> tuple[list[tuple[str, str, AsyncOpenAI, dict]], list[AsyncOpenAI]]:
    """The app's chain: the main model, then settings.llm_fallback_models on the same endpoint; Groq's models (the
    app's own last resort) only when every one of those fails."""
    routes, clients = [], []
    if settings.llm_api_key:
        main = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, max_retries=0,
                           timeout=settings.llm_timeout)
        clients.append(main)
        options = {}
        if settings.llm_temperature is not None:
            options["temperature"] = settings.llm_temperature
        if settings.llm_reasoning_effort:
            options["reasoning_effort"] = settings.llm_reasoning_effort
        for model in (settings.llm_model, *settings.llm_fallback_models):
            routes.append(("main", model, main, options))
    if settings.groq_api_key:
        groq = AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url, max_retries=0,
                           timeout=settings.llm_timeout)
        clients.append(groq)
        options = {"reasoning_effort": settings.groq_reasoning_effort} if settings.groq_reasoning_effort else {}
        for model in settings.groq_models:
            routes.append(("groq", model, groq, options))
    return routes, clients


async def run_chat(sites: list[dict], force: bool, only: str | None) -> dict:
    path = CACHE / "chat.json"
    state = load(path, {"llm_calls": 0, "answers": {}, "failures": []})
    routes, clients = chat_routes()
    if not routes:
        raise SystemExit("No LLM key is configured.")
    resting: dict[str, float] = {}
    finished: set[str] = set()
    try:
        for site in sites:
            if only and site["id"] != only:
                continue
            if site["id"] in state["answers"] and not force:
                continue
            prompt = PROMPT.format(address=site["address"])
            attempts, answer = [], None
            for provider, model, client, options in routes:
                if model in finished or resting.get(model, 0.0) > time.monotonic():
                    continue
                if state["llm_calls"] >= MAX_LLM_CALLS:
                    status(f"LLM budget of {MAX_LLM_CALLS} calls reached; {site['id']} has no chatbot answer.")
                    break
                state["llm_calls"] += 1
                save(path, state)  # counted before the call, so a crash cannot hide one
                started = time.monotonic()
                try:
                    response = await client.chat.completions.create(
                        model=model, messages=[{"role": "user", "content": prompt}], **options,
                    )
                except (APIStatusError, APIConnectionError) as exc:
                    what, rest = failure(exc)
                    attempts.append({"provider": provider, "model": model, "error": what})
                    if rest is None:
                        finished.add(model)
                    else:
                        resting[model] = time.monotonic() + rest
                    print(f"  {site['id']}: {model} failed ({what}); trying the next model", flush=True)
                    continue
                text = (response.choices[0].message.content or "").strip() if response.choices else ""
                if not text:
                    attempts.append({"provider": provider, "model": model, "error": "empty reply"})
                    resting[model] = time.monotonic() + 30.0
                    continue
                usage = response.usage
                answer = {
                    "text": text, "provider": provider, "model": model, "answered_at": now_text(),
                    "seconds": round(time.monotonic() - started, 1), "attempts": attempts, "prompt": prompt,
                    "options": dict(options),
                    "tokens": {"prompt": usage.prompt_tokens, "completion": usage.completion_tokens} if usage else None,
                }
                break
            if answer is None:
                state["failures"].append({"site": site["id"], "at": now_text(), "attempts": attempts})
                status(f"chat {site['id']}: no model answered ({attempts}).")
            else:
                state["answers"][site["id"]] = answer
                first_line = text.splitlines()[0][:80]
                print(f"{site['id']:13} {model:24} {first_line}", flush=True)
            save(path, state)
            if state["llm_calls"] >= MAX_LLM_CALLS:
                break
            await asyncio.sleep(PACE_S)
    finally:
        for client in clients:
            await client.close()
    answered = len(state["answers"])
    models = Counter(a["model"] for a in state["answers"].values())
    status(f"chat: {answered} answers, {state['llm_calls']} LLM calls used of {MAX_LLM_CALLS}; models {dict(models)}.")
    return state


# ---------- Parsing the chatbot's answer ----------

EMPHASIS = re.compile(r"\*\*|__|`|~~|\*")
LEAD = re.compile(r"^\s*(?:[-*•·▪►➤→>]+|\(?\d+\s*[.)]|\(?[a-cA-C][.)]|#{1,6})\s*")
LABEL = re.compile(
    r"^(?P<label>(?:(?:my|the|your|a)\s+)?(?:single\s+)?(?:top|best|first|main|primary|#1)\s*"
    r"(?:pick|choice|recommendation|suggestion|bet|option|idea)?"
    r"|recommendation|recommended(?:\s+business)?"
    r"|(?:two\s+|other\s+|the\s+)?alternatives?|alt\.?|option|runners?[- ]up"
    r"|second(?:ary)?(?:\s+(?:pick|choice|option))?|third(?:\s+(?:pick|choice|option))?|backup(?:\s+(?:pick|option))?)"
    r"(?:\s*(?:#\s*)?(?:\d|one|two))?"
    r"(?:\s+(?:for|in|at|on|here|this|that|the|your|spot|location|address|storefront|site|space|block|area|street)\b){0,4}"
    r"(?:\s*[:\-–—.)]+\s*|\s+(?:is|would\s+be|=)\s+(?:an?\s+)?|\s*$)",
    re.IGNORECASE,
)
TOP_LABEL = re.compile(r"^(?:(?:my|the|your|a)\s+)?(?:single\s+)?(?:top|best|first|main|primary|#1)|^recommend",
                       re.IGNORECASE)
SEPARATOR = re.compile(r"\s+[–—-]\s+|\s*:\s+|\s+\(|\s+because\b|\.\s+|;\s+|\s+[–—]\s*|\s*—\s*", re.IGNORECASE)
# Where a sentence-style answer ('A highly curated, independent bookstore focusing on ...') stops naming the business.
CLAUSE = re.compile(r"\s+(?:focusing|focused|with|that|which|offering|featuring|serving|specializing|specialising|"
                    r"catering|where|aimed|targeting|designed)\b", re.IGNORECASE)
ARTICLE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)


def clean_line(raw: str) -> str:
    line = LEAD.sub("", raw.strip())
    line = EMPHASIS.sub("", line).strip()
    return LEAD.sub("", line).strip()


def category_of(text: str) -> str:
    """The business named at the start of a line. In a sentence ('A stylish, gender-neutral hair salon with ...') the
    adjectives before the last comma are dropped; in a label line ('Coffee shop, open early') what follows is."""
    part = SEPARATOR.split(text.strip(), maxsplit=1)[0]
    sentence = bool(ARTICLE.match(part))
    part = ARTICLE.sub("", CLAUSE.split(part, maxsplit=1)[0])
    if "," in part:
        pieces = [piece.strip() for piece in part.split(",") if piece.strip()]
        part = pieces[-1] if sentence else pieces[0]
    return part.strip(" \t.,:;!-–—\"'“”‘’")


def parse_answer(text: str) -> list[str]:
    """[top pick, first alternative, second alternative] as short categories, from a free-text answer: the line
    labelled as the top pick (or, without labels, the first short line), then the lines after the alternatives label
    (or, without one, the lines after the top pick). Headers and lines ending in a colon are skipped."""
    rows = []
    for raw in (text or "").splitlines():
        line = clean_line(raw)
        if not line:
            continue
        match = LABEL.match(line)
        kind = ("top" if TOP_LABEL.match(match.group("label")) else "alt") if match else None
        rows.append((kind, line[match.end():].strip() if match else line, line))
    labelled_top = any(kind == "top" for kind, _, _ in rows)
    top_index, top, expecting_top = None, None, False
    for index, (kind, rest, line) in enumerate(rows):
        if kind and not rest:
            expecting_top = kind == "top"
            continue
        if kind is None and line.endswith(":"):
            continue
        if labelled_top and not (kind == "top" or expecting_top):
            continue  # preamble before the labelled top pick
        category = category_of(rest)
        if not labelled_top and (kind == "alt" or len(category.split()) > 8):
            continue  # a sentence, not a category
        if category:
            top_index, top = index, category
            break
    if top is None:
        return []
    alt_index = next((i for i, (kind, _, _) in enumerate(rows) if kind == "alt" and i > top_index), None)
    alternatives: list[str] = []
    for kind, rest, line in rows[alt_index if alt_index is not None else top_index + 1:]:
        if (kind and not rest) or kind == "top" or (kind is None and line.endswith(":")):
            continue
        category = category_of(rest)
        if category:
            alternatives.append(category)
        if len(alternatives) == 2:
            break
    return [top, *alternatives]


# ---------------------------------------------------------------------------------------------------------------------
# 3-4. Walk-in's pick and both sides measured the same way (no LLM)
# ---------------------------------------------------------------------------------------------------------------------

FIELDS = (
    "genre", "genre_id", "demand_rank", "ref_rank", "nearby_count", "nearby_capped", "around_count", "around_capped",
    "expected_nearby", "relative_supply", "gap_score", "evidence", "lift", "leakage", "favorites_kind",
    "favorites_total", "favorites_far",
)
# Words that only describe a category's style, dropped when a business has no entry in the keyword table.
QUALIFIERS = {
    "specialty", "speciality", "artisan", "artisanal", "upscale", "boutique", "neighborhood", "neighbourhood", "modern",
    "fast-casual", "healthy", "premium", "independent", "local", "trendy", "high-end", "gourmet", "authentic",
    "contemporary", "small", "cozy", "cosy", "family-friendly", "all-day", "third-wave", "curated", "concept",
    "chic", "elevated", "quick-service", "counter-service", "community", "hip", "stylish", "casual", "craft", "design",
    "lifestyle", "experiential", "late-night", "daytime", "intimate", "affordable", "budget", "luxury", "new", "fresh",
    "sustainable", "niche", "clean", "gender-neutral", "highly", "fusion",
}
CONJUNCTION = re.compile(r"\s*(?:&|\+|/|\band\b|\bwith\b|\bplus\b|\bor\b|,|\s[–—-]\s)\s*", re.IGNORECASE)

# The businesses a chatbot names, as the Qloo place genre each one is. Fixed from the chatbot's vocabulary and Qloo's
# genre names (checked with engine.find_genre), never from Walk-in's results. Read in order, first match wins, so
# specific entries come first; None marks a kind of shop Qloo has no specific place genre for (home decor, groceries,
# concept stores: its resolver offers only the generic 'Store').
LEXICON: tuple[tuple[str, str | None], ...] = (
    (r"\bwine bar\b", "Wine bar"),
    (r"\bwine (?:shop|store)\b|\bbottle shop\b", "Wine store"),
    (r"\bcocktail", "Cocktail bar"),
    (r"\btapas\b", "Tapas bar"),
    (r"\bsmall plates\b", "Small plates"),
    (r"\btea ?(?:bar|house|room|shop)\b", "Tea house"),
    (r"\bbubble tea\b|\bboba\b", "Bubble tea"),
    (r"\bjuice\b|\bsmoothie", "Juice shop"),
    (r"\bcoffee", "Coffee shop"),
    (r"\bcafe\b|\bcafes\b", "Cafe"),
    (r"\bbakery\b|\bbakeries\b|\bpanaderia\b|\bboulangerie\b", "Bakery"),
    (r"\bpatisserie\b|\bpastry\b", "Patisserie"),
    (r"\bbrunch\b", "Brunch"),
    (r"\bsandwich", "Sandwich shop"),
    (r"\bdeli\b|\bdelicatessen\b", "Deli"),
    (r"\bstreet food\b", "Street food"),
    (r"\basian\b", "Asian fusion"),
    (r"\btake-?away\b|\btake-?out\b", "Takeout"),
    (r"\bhealth food\b", "Health food"),
    (r"\bvinyl\b|\brecord (?:store|shop)\b|\brecords\b", "Record store"),
    (r"\bbook ?(?:store|shop)s?\b|\bbooks\b", "Book store"),
    (r"\bvintage\b|\bthrift\b|\bsecond-?hand\b", "Vintage clothing store"),
    (r"\bplants?\b", "Plant nursery"),
    (r"\bflorist\b|\bflowers?\b", "Florist"),
    (r"\bgifts?\b", "Gift shop"),
    (r"\bantique", "Antique store"),
    (r"\bbeauty salon\b", "Beauty salon"),
    (r"\bcosmetic|\bbeauty\b|\bskin ?care\b|\bfragrance|\bperfume", "Cosmetics store"),
    (r"\bstreetwear\b|\bapparel\b|\bclothing\b|\bclothes\b|\bfashion\b", "Clothing store"),
    (r"\bshoes?\b|\bsneakers?\b", "Shoe store"),
    (r"\bpilates\b", "Pilates studio"),
    (r"\byoga\b", "Yoga studio"),
    (r"\bgym\b|\bfitness\b", "Gym"),
    (r"\bhealth\b|\bvitamins?\b|\bsupplements?\b", "Vitamin store"),
    (r"\bwellness\b", "Wellness center"),
    (r"\bbarber", "Barber shop"),
    (r"\bhair\b|\bsalon\b", "Hair salon"),
    (r"\bco-?working\b", "Coworking space"),
    (r"\bice cream\b|\bgelato\b", "Ice cream shop"),
    (r"\bbagel", "Bagel shop"),
    (r"\bramen\b", "Ramen"),
    (r"\bhome ?decor\b|\bhomewares?\b|\bhome goods\b|\bhousewares\b|\binteriors?\b|\bfurniture\b", None),
    (r"\bgrocer|\bgourmet food\b|\bspecialty food\b|\bpantry\b", None),
    (r"\bconcept store\b|\blifestyle\b|\beveryday goods\b|\bzakka\b|\bdesign\b|\bretail\b|\bhub\b", None),
    (r"\bmarket\b", "Market"),
    (r"\bboutique\b", "Boutique"),
)


def fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def plain(value: str) -> str:
    return " ".join(word for word in value.split() if word.lower().strip(",") not in QUALIFIERS)


def components(text: str) -> list[str]:
    """The businesses a combined category names, in order: 'Specialty Coffee & Artisanal Bakery Concept' ->
    ['Specialty Coffee', 'Artisanal Bakery Concept']."""
    no_paren = re.sub(r"\s*\(.*?\)\s*", " ", text)
    return [part.strip(" ,.-") for part in CONJUNCTION.split(no_paren) if part.strip(" ,.-")]


def lexicon_entry(component: str) -> tuple[str, str | None] | None:
    lowered = fold(component).lower()
    return next(((pattern, genre) for pattern, genre in LEXICON if re.search(pattern, lowered)), None)


def faithful(query: str, genre: dict) -> bool:
    """A resolver match that adds no words the chatbot did not say: the same kind or a broader one ('Ramen bar' ->
    'Ramen'), never a more specific one ('Vinyl' -> 'Vinyl Sign Shop')."""
    wanted, name = engine._normalize_genre(query), engine._normalize_genre(genre["name"])
    return engine._match_quality(wanted, name) in (1, 3) or wanted.replace(" ", "") == name.replace(" ", "")


async def resolve(q, genres: list[dict], query: str) -> tuple[dict | None, str | None]:
    try:
        return await engine.find_genre(q, genres, query)
    except QlooError as exc:
        return None, f"Qloo error: {str(exc)[:120]}"


async def map_component(q, genres: list[dict], component: str) -> dict:
    """One named business as a Qloo place genre: through the keyword table, or else the resolver on the words as
    written (then without style words), keeping only faithful matches."""
    entry = lexicon_entry(component)
    if entry is not None:
        pattern, canonical = entry
        if canonical is None:
            return {"text": component, "via": f"table: /{pattern}/ has no Qloo place genre", "query": None,
                    "genre": None, "reason": "Qloo has no specific place genre for this kind of shop."}
        genre, reason = await resolve(q, genres, canonical)
        return {"text": component, "via": f"table: /{pattern}/", "query": canonical, "genre": genre, "reason": reason}
    tried = []
    for query in dict.fromkeys(value for value in (component, fold(component), plain(fold(component))) if value):
        genre, reason = await resolve(q, genres, query)
        if genre and not faithful(query, genre):
            tried.append(f"{query!r} -> {genre['name']!r} rejected (adds words)")
            continue
        if genre:
            return {"text": component, "via": "resolver, as written" if query == component else "resolver, plain",
                    "query": query, "genre": genre, "reason": None, "tried": tried}
        tried.append(f"{query!r}: {reason}")
    return {"text": component, "via": "resolver", "query": None, "genre": None, "reason": "; ".join(tried)}


def measure(row: dict) -> dict:
    return {key: row.get(key) for key in FIELDS}


async def measure_text(q, catchment, genres: list[dict], rows: list[dict], text: str) -> dict:
    """A chatbot category measured the way Walk-in's pick is. Every business it names is mapped to a Qloo place genre
    and probed on the gap table's own supply baseline; the first one that maps is the reading the metrics use, and the
    least crowded one is a sensitivity reading in the chatbot's favour. The resolver's verdict on the literal wording
    is kept too."""
    literal, literal_reason = await resolve(q, genres, text)
    out = {"literal": {"genre": literal["name"] if literal else None, "reason": literal_reason}, "components": []}
    probed: dict[str, dict] = {}
    for component in components(text):
        mapped = await map_component(q, genres, component)
        genre = mapped.pop("genre")
        entry = {**mapped, "genre": genre["name"] if genre else None, "qloo": None}
        if genre:
            if genre["id"] not in probed:
                probed[genre["id"]] = measure(await engine.probe_genre(q, catchment, genre, rows))
            entry["qloo"] = probed[genre["id"]]
            entry["walkin_table_position"] = next(
                (i for i, r in enumerate(rows, 1) if r["genre_id"] == genre["id"]), None
            )
        out["components"].append(entry)
    mapped = [c for c in out["components"] if c["qloo"]]
    out["qloo"] = mapped[0]["qloo"] if mapped else None
    out["mapped_from"] = mapped[0]["text"] if mapped else None
    out["walkin_table_position"] = mapped[0].get("walkin_table_position") if mapped else None
    out["least_crowded"] = min(mapped, key=lambda c: c["qloo"]["nearby_count"])["qloo"] if mapped else None
    if not mapped:
        out["unmapped_reason"] = "; ".join(f"{c['text']}: {c['reason']}" for c in out["components"])
    return out


async def walk(s, site: dict):
    """The 10-minute walk, traced again (up to three tries) when routing failed and fell back to a circle."""
    attempts = 1
    catchment = await s.walker.walk(site["lat"], site["lon"], MINUTES)
    while catchment.source == "circle" and attempts < 3:
        await asyncio.sleep(5)
        attempts += 1
        catchment = await s.walker.walk(site["lat"], site["lon"], MINUTES)
    return catchment, attempts


async def run_data(sites: list[dict], chat: dict, force: bool, only: str | None) -> None:
    s = default_services()
    try:
        for site in sites:
            if only and site["id"] != only:
                continue
            path = CACHE / "data" / f"{site['id']}.json"
            if path.exists() and not force:
                continue
            started, calls0, hits0 = time.time(), s.qloo.calls, s.qloo.cache_hits
            catchment, walk_attempts = await walk(s, site)
            genres, cues = await engine.demand_genres(s.qloo, catchment)
            rows = await engine.gap_table(s.qloo, catchment, genres, "any", None)
            by_id = {g["id"]: g for g in genres}

            walkin_probe = None
            if rows:
                top = by_id.get(rows[0]["genre_id"]) or {
                    "id": rows[0]["genre_id"], "name": rows[0]["genre"], "rank": rows[0]["demand_rank"],
                    "ref_rank": rows[0]["ref_rank"],
                }
                walkin_probe = measure(await engine.probe_genre(s.qloo, catchment, top, rows))

            answer = (chat.get("answers") or {}).get(site["id"])
            parsed = parse_answer(answer["text"]) if answer else []
            picks = []
            for role, text in zip(("top", "alternative 1", "alternative 2"), parsed, strict=False):
                picks.append({"role": role, "text": text, **await measure_text(s.qloo, catchment, genres, rows, text)})

            data = {
                "site": site["id"],
                "measured_at": now_text(),
                "walk": {
                    "source": catchment.source, "attempts": walk_attempts,
                    "area_km2": round(catchment.area_m2 / 1e6, 3), "radius_m": round(catchment.radius_m),
                    "around_outline": bool(catchment.around),
                },
                "demand_top15": [
                    {"rank": g["rank"], "genre": g["name"], "ref_rank": g.get("ref_rank")} for g in genres[:TOP_DEMAND]
                ],
                "ranked_genres": len(genres),
                "cues": cues,
                "gap_table": [measure(r) for r in rows],
                "walkin_probe": walkin_probe,
                "chatbot": {
                    "model": answer.get("model") if answer else None,
                    "provider": answer.get("provider") if answer else None,
                    "parsed": parsed,
                    "picks": picks,
                },
                "qloo_calls": s.qloo.calls - calls0,
                "qloo_cache_hits": s.qloo.cache_hits - hits0,
                "seconds": round(time.time() - started, 1),
            }
            save(path, data)
            wi = rows[0]["genre"] if rows else None
            cb = picks[0]["qloo"]["genre"] if picks and picks[0].get("qloo") else (parsed[0] if parsed else None)
            status(f"data {site['id']}: walk={catchment.source}, {len(genres)} genres, Walk-in={wi!r}, "
                   f"chatbot={cb!r}; {data['qloo_calls']} Qloo calls, {data['qloo_cache_hits']} cached, {data['seconds']}s.")
    finally:
        await s.aclose()


# ---------------------------------------------------------------------------------------------------------------------
# 4b. OpenStreetMap: the independent count of each measured kind inside the walk
# ---------------------------------------------------------------------------------------------------------------------

def osm_count(check: osm.CrossCheck, genre: str, genre_id: str | None) -> dict:
    if not check.checked:
        return {"checked": False, "count": None, "reason": "Overpass did not answer"}
    kind = osm.kind_of(genre, genre_id)
    if kind is None:
        return {"checked": False, "count": None, "reason": "no OpenStreetMap tag reliably marks this kind"}
    places = check.places_of(genre, genre_id) or []
    return {"checked": True, "count": len(places), "kind": kind.key, "tags": list(kind.text),
            "examples": [p["name"] for p in places[:6]]}


async def run_osm(sites: list[dict], force: bool, only: str | None) -> None:
    s = default_services()
    try:
        todo = [site for site in sites if (not only or site["id"] == only)
                and (force or not load(CACHE / "osm" / f"{site['id']}.json", {}).get("checked"))]
        for round_no in range(1, 4):
            if not todo:
                break
            failed = []
            for site in todo:
                data = load(CACHE / "data" / f"{site['id']}.json", None)
                if data is None:
                    continue
                catchment, _ = await walk(s, site)
                if catchment.area_m2 > OSM_MAX_M2:
                    scan = osm.Scan(False, note="area larger than the app asks Overpass about")
                else:
                    client = osm.OsmClient(settings.cache_dir.parent / "osm", endpoints=OVERPASS, timeout=25.0,
                                           budget=60.0)
                    try:
                        scan = await client.scan(catchment)
                    finally:
                        await client.aclose()
                check = osm.CrossCheck(scan, catchment)
                genres = {(r["genre"], r["genre_id"]) for r in data["gap_table"]}
                for pick in data["chatbot"]["picks"]:
                    for component in pick.get("components") or []:
                        if component.get("qloo"):
                            genres.add((component["qloo"]["genre"], component["qloo"]["genre_id"]))
                previous = load(CACHE / "osm" / f"{site['id']}.json", {})
                result = {
                    "site": site["id"], "checked": check.checked, "source": scan.source, "as_of": scan.as_of,
                    "note": scan.note, "named_places": len(scan.places) if scan.checked else None,
                    "rounds": previous.get("rounds", 0) + 1, "at": now_text(),
                    "counts": {gid: osm_count(check, name, gid) for name, gid in sorted(genres, key=str)},
                }
                save(CACHE / "osm" / f"{site['id']}.json", result)
                print(f"osm {site['id']:13} round {round_no}: {'checked' if check.checked else 'UNCHECKED'} "
                      f"{scan.source or ''} {result['named_places']}", flush=True)
                if not check.checked:
                    failed.append(site)
            todo = failed
            if todo and round_no < 3:
                await asyncio.sleep(60 * round_no)
        unchecked = [site["id"] for site in todo]
        status(f"osm: Overpass scans done; unchecked after 3 rounds: {unchecked or 'none'}.")
    finally:
        await s.aclose()


# ---------------------------------------------------------------------------------------------------------------------
# 5-6. Metrics, results.json and report.md
# ---------------------------------------------------------------------------------------------------------------------

def sign_test(wins: int, losses: int) -> float | None:
    """Two-sided exact sign test, ties dropped."""
    n = wins + losses
    if n == 0:
        return None
    tail = sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def med(values: list[float]) -> float | None:
    return float(median(values)) if values else None


def share(flags: list[bool]) -> dict:
    return {"yes": sum(flags), "n": len(flags), "pct": round(100 * sum(flags) / len(flags)) if flags else None}


def side_metrics(picks: list[dict | None]) -> dict:
    """picks: one measured pick per site (None when the side had no measurable pick there)."""
    measured = [p for p in picks if p and p.get("qloo")]
    qloo_counts = [p["qloo"]["nearby_count"] for p in measured]
    osm_checked = [p["osm"]["count"] for p in measured if p.get("osm") and p["osm"].get("checked")]
    rel = [p["qloo"]["relative_supply"] for p in measured]
    return {
        "measured": len(measured),
        "qloo_median": med(qloo_counts),
        "qloo_capped": sum(1 for p in measured if p["qloo"]["nearby_capped"]),
        "qloo_values": qloo_counts,
        "osm_median": med(osm_checked),
        "osm_n": len(osm_checked),
        "osm_values": osm_checked,
        "over_supplied": share([r >= OVER for r in rel]),
        "under_supplied": share([r <= UNDER for r in rel]),
        "relative_supply_median": med(rel),
        "top15_demand": share([p["qloo"]["demand_rank"] <= TOP_DEMAND for p in measured]),
        "demand_rank_median": med([p["qloo"]["demand_rank"] for p in measured]),
        "outside_top50": sum(1 for p in measured if p["qloo"]["demand_rank"] > 50),
        "under_and_loved": share([p["qloo"]["relative_supply"] <= UNDER and p["qloo"]["demand_rank"] <= TOP_DEMAND
                                  for p in measured]),
    }


def paired(cb: list[dict | None], wi: list[dict | None], key) -> dict:
    wins = losses = ties = 0
    for a, b in zip(cb, wi, strict=True):
        x, y = key(a), key(b)
        if x is None or y is None:
            continue
        if x > y:
            wins += 1
        elif x < y:
            losses += 1
        else:
            ties += 1
    return {"chatbot_more": wins, "walkin_more": losses, "ties": ties, "sign_test_p": sign_test(wins, losses)}


def qloo_of(p):
    return p["qloo"]["nearby_count"] if p and p.get("qloo") else None


def osm_of(p):
    return p["osm"]["count"] if p and p.get("osm") and p["osm"].get("checked") else None


def label_of(p: dict | None) -> str | None:
    if not p:
        return None
    if p.get("qloo"):
        return p["qloo"]["genre"]
    return f"(unmapped) {fold(p['text']).lower()}"


# The chatbot's most common concept, counted with a fixed keyword rule on the words of each side's pick.
CAFE_FAMILY = re.compile(r"coffee|\bcafes?\b|bakery|bakeries|panaderia|patisserie|pastry|espresso", re.IGNORECASE)


def cafe(p: dict | None) -> bool:
    return bool(p and CAFE_FAMILY.search(fold(p["text"])))


def osm_for(counts: dict, qloo: dict | None) -> dict | None:
    if not qloo:
        return None
    found = (counts.get("counts") or {}).get(qloo["genre_id"])
    return found or {"checked": False, "count": None, "reason": "Overpass did not answer"}


def chatbot_pick(p: dict, counts: dict) -> dict:
    """One chatbot suggestion as results.json keeps it, with OpenStreetMap's count for every reading."""
    least = p.get("least_crowded")
    return {
        "role": p["role"], "text": p["text"], "mapped_from": p.get("mapped_from"),
        "qloo": p.get("qloo"), "osm": osm_for(counts, p.get("qloo")),
        "walkin_table_position": p.get("walkin_table_position"),
        "unmapped_reason": p.get("unmapped_reason"),
        "least_crowded": {"text": p["text"], "qloo": least, "osm": osm_for(counts, least)} if least else None,
        "literal_resolver": p.get("literal"),
        "components": [{**c, "osm": osm_for(counts, c.get("qloo"))} for c in p.get("components") or []],
    }


def build_results(sites: list[dict], chat: dict) -> dict:
    per_site = []
    for site in sites:
        data = load(CACHE / "data" / f"{site['id']}.json", None)
        if data is None:
            continue
        counts = load(CACHE / "osm" / f"{site['id']}.json", {"checked": False, "counts": {}})
        answer = (chat.get("answers") or {}).get(site["id"]) or {}
        table = data["gap_table"]
        walkin = [{"role": role, "text": row["genre"], "qloo": row, "osm": osm_for(counts, row)}
                  for role, row in zip(("top", "alternative 1", "alternative 2"), table, strict=False)]
        chatbot = [chatbot_pick(p, counts) for p in data["chatbot"]["picks"]]
        probe = data.get("walkin_probe")
        per_site.append({
            **{k: site[k] for k in ("id", "name", "city", "country", "continent", "street", "address", "lat", "lon")},
            "geocoder": site["geocoder"],
            "walk": data["walk"],
            "osm_scan": {k: counts.get(k) for k in ("checked", "source", "as_of", "note", "named_places", "rounds")},
            "chatbot": {
                "model": answer.get("model"), "provider": answer.get("provider"), "answered_at": answer.get("answered_at"),
                "failed_attempts": answer.get("attempts"), "raw_answer": answer.get("text"),
                "parsed": data["chatbot"]["parsed"],
                "top": chatbot[0] if chatbot else None, "alternatives": chatbot[1:],
            },
            "walkin": {
                "top": walkin[0] if walkin else None, "alternatives": walkin[1:],
                "gap_table": [{**row, "osm": osm_for(counts, row)} for row in table],
                "probe_matches_table": bool(probe and table and probe["nearby_count"] == table[0]["nearby_count"]
                                            and probe["relative_supply"] == table[0]["relative_supply"]),
            },
            "agree": bool(chatbot and walkin and chatbot[0].get("qloo") and walkin[0]["qloo"]["genre_id"]
                          == chatbot[0]["qloo"]["genre_id"]),
            "demand_top15": data["demand_top15"],
            "qloo_calls": data["qloo_calls"], "qloo_cache_hits": data["qloo_cache_hits"],
        })

    cb_top = [r["chatbot"]["top"] for r in per_site]
    wi_top = [r["walkin"]["top"] for r in per_site]
    cb_least = [p["least_crowded"] if p else None for p in cb_top]
    cb_all = [p for r in per_site for p in ([r["chatbot"]["top"]] + r["chatbot"]["alternatives"]) if p]
    wi_all = [p for r in per_site for p in ([r["walkin"]["top"]] + r["walkin"]["alternatives"]) if p]
    cb_labels = [label_of(p) for p in cb_top if p]
    wi_labels = [label_of(p) for p in wi_top if p]
    raw_tops = [fold(p["text"]).lower().strip() for p in cb_top if p]
    metrics = {
        "sites": len(per_site),
        "cities": len({r["city"] for r in per_site}),
        "continents": len({r["continent"] for r in per_site}),
        "chatbot_answered": sum(1 for p in cb_top if p),
        "chatbot_top_mapped": sum(1 for p in cb_top if p and p.get("qloo")),
        "chatbot_top_literal_mapped": sum(1 for p in cb_top if p and (p.get("literal_resolver") or {}).get("genre")),
        "chatbot_all_literal_mapped": sum(1 for p in cb_all if (p.get("literal_resolver") or {}).get("genre")),
        "models": dict(Counter(r["chatbot"]["model"] for r in per_site if r["chatbot"]["model"])),
        "distinct": {
            "chatbot_genres": len(set(cb_labels)), "chatbot_raw_texts": len(set(raw_tops)),
            "chatbot_most_common": Counter(cb_labels).most_common(3),
            "walkin_genres": len(set(wi_labels)), "walkin_most_common": Counter(wi_labels).most_common(3),
            "chatbot_cafe_family": sum(1 for p in cb_top if cafe(p)),
            "walkin_cafe_family": sum(1 for p in wi_top if cafe(p)),
            "chatbot_cafe_any_of_three": sum(
                1 for r in per_site if any(cafe(p) for p in [r["chatbot"]["top"], *r["chatbot"]["alternatives"]])
            ),
            "walkin_cafe_any_of_three": sum(
                1 for r in per_site if any(cafe(p) for p in [r["walkin"]["top"], *r["walkin"]["alternatives"]])
            ),
            "chatbot_cafe_by_model": {
                model: [sum(1 for r in per_site if r["chatbot"]["model"] == model and cafe(r["chatbot"]["top"])),
                        sum(1 for r in per_site if r["chatbot"]["model"] == model)]
                for model in dict.fromkeys(r["chatbot"]["model"] for r in per_site if r["chatbot"]["model"])
            },
        },
        "top": {"chatbot": side_metrics(cb_top), "walkin": side_metrics(wi_top),
                "chatbot_least_crowded": side_metrics(cb_least)},
        "paired_qloo": paired(cb_top, wi_top, qloo_of),
        "paired_osm": paired(cb_top, wi_top, osm_of),
        "paired_qloo_least_crowded": paired(cb_least, wi_top, qloo_of),
        "paired_osm_least_crowded": paired(cb_least, wi_top, osm_of),
        "agreement": sum(1 for r in per_site if r["agree"]),
        "chatbot_top_in_walkin_top3": sum(
            1 for r in per_site if r["chatbot"]["top"] and r["chatbot"]["top"].get("qloo") and any(
                w and w["qloo"]["genre_id"] == r["chatbot"]["top"]["qloo"]["genre_id"]
                for w in [r["walkin"]["top"], *r["walkin"]["alternatives"]]
            )
        ),
        "all_three": {"chatbot": side_metrics(cb_all), "walkin": side_metrics(wi_all),
                      "chatbot_suggestions": len(cb_all)},
        "osm_sites_checked": sum(1 for r in per_site if r["osm_scan"].get("checked")),
        "osm_sources": dict(Counter(
            f"{r['osm_scan']['source']} (data as of {str(r['osm_scan']['as_of'])[:10]})"
            for r in per_site if r["osm_scan"].get("checked")
        )),
        "walk_sources": dict(Counter(r["walk"]["source"] for r in per_site)),
        "probe_matches_table": sum(1 for r in per_site if r["walkin"]["probe_matches_table"]),
        "qloo_calls": sum(r["qloo_calls"] for r in per_site),
        "llm_calls": chat.get("llm_calls"),
    }
    return {"generated_at": now_text(), "prompt": PROMPT, "thresholds": {"over": OVER, "under": UNDER,
            "top_demand": TOP_DEMAND, "walk_minutes": MINUTES}, "metrics": metrics, "sites": per_site}


def fmt(value, digits: int = 0) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        if digits:
            return f"{value:.{digits}f}"
        return f"{value:.0f}" if value == int(value) else f"{value:.1f}"
    return str(value)


def cell_count(p: dict | None) -> str:
    if not p or not p.get("qloo"):
        return "–"
    q = p["qloo"]
    return f"{q['nearby_count']}{'+' if q['nearby_capped'] else ''}"


def cell_osm(p: dict | None) -> str:
    if not p or not p.get("qloo"):
        return "–"
    o = p.get("osm") or {}
    if o.get("checked"):
        return str(o["count"])
    return "n/a" if "tag" in (o.get("reason") or "") else "unchecked"


def cell_rel(p: dict | None) -> str:
    return fmt(p["qloo"]["relative_supply"], 2) if p and p.get("qloo") else "–"


def cell_rank(p: dict | None) -> str:
    if not p or not p.get("qloo"):
        return "–"
    rank = p["qloo"]["demand_rank"]
    return ">50" if rank > 50 else str(rank)


def genre_of(p: dict | None) -> str:
    if not p:
        return "no answer"
    return p["qloo"]["genre"] if p.get("qloo") else "(no Qloo genre)"


def pct(s: dict) -> str:
    return f"{s['pct']}% ({s['yes']}/{s['n']})" if s["n"] else "–"


def p_value(p: float | None) -> str:
    return "–" if p is None else f"{p:.2f}"


def headline(m: dict) -> str:
    d, cb, wi = m["distinct"], m["top"]["chatbot"], m["top"]["walkin"]
    if cb["qloo_median"] == wi["qloo_median"]:
        competition = f"both sides' picks faced the same median of {fmt(cb['qloo_median'])} competitors"
    else:
        competition = (f"the chatbot's picks faced a median of {fmt(cb['qloo_median'])} competitors and Walk-in's "
                       f"{fmt(wi['qloo_median'])}")
    return (
        f"Across {m['sites']} storefronts in {m['cities']} cities on {m['continents']} continents, a plain chatbot's top "
        f"pick was a coffee shop, café or bakery at {d['chatbot_cafe_family']} of them, while Walk-in's {wi['measured']} "
        f"top picks were {d['walkin_genres']} different kinds of place; by Qloo's count, though, {competition} inside "
        f"the {MINUTES}-minute walk."
    )


def write_report(results: dict) -> str:
    m, sites = results["metrics"], results["sites"]
    d = m["distinct"]
    cb, wi, lc = m["top"]["chatbot"], m["top"]["walkin"], m["top"]["chatbot_least_crowded"]
    pq, po, plq = m["paired_qloo"], m["paired_osm"], m["paired_qloo_least_crowded"]
    a_cb, a_wi = m["all_three"]["chatbot"], m["all_three"]["walkin"]
    most = ", ".join(f"{name} ×{n}" for name, n in d["chatbot_most_common"])
    wmost = ", ".join(f"{name} ×{n}" for name, n in d["walkin_most_common"] if n > 1) or "none repeated"
    by_model = "; ".join(f"{k}: {a} of {b}" for k, (a, b) in d["chatbot_cafe_by_model"].items())
    osm_sources = "; ".join(f"{k}: {v} walks" for k, v in m["osm_sources"].items())
    example = next((s for s in sites if s["id"] == "paris"), None)
    tagging = ""
    if example and example["chatbot"]["top"] and example["walkin"]["top"]:
        c, w = example["chatbot"]["top"], example["walkin"]["top"]
        tagging = (f" In Paris, OpenStreetMap shows {cell_osm(c)} places tagged as cafés inside the walk and "
                   f"{cell_osm(w)} tagged 'brunch', where Qloo lists {cell_count(c)} and {cell_count(w)}.")
    loved = cb["under_and_loved"]["yes"]
    cafe_tops = [r["chatbot"]["top"] for r in sites if cafe(r["chatbot"]["top"])]
    compound = "each time" if all(CONJUNCTION.search(p["text"]) for p in cafe_tops) else "usually"
    both_cafe = [f"{r['city']} ({r['chatbot']['top']['qloo']['genre']} vs {r['walkin']['top']['qloo']['genre']})"
                 for r in sites if cafe(r["chatbot"]["top"]) and cafe(r["walkin"]["top"])]
    same = (f"The two sides never named the same genre; both chose a café concept only in {', '.join(both_cafe)}."
            if m["agreement"] == 0 and both_cafe else
            f"The two sides named the same genre at {m['agreement']} of {m['sites']} sites.")
    if cb["qloo_median"] == wi["qloo_median"]:
        level = f"both sides' top picks had the same median, {fmt(cb['qloo_median'])} competitors inside the walk"
    else:
        level = (f"the top picks had medians of {fmt(cb['qloo_median'])} (chatbot) and {fmt(wi['qloo_median'])} "
                 "(Walk-in) competitors inside the walk")
    walks = sum(1 for r in sites if r["walk"]["source"] == "street network")
    fallbacks = {k: v for k, v in m["models"].items() if k != settings.llm_model}
    model_note = (f"{settings.llm_model} ×{m['models'].get(settings.llm_model, 0)}"
                  + (f"; after HTTP 503 (overloaded) errors, {', '.join(f'{k} ×{v}' for k, v in fallbacks.items())}"
                     if fallbacks else ""))
    lines = [
        "# Walk-in vs a plain chatbot on 15 real storefronts",
        "",
        f"**Headline.** {headline(m)}",
        "",
        "## What the numbers say",
        "",
        f"- **(a) Sameness: the clear result.** The chatbot's top pick was a coffee shop, café or bakery at "
        f"{d['chatbot_cafe_family']} of {m['sites']} storefronts, {compound} as a compound such as 'Specialty Coffee & "
        f"Artisanal Bakery', and a coffee shop, café or bakery was among its three suggestions at "
        f"{d['chatbot_cafe_any_of_three']}. Mapped to "
        f"Qloo's place genres, its {m['sites']} top picks were {d['chatbot_genres']} kinds ({most}). Walk-in's were "
        f"{d['walkin_genres']} kinds (repeated: {wmost}), with a coffee shop, café or bakery at {d['walkin_cafe_family']}. "
        f"{same} This part uses no Walk-in data.",
        f"- **(b) Competition: level.** By Qloo's count {level}; the chatbot's had more at "
        f"{pq['chatbot_more']} sites, Walk-in's at {pq['walkin_more']}, with {pq['ties']} tie (sign test "
        f"p = {p_value(pq['sign_test_p'])}). OpenStreetMap's medians are {fmt(cb['osm_median'])} and "
        f"{fmt(wi['osm_median'])} ({po['chatbot_more']} sites to {po['walkin_more']}, p = {p_value(po['sign_test_p'])}), "
        "but it is not a fair referee here: a café carries one tag almost everywhere (amenity=cafe), while Walk-in's "
        f"cuisine-level kinds rest on optional cuisine tags.{tagging} The claim that the chatbot picks what the block "
        "already has plenty of is not supported by the counts.",
        f"- **(c) Relative supply (Walk-in's own measure).** The chatbot's picks sat where the surroundings predict "
        f"(median {fmt(cb['relative_supply_median'], 2)}; {cb['over_supplied']['yes']} over-supplied, "
        f"{cb['under_supplied']['yes']} under-supplied); Walk-in's sat lower (median "
        f"{fmt(wi['relative_supply_median'], 2)}; {wi['over_supplied']['yes']} over, {wi['under_supplied']['yes']} "
        "under), which is partly what its score is built to find.",
        f"- **(d) Local demand.** {cb['top15_demand']['yes']} of the chatbot's {cb['measured']} top picks were among "
        f"the {TOP_DEMAND} place types people around the storefront engage with most, and {cb['outside_top50']} were "
        f"outside their top 50. Walk-in's always are: it only considers the top {engine.GAP_GENRES}. "
        f"{'None' if loved == 0 else loved} of the chatbot's {cb['measured']} picks "
        f"{'was' if loved <= 1 else 'were'} both under-supplied and in that top {TOP_DEMAND}; "
        f"{wi['under_and_loved']['yes']} of Walk-in's were.",
        "",
        "## Aggregate metrics (top picks)",
        "",
        "| Metric | Plain chatbot | Walk-in |",
        "|---|---|---|",
        f"| Top picks measured (mapped to a Qloo place genre) | {cb['measured']} of {m['sites']} | "
        f"{wi['measured']} of {m['sites']} |",
        f"| (a) Distinct Qloo genres among the {m['sites']} top picks | {d['chatbot_genres']} ({most}) | "
        f"{d['walkin_genres']} |",
        f"| (a) Top pick is a coffee shop, café or bakery | {d['chatbot_cafe_family']} of {m['sites']} | "
        f"{d['walkin_cafe_family']} of {m['sites']} |",
        f"| (a) Coffee shop, café or bakery among the three suggestions | {d['chatbot_cafe_any_of_three']} of "
        f"{m['sites']} | {d['walkin_cafe_any_of_three']} of {m['sites']} |",
        f"| (b) Median competitors inside the walk, Qloo | {fmt(cb['qloo_median'])} | {fmt(wi['qloo_median'])} |",
        f"| (b) Paired, Qloo: sites where this side's pick has more | {pq['chatbot_more']} | {pq['walkin_more']} "
        f"({pq['ties']} tie; p = {p_value(pq['sign_test_p'])}) |",
        f"| (b) Median competitors inside the walk, OpenStreetMap (independent; tagging-skewed) | "
        f"{fmt(cb['osm_median'])} (n={cb['osm_n']}) | {fmt(wi['osm_median'])} (n={wi['osm_n']}) |",
        f"| (b) Paired, OpenStreetMap | {po['chatbot_more']} | {po['walkin_more']} ({po['ties']} ties; "
        f"p = {p_value(po['sign_test_p'])}) |",
        f"| (c) Over-supplied (relative supply ≥ {OVER}) | {pct(cb['over_supplied'])} | {pct(wi['over_supplied'])} |",
        f"| (c) Under-supplied (≤ {UNDER}) | {pct(cb['under_supplied'])} | {pct(wi['under_supplied'])} |",
        f"| (c) Median relative supply | {fmt(cb['relative_supply_median'], 2)} | "
        f"{fmt(wi['relative_supply_median'], 2)} |",
        f"| (d) Among people's top {TOP_DEMAND} place types here | {pct(cb['top15_demand'])} | "
        f"{pct(wi['top15_demand'])} (by construction) |",
        f"| (d) Median rank people here give the pick | {fmt(cb['demand_rank_median'])} | "
        f"{fmt(wi['demand_rank_median'])} |",
        f"| (c)+(d) Under-supplied and in people's top {TOP_DEMAND} | {pct(cb['under_and_loved'])} | "
        f"{pct(wi['under_and_loved'])} (its objective) |",
        "",
        f"Chatbot models that answered: {model_note}. Coffee/café/bakery top picks by model: {by_model}. LLM calls "
        f"used: {m['llm_calls']} of {MAX_LLM_CALLS}. Walks: {walks} of {m['sites']} traced on the street network. "
        f"OpenStreetMap: {osm_sources}. Qloo requests in the measured run: {m['qloo_calls']} live, the rest from the "
        "on-disk cache.",
        "",
        "## Per site (top picks)",
        "",
        "Qloo and OSM are the places of that kind inside the 10-minute walk ('+' = Qloo's cap of 100; OSM 'n/a' = no "
        "OpenStreetMap tag reliably marks that kind). Supply is relative supply: places inside the walk against what the "
        "surrounding 20-minute walk predicts (1.00 = typical). Rank is where people here rank that place type "
        "(1 = most engaged; '>50' = outside their top 50).",
        "",
        "| # | Storefront | Model | Chatbot's top pick, as written | Qloo genre | Qloo | OSM | Supply | Rank | "
        "Walk-in's pick | Qloo | OSM | Supply | Rank |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(sites, 1):
        c, w = r["chatbot"]["top"], r["walkin"]["top"]
        lines.append(
            f"| {i} | {r['name']}, {r['city']} | {(r['chatbot']['model'] or '–').removeprefix('gemini-')} | "
            f"{c['text'] if c else 'no answer'} | {genre_of(c)} | {cell_count(c)} | {cell_osm(c)} | {cell_rel(c)} | "
            f"{cell_rank(c)} | {genre_of(w) if w else 'no pick'} | {cell_count(w)} | {cell_osm(w)} | {cell_rel(w)} | "
            f"{cell_rank(w)} |"
        )
    lines += [
        "",
        "## Sensitivity",
        "",
        f"- **Least-crowded reading.** Reading each compound chatbot pick as whichever named business has the fewest "
        f"competitors (a bakery rather than a coffee shop, say), its median stays {fmt(lc['qloo_median'])} on Qloo "
        f"({plq['chatbot_more']} sites to {plq['walkin_more']}, p = {p_value(plq['sign_test_p'])}) and "
        f"{fmt(lc['osm_median'])} on OpenStreetMap; {pct(lc['over_supplied'])} over-supplied; "
        f"{pct(lc['top15_demand'])} in people's top {TOP_DEMAND}.",
        f"- **All three suggestions.** The chatbot's {m['all_three']['chatbot_suggestions']} suggestions "
        f"({a_cb['measured']} mappable to a Qloo genre) against Walk-in's top three gaps per site: median "
        f"{fmt(a_cb['qloo_median'])} vs {fmt(a_wi['qloo_median'])} competitors on Qloo, {fmt(a_cb['osm_median'])} vs "
        f"{fmt(a_wi['osm_median'])} on OpenStreetMap; over-supplied {pct(a_cb['over_supplied'])} vs "
        f"{pct(a_wi['over_supplied'])}; in people's top {TOP_DEMAND} {pct(a_cb['top15_demand'])} vs "
        f"{pct(a_wi['top15_demand'])}.",
        f"- **The app's resolver alone.** `engine.find_genre` on the chatbot's wording as written mapped "
        f"{m['chatbot_all_literal_mapped']} of its {m['all_three']['chatbot_suggestions']} categories "
        "(compounds like 'Specialty Coffee & Artisanal Bakery Concept' match no Qloo genre), hence the component rule "
        "in the method.",
        "",
        "## Alternatives (secondary)",
        "",
        "| # | City | Chatbot's alternatives → Qloo genre (Qloo / OSM / supply / rank) | Walk-in's 2nd and 3rd gaps "
        "(Qloo / OSM / supply / rank) |",
        "|---|---|---|---|",
    ]

    def brief(p: dict, chatbot: bool) -> str:
        if not p.get("qloo"):
            return f"{p['text']} → (no Qloo genre)"
        name = f"{p['text']} → {p['qloo']['genre']}" if chatbot else p["qloo"]["genre"]
        return f"{name} ({cell_count(p)} / {cell_osm(p)} / {cell_rel(p)} / {cell_rank(p)})"

    for i, r in enumerate(sites, 1):
        lines.append(
            f"| {i} | {r['city']} | {'; '.join(brief(p, True) for p in r['chatbot']['alternatives']) or '–'} | "
            f"{'; '.join(brief(p, False) for p in r['walkin']['alternatives']) or '–'} |"
        )
    lines += ["", "## Method", ""] + METHOD + ["", "## Caveats", ""] + CAVEATS + [
        "",
        "## Files",
        "",
        "- `sites.json`: the 15 storefronts with the geocoder's confirmation.",
        "- `results.json`: per site, the chatbot's raw answer and model, the parsed picks, every business each pick "
        "names with its mapping, both sides' numbers, Walk-in's full gap table and the OpenStreetMap counts; the "
        "aggregate metrics.",
        "- `run_h2h.py`: the script (phases sites, chat, data, osm, report). `_cache/` holds the raw chatbot answers and "
        "per-site measurements it reuses.",
        "",
    ]
    return "\n".join(lines)


METHOD = [
    "1. **Sites:** 15 storefront addresses on commercial streets in 15 cities on 6 continents (trendy strips, immigrant "
    "and working-class high streets, a Tokyo shotengai, a Cairo road), geocoded with Nominatim and fixed before any "
    "result was seen.",
    "2. **Chatbot:** one call per site with the app's LLM settings (Gemini via its OpenAI-compatible endpoint, reasoning "
    "effort low, next fallback model on a 429 or 503), no system prompt, the prompt verbatim; top pick and two "
    "alternatives parsed from the reply.",
    "3. **Walk-in, no LLM:** the 10-minute walk from Valhalla, Qloo's genre ranking for it (`engine.demand_genres`) and "
    "the Qloo-only gap table (`engine.gap_table(..., 'any', None)`); its pick is the top row.",
    "4. **Same measure:** each business a chatbot category names ('Specialty Coffee & Artisanal Bakery' names two) was "
    "mapped to a Qloo genre through a fixed keyword table of Qloo genre names, resolved with `engine.find_genre`, and "
    "measured with `engine.probe_genre` on the table's own supply baseline; the first-named one counts.",
    "5. **Independent check:** OpenStreetMap's named places of each kind inside the same walk (`OsmClient.scan` plus "
    "`CrossCheck.places_of`), retried over several rounds and Overpass instances; no walk was left unchecked.",
    "6. **Metrics:** (a) distinct top picks; (b) median competitors inside the walk on Qloo and OpenStreetMap, with "
    "a paired sign test; (c) share over-supplied (≥ 1.2) or under-supplied (≤ 0.8); (d) share in people's top 15.",
]

CAVEATS = [
    "- **(b) to (d) use Walk-in's own data (Qloo) for both sides.** OpenStreetMap is the independent check, and it is "
    "skewed here: a café is tagged the same way everywhere, cuisine-level kinds often are not, so it undercounts many of "
    "Walk-in's picks (and has no tag at all for some of each side's: Vintage clothing store, Takeout, Plant nursery, "
    "Cultural center, Modern izakaya, Lunch restaurant). Most walks were read from an instance whose data dates from "
    "August 2026.",
    "- **Walk-in is partly graded on its own objective.** It only considers the place types people here rank in their "
    "top 8, so (d) is 100% by construction, and its score favours low relative supply, so (c) leans its way. (a) and "
    "the OpenStreetMap counts are the parts it was not built to win.",
    "- **15 sites is small.** One chatbot answer per site, and a second could differ; 4 of 15 came from fallback "
    "models after HTTP 503 (overloaded) errors. No difference in (b) is statistically significant.",
    "- **The chatbot had no map.** That is the point being tested, not a flaw: it is what anyone gets by asking a "
    "chatbot about an address.",
    "- **Taste data isn't foot traffic or sales.** Neither side's pick was checked against footfall, rents or revenue, "
    "and a gap is not proof of demand.",
    "- **Mapping is a judgment.** Compound picks were read as their first-named business (the least-crowded reading is "
    "in the sensitivity section); kinds Qloo has no place genre for (groceries, home decor, concept stores) count as "
    "unmapped. Breadth matters too: 'Coffee shop' is common everywhere, so raw counts partly measure how broad a "
    "category is.",
    "- **This is the gap table, not the whole app.** The live survey also folds OpenStreetMap places into supply and has "
    "the AI turn the top gaps into concepts; neither step ran here. The raw top row is not always a storefront business "
    "(Berlin's is 'Cultural center').",
]


async def run_report(sites: list[dict], chat: dict) -> None:
    results = build_results(sites, chat)
    save(OUT / "results.json", results)
    (OUT / "report.md").write_text(write_report(results), encoding="utf-8")
    m = results["metrics"]
    print(json.dumps({k: m[k] for k in ("sites", "chatbot_top_mapped", "distinct", "paired_qloo", "paired_osm",
                                        "agreement", "models")}, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(m["top"], ensure_ascii=False, default=str))
    status(f"report: results.json and report.md written ({m['sites']} sites).")


# ---------------------------------------------------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["sites", "chat", "data", "osm", "report", "all", "parse"])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    CACHE.mkdir(parents=True, exist_ok=True)
    sites = await run_sites(args.force and args.phase == "sites")
    if args.phase == "sites":
        return
    if args.phase in ("chat", "all"):
        await run_chat(sites, args.force and args.phase == "chat", args.only)
    chat = load(CACHE / "chat.json", {"llm_calls": 0, "answers": {}})
    if args.phase == "parse":
        for site in sites:
            answer = chat["answers"].get(site["id"])
            print(f"{site['id']:13} {parse_answer(answer['text']) if answer else None}")
        return
    if args.phase in ("data", "all"):
        await run_data(sites, chat, args.force and args.phase == "data", args.only)
    if args.phase in ("osm", "all"):
        await run_osm(sites, args.force and args.phase == "osm", args.only)
    if args.phase in ("report", "all"):
        await run_report(sites, chat)


if __name__ == "__main__":
    asyncio.run(main())
