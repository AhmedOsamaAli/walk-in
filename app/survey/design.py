"""Design sheets: what a concept looks, sounds and feels like, and the prompts for its renders."""
from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

from .. import scoring, space
from ..answers import AnswerCache, fingerprint
from ..images import Images
from ..llm import LLM
from ..qloo import QlooClient, QlooError
from . import experience
from .concepts import ground_names, grounded_price
from .evidence import example_places, gap_for, in_sentence, offer_items
from .experience import fans_of
from .models import RunState

log = logging.getLogger("blankspace")


DESIGN_SYSTEM = """You are Blank Space's concept designer. Turn a business concept into a design brief for an empty storefront.
Ground every choice in the evidence: design DNA of the locals' favorite places, what local fans of this category also
love, local artists, nearby places and local brands.
Design for the unit: no patio, terrace or sidewalk seating unless unit.outdoor_space is yes. When a unit is given,
layout and seating fit its size and capacity, and there is no cooking line unless it has a full kitchen.
owner_constraints are hard rules: nothing in the offer they forbid. The offer starts from offer_evidence (what the
places locals love are known for, those no place inside the walk offers first) and price_level follows price_evidence.
Return JSON with keys: name, tagline, concept_statement, interior {mood, materials (list), lighting, layout, seating},
offer (list of 4-6 items), price_level (1-4), music {direction, artists (list, only from local_artists)},
partners (list of {name, why}; name only from nearby_places or partner_brands), image_prompt (a photorealistic wide
view of the whole interior: layout, materials, lighting and seating; no people, text or logos), facade_prompt (the
shopfront seen from a typical street of this neighborhood, with a sign that reads exactly the concept name; no people)."""


async def design_concept(
    llm: LLM, images: Images, run: RunState, index: int, q: QlooClient | None = None,
    answers: AnswerCache | None = None,
) -> dict:
    concept = run.concepts[index]
    row = gap_for(run, concept["genre"])
    dna = scoring.design_dna(example_places(row)) if row else {}
    fans: dict = {"brands": [], "artists": [], "specific": False}
    if row and q is not None:
        try:
            fans = await fans_of(q, run, row["genre_id"])
        except QlooError:
            log.warning("Fan taste lookup failed; designing from the area's taste only", exc_info=True)
    # The soundtrack and partners come from what this neighborhood over-indexes on. Fans of the category are mostly
    # its audience at large, so they only decide the order: signature names they share come first.
    shared = {card["name"] for card in fans["brands"] + fans["artists"]} if fans.get("specific") else set()
    signature_artists = run.taste.get("distinctive_artists", [])
    local_artists = [a["name"] for a in sorted(signature_artists, key=lambda a: a["name"] not in shared)]
    nearby = [p.get("name") for p in run.block if p.get("name")]
    brand_cards = sorted(run.taste.get("distinctive_brands", []), key=lambda b: b["name"] not in shared)
    fitting_brands = [b["name"] for b in scoring.partner_brands(brand_cards, concept["genre"])]
    site = run.site
    unit = space.unit_text(site.size_m2, site.kitchen, site.outdoor)
    fit = space.fit(concept["genre"], site.size_m2, site.kitchen)
    capacity = fit["capacity_text"] if fit else None
    design: dict[str, Any] = {}
    mode, model = "rules", None
    if llm.enabled:
        brief: dict[str, Any] = {
            "site": site.label,
            "owner_notes": site.notes or None,
            "concept": {k: concept.get(k) for k in ("name", "genre", "one_liner", "for_whom", "price_level", "signature")},
            "design_dna_of_locals_favorites": dna,
            "local_artists": local_artists[:15],
            "nearby_places": nearby[:40],
            "local_brands": [{"name": b["name"], "type": b.get("kind")} for b in brand_cards[:15]],
            "signature_names_this_category_s_fans_share": sorted(shared & ({*local_artists} | {b["name"] for b in brand_cards})),
            "partner_brands": fitting_brands[:8],
            "taste_cues": run.cues,
        }
        if row:
            brief["offer_evidence"] = offer_items(row, run.constraints, limit=8)
            brief["price_evidence"] = (row.get("price") or {}).get("basis")
        rules = run.constraints.as_evidence()
        if rules:
            brief["owner_constraints"] = rules
        if unit:
            brief["unit"] = {**unit, "capacity": capacity or "unknown"}
        payload = json.dumps(brief, ensure_ascii=False)
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
        design = rule_design(run, concept, dna, local_artists, fitting_brands, capacity=capacity)
        mode, model = "rules", None
    design["offer"] = [item for item in design.get("offer") or [] if isinstance(item, str) and run.constraints.allows_item(item)][:6]
    if row:
        design["price_level"], design["price_basis"] = grounded_price(run, row, design.get("price_level", concept.get("price_level")))
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
    # Hours come from the places themselves, never from the model; launch ideas were dropped as ungrounded.
    design.pop("launch", None)
    design["hours"], design["hours_basis"] = opening_hours(row)
    design["unit"] = unit
    design["capacity"] = capacity
    design["capacity_basis"] = CAPACITY_BASIS if capacity else None
    design["experience"] = experience.plan(run, concept["genre"])
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


CAPACITY_BASIS = (
    "Planning estimate from the International Building Code occupant load factors (15 ft² per seated guest, 5 per "
    "standing guest) after kitchen, storage and circulation. Check the local code and the unit's certificate."
)


def room_scale(run: RunState) -> str:
    size = space.size_text(run.site.size_m2)
    return f"The room is about {size}, furnished at a realistic scale for that size. " if size else ""


def design_shots(run: RunState, concept: dict, design: dict, dna: dict) -> list[dict]:
    """Prompts for the two renders. The server keeps them, so a client can only render the shots it was given."""
    sign = sign_text(str(design.get("name") or concept["name"]))
    interior = design.get("image_prompt")
    facade = design.get("facade_prompt")
    if isinstance(interior, str) and interior.strip():
        interior = f"{interior.strip()} {room_scale(run)}{INTERIOR_STYLE}"
    else:
        interior = interior_prompt(run, concept, dna, design)
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
    return f"Interior of a small street-level {noun} in {run.site.label}. {described}. {room_scale(run)}{INTERIOR_STYLE}"


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
        if not place.get("name") or genre in names or not business or not scoring.is_storefront_place(place):
            continue
        kind = scoring.genre_kind(business[0])
        order = wanted.index(kind) if kind in wanted else len(wanted)
        candidates.append((order, -(place.get("popularity") or 0), place["name"]))
    return [name for _, _, name in sorted(candidates)[:limit]]


def opening_hours(row: dict | None) -> tuple[str | None, str | None]:
    """Hours the places locals love of this type keep (competitors inside the walk when too few list theirs)."""
    if not row:
        return None, None
    genre = in_sentence(row["genre"])
    found = scoring.typical_hours(example_places(row))
    if found:
        return found["text"], f"Typical hours of the {found['sample']} {genre} places locals love that list them"
    found = scoring.typical_hours(scoring.relevant(row.get("_nearby_entities") or [], row["genre_id"], row["genre"]))
    if found:
        return found["text"], f"Typical hours of {found['sample']} {genre} places inside the walk"
    return None, None


# Lighting a kind of business is designed around; the favorites' tags rarely say, so this is a design convention.
LIGHTING = {
    "food": "Daylight through the shopfront by day, warm pendants over the tables after dark",
    "bar": "Low, warm light with the bar itself lit brightest",
    "venue": "Dim house lights with a lit stage; brighter at the bar",
    "retail": "Bright, even light on the displays, warmer at the counter",
    "wellness": "Soft, calm light, dimmable in the treatment rooms",
}
WARM_AMBIENCE = re.compile(r"\b(romantic|cozy|cosy|intimate|dim|moody|candle)", re.IGNORECASE)
BIG_ROOM_SEATING = re.compile(r"\b(outdoor|balcon\w*|stadium|tiered|mezzanine|patio|terrace|rooftop|lawn|bleacher\w*)\b", re.IGNORECASE)


def rule_design(
    run: RunState, concept: dict, dna: dict, artists: list[str], partner_brands: list[str], capacity: str | None = None,
) -> dict:
    ambience = ", ".join(dna.get("ambience", [])[:3]).lower() or "warm and welcoming"
    decor = [item.lower() for item in dna.get("decor", [])[:4]]
    minutes = run.site.minutes
    kind = scoring.genre_kind(concept["genre"])
    layout = LAYOUTS.get(kind, LAYOUTS["food"])
    # Only space the owner says the unit has: favorites with patios say nothing about this unit.
    if run.site.outdoor:
        layout += ", plus sidewalk seating"
    # Seating the favorites list, unless it belongs to a big building (balconies, stadium rows) or the outdoors.
    seating = ", ".join(
        a for a in dna.get("amenities", []) if "seating" in a.lower() and not BIG_ROOM_SEATING.search(a)
    ) or "Mixed bar and table seating"
    lighting = LIGHTING.get(kind, LIGHTING["food"])
    if kind == "food" and WARM_AMBIENCE.search(ambience):
        lighting = "Low, warm light at every table"
    partners = [
        {"name": name, "why": f"Loved inside the {minutes}-minute walk for a different visit than this one: cross-promote."}
        for name in partner_places(run, concept["genre"])
    ]
    if partner_brands:
        partners.append({"name": partner_brands[0], "why": "A brand people within 1.5 km over-index on; a natural co-branding partner."})
    row = gap_for(run, concept["genre"])
    offer = [i["item"] for i in offer_items(row, run.constraints, limit=6)] if row else list(concept.get("signature") or [])
    return {
        "name": concept["name"],
        "tagline": concept.get("one_liner"),
        "concept_statement": " ".join(concept.get("why_here", [])),
        "interior": {
            "mood": ambience,
            "materials": decor,
            "lighting": lighting,
            "layout": layout,
            "seating": f"{seating}; {capacity}" if capacity else seating,
        },
        "offer": offer,
        "price_level": concept.get("price_level"),
        "music": {
            "direction": "Artists people within 1.5 km over-index on",
            "artists": artists[:5],
        },
        "partners": partners,
        "image_prompt": None,
    }
