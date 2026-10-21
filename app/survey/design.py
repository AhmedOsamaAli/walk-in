"""Design sheets: what a concept looks, sounds and feels like, and the prompts for its renders."""
from __future__ import annotations

import copy
import json
import logging
from typing import Any

from .. import scoring
from ..answers import AnswerCache, fingerprint
from ..images import Images
from ..llm import LLM
from ..qloo import QlooClient, QlooError
from .concepts import ground_names
from .evidence import describe_age, gap_for, storefront_favorites
from .experience import fans_of
from .models import RunState

log = logging.getLogger("blankspace")


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
