"""What a language model suggests with no data, shown next to the evidence-based concepts.
"""
from __future__ import annotations

from ...answers import AnswerCache, fingerprint
from ...llm import LLM
from ..models import Site

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
