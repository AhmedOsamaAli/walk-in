"""app.survey.concepts became a package, one module per job; every name the old module offered is still importable
from it, so callers and tests keep working, and the modules only import downward (no cycles)."""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

from app.survey import concepts

# Every name app/survey/concepts.py defined (before it became a package), and the evidence helpers it handed on.
OLD_DEFINITIONS = [
    "AGENT_VERSION", "AgentResult", "BAKED_ITEM", "BASELINE_SYSTEM", "CATEGORY_NAME_WORDS", "COMBINABLE",
    "COMMON_NAME_WORDS", "CONCEPT_SYSTEM", "CONCEPT_TOOLS", "DIGITS", "DRINK_ITEM", "FILLER", "FILLER_NAME_WORDS",
    "KIND_NOUNS", "LIGHT_FORMAT", "MAX_FAN_CHECKS", "MAX_LIVE_TESTS", "NAME_NOUNS", "NAME_WORDS", "NEAR_DUPLICATES",
    "NEXT_DOOR", "NOT_A_SIGNATURE", "PRICE_LINES", "REASON", "THEMED_CAUTION", "TOO_BROAD", "TOP_DEMAND", "UNIT_CLAIM",
    "WEAK_GAP", "WILDCARD_CAUTION", "_name_words", "agent_brief", "agent_concepts", "area_figures", "article",
    "baseline_concepts", "carries", "caution", "clean_concepts", "combinable", "combined_inside", "concept_name",
    "concept_rows", "concepts_from_agent", "for_whom", "ground_names", "grounded_line", "invent_name", "kitchen_line",
    "loses_signature", "loved_rows", "misfit", "name_core", "name_noun", "neighbors", "one_liner", "owner_rule_lines",
    "place_kind", "place_names", "placeholder_name", "plain_number", "price_line", "proposed_line", "proposed_name",
    "removed_text", "replay_agent", "requested_first", "rule_concept", "rule_concepts", "rule_problems", "ruled_items",
    "ruled_line", "ruled_signature", "same_business", "same_item", "signature_of", "stray_numbers", "strong_enough",
    "submitted", "taken_name", "themed_base", "themed_concept", "themed_line", "themed_wildcard", "unit_line",
    "unit_supports", "wildcard_brief", "wildcard_concept", "wildcard_items", "wildcard_line", "wildcard_pair",
    "with_notes", "with_wildcard", "without_names",
]
HANDED_ON = [
    "aged", "annotate", "area_noun", "capitalized", "competition", "count_of", "crowd_of", "evidence_brief", "fits",
    "gap_evidence", "gap_for", "gap_summary", "in_running_text", "in_sentence", "inspect_payload", "is_walk",
    "love_evidence", "offer_items", "people_here", "plural", "public_gap", "risk", "short_label", "singular",
    "storefront_favorites", "supply",
]
# Each module may import only the modules before it in this order.
LAYERS = ["names", "lines", "offer", "owner_rules", "wildcard", "rules", "grounding", "agent", "baseline"]
PACKAGE = Path(concepts.__file__).parent


def test_every_name_the_module_offered_is_still_there():
    missing = [name for name in OLD_DEFINITIONS + HANDED_ON if not hasattr(concepts, name)]
    assert missing == []


def test_each_name_is_the_one_its_module_defines():
    from app.survey import evidence

    for name in OLD_DEFINITIONS:
        home = next(module for module in LAYERS if name in ast_definitions(module))
        assert getattr(concepts, name) is getattr(importlib.import_module(f"app.survey.concepts.{home}"), name), name
    assert all(getattr(concepts, name) is getattr(evidence, name) for name in HANDED_ON)


def ast_definitions(module: str) -> set[str]:
    tree = ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return names


def test_the_modules_only_import_downward():
    for position, module in enumerate(LAYERS):
        tree = ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))
        siblings = {node.module for node in tree.body if isinstance(node, ast.ImportFrom) and node.level == 1}
        assert siblings <= set(LAYERS[:position]), (module, siblings - set(LAYERS[:position]))
        assert ast.get_docstring(tree), f"{module} says what it is for"
