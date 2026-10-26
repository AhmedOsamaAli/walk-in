"""Design sheets: what a concept sells, when it opens, what the unit holds and how it launches, all from the evidence.

The sheet keeps the concept's own name, positioning and signature, so the card and the sheet never disagree, and adds
what the evidence says: the offer (what the places people here love are known for, those no place inside the walk
offers first), the hours those places keep, the unit's capacity, the experience plan from what people here over-index
on, and the launch plan. The owner's rules hold here as on the concepts: every item keeps to them, and the sheet says
how it meets each rule (owner_rules). It describes no decor, mood or partners and makes no pictures: on real surveys
those came out the same everywhere or were invented, and told an owner nothing a search or a chatbot would not.
"""
from __future__ import annotations

import logging

from .. import scoring, space
from ..qloo import QlooClient, QlooError
from . import experience, launch
from .audience import audience as audience_of
from .concepts import owner_rule_lines
from .evidence import area_noun, example_places, gap_for, in_sentence, offer_items
from .experience import fans_of
from .models import RunState

log = logging.getLogger("walkin")

CAPACITY_BASIS = (
    "Planning estimate from the International Building Code occupant load factors (15 ft² per seated guest, 5 per "
    "standing guest) after kitchen, storage and circulation. Check the local code and the unit's certificate."
)
OFFER_SIZE = 6


async def design_concept(run: RunState, index: int, q: QlooClient | None = None) -> dict:
    """The design sheet for concept `index`. With `q`, Qloo says what fans of the category also love (the area's
    signature names those fans share lead the launch plan's audiences) and who the places people here love of this
    kind draw (the audience, and the ad settings it implies)."""
    concept = run.concepts[index]
    row = gap_for(run, concept["genre"])
    shared: set[str] = set()
    people = None
    if row and q is not None:
        try:
            fans = await fans_of(q, run, row["genre_id"])
        except QlooError:
            log.warning("Fan taste lookup failed; planning from the area's taste only", exc_info=True)
        else:
            # Fans of a category are mostly its audience at large, so they only decide the order.
            if fans.get("specific"):
                shared = {card["name"] for card in fans["brands"] + fans["artists"]}
        people = await audience_of(q, row, area_noun(run.site.area))
    site = run.site
    fit = space.fit(concept["genre"], site.size_m2, site.kitchen)
    capacity = fit["capacity_text"] if fit else None
    offer = sheet_offer(run, concept, row)
    hours, hours_basis = opening_hours(row, area_noun(site.area))
    return {
        "name": concept["name"],
        "tagline": concept.get("one_liner"),
        "offer": offer,
        "hours": hours,
        "hours_basis": hours_basis,
        "unit": space.unit_text(site.size_m2, site.kitchen, site.outdoor),
        "capacity": capacity,
        "capacity_basis": CAPACITY_BASIS if capacity else None,
        "experience": experience.plan(run, concept["genre"], theme=concept.get("theme")),
        "audience": people,
        "launch": launch.plan(run, concept, row, shared, hours, people),
        "owner_rules": owner_rule_lines(run, row, {"genre": concept["genre"], "signature": offer}),
        "mode": "rules",
        "model": None,
    }


def sheet_offer(run: RunState, concept: dict, row: dict | None) -> list[str]:
    """What the business sells: the concept's signature, then what the places people here love are known for (those no
    place inside the walk offers first), within the owner's rules; six items at most, none twice."""
    items = [item for item in concept.get("signature") or [] if isinstance(item, str)]
    if row:
        items += [i["item"] for i in offer_items(row, run.constraints, limit=OFFER_SIZE)]
    offer: list[str] = []
    seen: set[str] = set()
    for item in (" ".join(text.split()) for text in items):
        key = scoring.item_key(item)
        if item and key not in seen and not run.constraints.item_problem(item):
            seen.add(key)
            offer.append(item)
    return offer[:OFFER_SIZE]


def sign_text(name: str) -> str:
    """What the sign says: names the evidence rules gave before they invented real ones end with the neighborhood
    ("Seafood, Williamsburg"), which a sign would not."""
    return name.split(",")[0].strip()[:40] or "Opening soon"


def opening_hours(row: dict | None, here: str = "walk") -> tuple[str | None, str | None]:
    """Hours the places people here love of this type keep (competitors inside the area when too few list theirs)."""
    if not row:
        return None, None
    genre = in_sentence(row["genre"])
    found = scoring.typical_hours(example_places(row))
    if found:
        return found["text"], f"Typical hours of the {found['sample']} {genre} places people here love that list them"
    found = scoring.typical_hours(scoring.relevant(row.get("_nearby_entities") or [], row["genre_id"], row["genre"]))
    if found:
        return found["text"], f"Typical hours of {found['sample']} {genre} places inside the {here}"
    return None, None
