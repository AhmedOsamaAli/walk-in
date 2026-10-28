"""The agent's concepts checked against the evidence: real genres, real places, original names, every factual line
rebuilt from the measurements, and what breaks the owner's rules repaired once or dropped, with the reason.
"""
from __future__ import annotations

from ... import scoring
from ..evidence import competition, fits, gap_evidence, gap_for, people_here, risk, storefront_favorites
from ..models import RunState
from .lines import FILLER, for_whom, grounded_line, one_liner, without_names
from .names import concept_name, place_names
from .offer import TOO_BROAD, ruled_signature, same_business
from .owner_rules import misfit, owner_rule_lines, removed_text, rule_problems


def ground_names(names: list[str] | None, allowed: set[str]) -> list[str]:
    allowed_lower = {a.lower(): a for a in allowed}
    return [allowed_lower[n.lower()] for n in names or [] if isinstance(n, str) and n.lower() in allowed_lower]


def clean_concepts(run: RunState, concepts: list[dict], notes: list[str] | None = None) -> list[dict]:
    """Keep only concepts whose genre exists in the evidence and that the unit and the owner's notes allow, one per kind
    of business, citing real places under original names, stocked as the evidence and the notes say.

    The model contributes the creative parts (name, positioning, signature items). Every factual line (why here, who
    for, the competition, the risk) is rebuilt from the measured evidence, so a misread number never reaches the owner.
    What breaks the owner's rules is repaired once; a concept that still breaks one is dropped. Repairs and drops are
    added to `notes`, in plain words.
    """
    notes = notes if notes is not None else []
    cleaned: list[dict] = []
    known_places = place_names(run)
    area, ages = run.site.area, run.site.ages
    for concept in concepts or []:
        if not isinstance(concept, dict):
            continue
        row = gap_for(run, str(concept.get("genre") or ""))
        if not row or scoring.genre_key(row["genre"]) in TOO_BROAD:
            label = " ".join(str(concept.get("name") or "A concept").split())[:60]
            why = (f"{concept.get('genre')!r} is not a category the survey measured" if not row
                   else f"{row['genre']} is too broad to open as one business")
            notes.append(f"Dropped {label}: {why}.")
            continue
        proposed = " ".join(str(concept.get("name") or "").split())[:60]
        label = f"{proposed or 'A concept'} ({scoring.genre_title(row['genre'])})"
        if not fits(row):
            notes.append(f"Dropped {label}: {misfit(row)}.")
            continue
        if any(same_business(c["genre"], row["genre"]) for c in cleaned):
            continue
        favorites = {card["name"] for card in storefront_favorites(row)[1] if card.get("name")}
        concept["genre"] = row["genre"]
        concept["genre_id"] = row["genre_id"]
        concept["gap_score"] = row["gap_score"]
        concept["inspired_by"] = ground_names(concept.get("inspired_by"), favorites)[:4] or [
            card["name"] for card in storefront_favorites(row)[1][:3] if card.get("name")
        ]
        concept["name"] = concept_name(run, row, proposed, {c["name"] for c in cleaned}, known_places, notes)
        concept["one_liner"] = ruled_line(run, row, str(concept.get("one_liner") or ""), concept["name"], notes)
        for key in ("price_level", "price_basis", "price_anchors"):
            concept.pop(key, None)
        signature, removed = ruled_signature(concept.get("signature"), row, run)
        if removed:
            notes.append(f"{concept['name']}: took out {removed_text(removed)}.")
        if removed and not signature:
            notes.append(f"Dropped {concept['name']} ({scoring.genre_title(row['genre'])}): nothing on its menu works "
                         f"under your rules, and the places {people_here(ages)} love offer nothing that does.")
            continue
        concept["signature"] = signature
        concept["for_whom"] = for_whom(row, area, ages)
        concept["why_here"] = gap_evidence(row, area, ages)
        concept["beat_competitors"] = competition(row, area, run.constraints, ages)
        concept["risk"] = risk(row, area, ages)
        concept["evidence"] = concept["why_here"]
        concept["owner_rules"] = owner_rule_lines(run, row, concept)
        problems = rule_problems(run, row, concept)
        if problems:
            notes.append(f"Dropped {concept['name']} ({scoring.genre_title(row['genre'])}): {'; '.join(problems)}.")
            continue
        cleaned.append(concept)
    return cleaned[:3]


def ruled_line(run: RunState, row: dict, text: str, name: str, notes: list[str]) -> str:
    """The model's positioning, grounded (grounded_line), unless it describes something the owner's rules forbid (fried
    chicken in a unit without a hood, 'upscale' on a budget) or leans on filler ('cozy', 'vibe') where it should say
    what the place is; then the evidence's own line."""
    line = grounded_line(text, row, run.site, also=name)
    clash = run.constraints.item_clash(line)
    filler = FILLER.search(without_names(line, (name, run.site.label)))
    if clash:
        notes.append(f"{name}: its one-liner mentioned '{clash[0]}', which {clash[1]}; the evidence's own line "
                     f"replaces it.")
    elif filler:
        notes.append(f"{name}: its one-liner leaned on '{filler.group(0)}', which nothing measured backs; the "
                     f"evidence's own line replaces it.")
    else:
        return line
    return one_liner(row, run.site.area, run.site.ages)
