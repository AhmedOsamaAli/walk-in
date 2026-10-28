"""Business concepts for a site: the agent with live Qloo tools, the evidence rules behind it, and the
grounding that keeps both to what the evidence says.

The owner's rules are hard rules for both: a price band means nothing the concept says about itself contradicts it (a
budget place is never called upscale), a unit without a hood means nothing that needs one, a size means every concept
fits it, and every concept says how it meets each rule (owner_rules). No concept carries a price level: Qloo's are
dollar signs with no amounts behind them. The agent is told the rules, and its answer is checked after it answers: what
breaks a rule is repaired once (items taken out and replaced from the evidence, the evidence's own line, a real name
given) and a concept that still breaks one is dropped, with the reason in the payload's notes. A wildcard may follow
the ranked concepts: a kind of place people here love, hosting what they watch, hear and follow (themed_wildcard), or
else two things people here love, combined into a business no place inside the area is (wildcard_concept).

The package, by job:

names        business names: original, never a category plus the neighborhood, never an existing place's
lines        what a concept says, and the checks that keep the model's lines to the evidence
offer        what a concept sells, within the owner's rules; which categories are one business
owner_rules  how each concept meets the owner's rules, and what drops one that breaks them
wildcard     the wildcard: a theme people here follow, or two loves combined
rules        the evidence rules' concepts, and the measurements the agent's are held to
grounding    the agent's concepts checked and repaired against the evidence
agent        the agent with live Qloo tools, its prompt, budget and replay
baseline     what a model suggests with no data
"""
from __future__ import annotations

from ..evidence import (  # noqa: F401
    aged,
    annotate,
    area_noun,
    capitalized,
    competition,
    count_of,
    crowd_of,
    evidence_brief,
    fits,
    gap_evidence,
    gap_for,
    gap_summary,
    in_running_text,
    in_sentence,
    inspect_payload,
    is_walk,
    love_evidence,
    offer_items,
    people_here,
    plural,
    public_gap,
    risk,
    short_label,
    singular,
    storefront_favorites,
    supply,
)
from .agent import (  # noqa: F401
    AGENT_VERSION,
    CONCEPT_SYSTEM,
    CONCEPT_TOOLS,
    MAX_FAN_CHECKS,
    MAX_LIVE_TESTS,
    REASON,
    AgentResult,
    agent_brief,
    agent_concepts,
    concepts_from_agent,
    replay_agent,
    submitted,
    wildcard_brief,
    with_notes,
)
from .baseline import (  # noqa: F401
    BASELINE_SYSTEM,
    baseline_concepts,
)
from .grounding import (  # noqa: F401
    clean_concepts,
    ground_names,
    ruled_line,
)
from .lines import (  # noqa: F401
    DIGITS,
    FILLER,
    NEXT_DOOR,
    TOP_DEMAND,
    UNIT_CLAIM,
    area_figures,
    for_whom,
    grounded_line,
    neighbors,
    one_liner,
    plain_number,
    stray_numbers,
    unit_supports,
    without_names,
)
from .names import (  # noqa: F401
    CATEGORY_NAME_WORDS,
    COMMON_NAME_WORDS,
    FILLER_NAME_WORDS,
    KIND_NOUNS,
    NAME_NOUNS,
    NAME_WORDS,
    _name_words,
    concept_name,
    invent_name,
    name_core,
    name_noun,
    place_names,
    placeholder_name,
    taken_name,
)
from .offer import (  # noqa: F401
    NEAR_DUPLICATES,
    NOT_A_SIGNATURE,
    TOO_BROAD,
    loses_signature,
    ruled_items,
    ruled_signature,
    same_business,
    same_item,
    signature_of,
)
from .owner_rules import (  # noqa: F401
    BAKED_ITEM,
    DRINK_ITEM,
    PRICE_LINES,
    kitchen_line,
    misfit,
    owner_rule_lines,
    price_line,
    removed_text,
    rule_problems,
    unit_line,
)
from .rules import (  # noqa: F401
    WEAK_GAP,
    caution,
    concept_rows,
    requested_first,
    rule_concept,
    rule_concepts,
    strong_enough,
)
from .wildcard import (  # noqa: F401
    COMBINABLE,
    LIGHT_FORMAT,
    THEMED_CAUTION,
    WILDCARD_CAUTION,
    article,
    carries,
    combinable,
    combined_inside,
    loved_rows,
    place_kind,
    proposed_line,
    proposed_name,
    themed_base,
    themed_concept,
    themed_line,
    themed_wildcard,
    wildcard_concept,
    wildcard_items,
    wildcard_line,
    wildcard_pair,
    with_wildcard,
)
