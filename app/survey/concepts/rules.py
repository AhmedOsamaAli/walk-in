"""The evidence rules' concepts: the strongest gaps the unit and the owner's notes allow, designed from the evidence
alone; and how the agent's concepts are held to the same measurements (weak gaps replaced, the owner's request first).
"""
from __future__ import annotations

import logging

from ... import scoring
from ..evidence import competition, fits, gap_evidence, offer_items, risk, storefront_favorites
from ..intents import requested_row
from ..models import RunState
from .lines import for_whom, one_liner
from .names import invent_name
from .offer import TOO_BROAD, loses_signature, same_business
from .owner_rules import owner_rule_lines
from .wildcard import with_wildcard

log = logging.getLogger("walkin")


# Below this gap score a category is not a recommendation when stronger ones fit; the owner's own request always is.
WEAK_GAP = 30


def strong_enough(run: RunState, concepts: list[dict], notes: list[str] | None = None) -> list[dict]:
    """Replaces concepts built on weak gaps with the strongest fitting gaps the evidence rules can design, so the agent's
    hunches never outrank what the measurements say; the owner's requested business keeps its place. When no fitting
    gap is strong, nothing is dropped: the survey says so instead (caution). Replacements are added to `notes`."""
    if not any(row["gap_score"] >= WEAK_GAP for row in concept_rows(run)):
        return concepts
    wanted = requested_row(run)
    keep = [c for c in concepts if c["gap_score"] >= WEAK_GAP or wanted and c["genre_id"] == wanted["genre_id"]]
    dropped = [c for c in concepts if c not in keep]
    if dropped:
        log.info("Dropped concepts on weak gaps: %s", ", ".join(c["genre"] for c in dropped))
        if notes is not None:
            notes += [f"Replaced {c['name']} ({scoring.genre_title(c['genre'])}): its gap scores {c['gap_score']} of 100 "
                      f"while stronger gaps fit." for c in dropped]
    for row in concept_rows(run):
        if len(keep) >= 3:
            break
        if row["gap_score"] >= WEAK_GAP and not any(same_business(c["genre"], row["genre"]) for c in keep):
            keep.append(rule_concept(run, row, {c["name"] for c in keep}))
    return keep


def caution(run: RunState, concepts: list[dict]) -> str | None:
    """A plain warning when even the best concept rests on a weak gap. The wildcard is never ranked, so it never counts."""
    scores = [c["gap_score"] for c in concepts if not c.get("wildcard") and c.get("gap_score") is not None]
    if not scores or max(scores) >= WEAK_GAP:
        return None
    return (f"No strong gap here: the best category scores {max(scores)} of 100, so demand and supply are close to "
            f"typical. Treat these as options to test, not as gaps waiting to be filled.")


def concept_rows(run: RunState) -> list[dict]:
    """The rows concepts are built on: the strongest gaps the unit and the owner's notes allow, one per kind of
    business, the owner's requested business first. A category whose every loved item the owner's rules forbid is left
    out: its concept would have nothing to sell."""
    fitting = [
        row for row in run.gaps
        if fits(row) and scoring.genre_key(row["genre"]) not in TOO_BROAD and not loses_signature(run, row)
    ]
    solid = [row for row in fitting if row.get("evidence") == "ok"]
    rows: list[dict] = []
    for row in solid or fitting:
        if not any(same_business(row["genre"], kept["genre"]) for kept in rows):
            rows.append(row)
    rows = rows[:3]
    wanted = requested_row(run)
    if wanted:
        rows = [wanted] + [row for row in rows if not same_business(row["genre"], wanted["genre"])][:2]
    return rows


def rule_concepts(run: RunState) -> list[dict]:
    """The evidence rules' concepts: the strongest rows the unit and the notes allow, then the wildcard, if any."""
    concepts: list[dict] = []
    for row in concept_rows(run):
        concepts.append(rule_concept(run, row, {c["name"] for c in concepts}))
    return with_wildcard(run, concepts)


def rule_concept(run: RunState, row: dict, taken: set[str] | None = None) -> dict:
    """A concept built from the evidence alone, within the owner's rules; `taken` holds names other concepts have."""
    area, ages = run.site.area, run.site.ages
    _, cards = storefront_favorites(row)
    concept = {
        "name": invent_name(run, row["genre"], set(taken or ())),
        "genre": row["genre"],
        "genre_id": row["genre_id"],
        "gap_score": row["gap_score"],
        "one_liner": one_liner(row, area, ages),
        "for_whom": for_whom(row, area, ages),
        "why_here": gap_evidence(row, area, ages),
        "beat_competitors": competition(row, area, run.constraints, ages),
        "signature": [i["item"] for i in offer_items(row, run.constraints, limit=3)],
        "inspired_by": [card["name"] for card in cards[:3] if card.get("name")],
        "risk": risk(row, area, ages),
        "evidence": gap_evidence(row, area, ages),
    }
    concept["owner_rules"] = owner_rule_lines(run, row, concept)
    return concept


def requested_first(run: RunState, concepts: list[dict]) -> list[dict]:
    """The owner's requested business leads the concepts; the evidence rules design it when the agent did not."""
    wanted = requested_row(run)
    if not wanted or not concepts:
        return concepts
    mine = next((c for c in concepts if c["genre_id"] == wanted["genre_id"]), None) or rule_concept(
        run, wanted, {c["name"] for c in concepts},
    )
    return [mine] + [c for c in concepts if not same_business(c["genre"], wanted["genre"])][:2]
