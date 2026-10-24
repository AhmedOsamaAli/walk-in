"""The wildcard: at most one extra concept after the ranked ones, combining two things people here demonstrably love into
a business no place inside the walk already is. It keeps the owner's rules, says it is untested, and never counts in a
ranking."""
from __future__ import annotations

import json

from app import schemas
from app.survey import concepts
from tests.test_e2e import RUN_PARAMS, first, make_client, scripted_llm, sse_events, tool_call
from tests.test_owner_rules import burger_joint, cocktail_bar, coffee_shop, gap, venue, world

CAUTION = ("Untested: nothing like this exists nearby, so there is no direct proof people would come; it rests on two "
           "separate loves.")


def wildcard_of(built: list[dict]) -> dict | None:
    return next((c for c in built if c.get("wildcard")), None)


def test_two_loves_no_place_combines_make_a_wildcard_after_the_ranked_concepts():
    run = world()
    built = concepts.rule_concepts(run)
    wildcard = built[-1]
    assert [c.get("wildcard", False) for c in built] == [False] * (len(built) - 1) + [True]
    # People here travel for both cocktail bars and coffee shops, and no place inside the walk is both.
    assert wildcard["combines"] == [
        {"item": "cocktail bars", "genre": "Cocktail bar",
         "source": "People here travel a median 2.5 km to the cocktail bars they love most, such as Velvet Room 0 and "
                   "Velvet Room 1 (Qloo)."},
        {"item": "coffee shops", "genre": "Coffee shop",
         "source": "People here travel a median 2.5 km to the coffee shops they love most, such as Bean There 0 and "
                   "Bean There 1 (Qloo)."},
    ]
    assert wildcard["caution"] == CAUTION and wildcard["risk"] == CAUTION
    assert wildcard["gap_score"] is None and wildcard["genre"] == "Cocktail bar"
    assert wildcard["one_liner"] == ("A coffee shop by day and a cocktail bar by night, under one roof: two things people "
                                     "here love, and nothing inside the 10-minute walk is both.")
    assert wildcard["why_here"][-1] == "No place inside the 10-minute walk is both a cocktail bar and a coffee shop."
    assert wildcard["signature"] == ["Banana espresso martini", "Deviled eggs", "Ube latte", "Orange olive oil muffin"]
    assert wildcard["name"].endswith("Cocktails & Coffee") and wildcard["name"] not in [c["name"] for c in built[:-1]]
    assert not concepts.placeholder_name(wildcard["name"], wildcard["genre"], run.site.label)
    # The payload shape is the documented one.
    for concept in built:
        assert schemas.Concept.model_validate(concept).name == concept["name"]
    assert schemas.Concept.model_validate(wildcard).combines[1].genre == "Coffee shop"


def test_a_combination_that_already_exists_inside_the_walk_is_no_wildcard():
    both = venue("Corner Café Bar", "Cocktail bar", 77, 2, km=0.1)
    both["tags"].append({"id": "urn:tag:genre:place:test_coffee-shop", "name": "Coffee shop", "type": "urn:tag:genre:place"})
    run = world(rows=[cocktail_bar(), coffee_shop()])
    run.block.append(both)
    assert concepts.wildcard_pair(run) is None and wildcard_of(concepts.rule_concepts(run)) is None
    # With a third love, the next combination nobody offers is the wildcard instead.
    run = world()
    run.block.append(both)
    wildcard = wildcard_of(concepts.rule_concepts(run))
    assert [side["genre"] for side in wildcard["combines"]] == ["Cocktail bar", "Hamburger restaurant"]


def test_no_wildcard_when_the_evidence_does_not_show_two_loves():
    lukewarm = {"favorites_kind": "citywide", "leakage": None, "lift": 0.0}
    rows = [cocktail_bar(demand_rank=12, **lukewarm), coffee_shop(demand_rank=14, **lukewarm)]
    run = world(rows=rows)
    assert concepts.wildcard_pair(run) is None
    assert all(not c.get("wildcard") for c in concepts.rule_concepts(run))
    # One love is not enough either, nor a thin or broad category.
    run = world(rows=[cocktail_bar(), coffee_shop(demand_rank=14, **lukewarm), burger_joint(evidence="thin")])
    assert concepts.wildcard_pair(run) is None


def test_the_wildcard_keeps_the_owners_rules():
    # Halal: a bar is never one of the two loves; the cafe and the burger place combine instead, and on a budget it
    # carries no price, only how it keeps the band.
    run = world("halal, family friendly, budget prices")
    wildcard = wildcard_of(concepts.rule_concepts(run))
    assert [side["genre"] for side in wildcard["combines"]] == ["Coffee shop", "Hamburger restaurant"]
    assert "price_level" not in wildcard and concepts.PRICE_LINES["budget"] in wildcard["owner_rules"]
    assert {"Halal: no pork and no alcohol.", "Family friendly: no bar and no nightlife."} <= set(wildcard["owner_rules"])
    # No hood: nothing on it needs one, it says how it works and how it fits the unit.
    run = world("vegetarian, no extraction hood", size_m2=45, kitchen="light")
    wildcard = wildcard_of(concepts.rule_concepts(run))
    assert all(run.constraints.allows_item(item) for item in wildcard["signature"])
    assert wildcard["owner_rules"][0] == "Fits 45 m² (484 ft²): a bar counter and about 20–24 seats at most."
    assert wildcard["owner_rules"][1].startswith("No hood needed: drinks are made at the bar and the food is baked in a "
                                                 "ventless oven or assembled cold")
    assert concepts.rule_problems(run, concepts.gap_for(run, "Cocktail bar"), wildcard) == []


def test_the_wildcard_never_counts_in_a_ranking():
    run = world()
    ranked = [c for c in concepts.rule_concepts(run) if not c.get("wildcard")]
    weak = [{**c, "gap_score": 12} for c in ranked]
    wildcard = concepts.wildcard_concept(run, weak)
    # The caution reads the ranked concepts only; the wildcard has no score to count.
    assert concepts.caution(run, [*weak, wildcard]).startswith("No strong gap here: the best category scores 12 of 100")
    assert concepts.caution(run, [*ranked, wildcard]) is None
    # It only ever follows ranked concepts, and comes last.
    assert concepts.with_wildcard(run, []) == [] and concepts.with_wildcard(run, ranked)[-1]["wildcard"] is True


def test_the_models_wildcard_is_kept_where_it_passes_the_same_checks():
    run = world("no hood", size_m2=45)
    ranked = [c for c in concepts.rule_concepts(run) if not c.get("wildcard")]
    notes: list[str] = []
    proposal = {"name": "Night Shift", "one_liner": "Espresso until five, then espresso martinis until late",
                "signature": ["Ube latte", "Banana espresso martini", "Crispy potatoes"]}
    wildcard = concepts.wildcard_concept(run, ranked, proposal, notes)
    assert wildcard["name"] == "Night Shift" and wildcard["one_liner"] == proposal["one_liner"]
    assert wildcard["signature"][:2] == ["Ube latte", "Banana espresso martini"] and "Crispy potatoes" not in wildcard["signature"]
    assert notes == ["Night Shift: took out Crispy potatoes (it needs a deep fryer under an extraction hood)."]
    # A placeholder name, a seat count the unit cannot check and a fried promise all give way to the evidence's own.
    bad = {"name": "Cocktail Bar, Williamsburg", "one_liner": "A 60-seat room for fried chicken and cocktails"}
    wildcard = concepts.wildcard_concept(run, ranked, bad, [])
    assert not concepts.placeholder_name(wildcard["name"], "Cocktail bar", run.site.label)
    assert wildcard["one_liner"].startswith("A coffee shop by day and a cocktail bar by night")


def test_the_agent_names_the_wildcard_from_the_candidate_it_is_shown():
    requests: list[dict] = []
    submit = [tool_call("c1", "submit_concepts", {
        "concepts": [{"name": "Tide & Table", "genre": "Seafood", "one_liner": "Raw bar", "signature": ["Oysters"]}],
        "wildcard": {"name": "Shuck & Pour", "one_liner": "Oysters at the counter, a wine list to match",
                     "signature": ["Oysters", "Orange wine"]},
    })]
    with make_client(llm=scripted_llm([submit], requests)) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        payload = first(events, "concepts")
        agent_request = next(body for body in requests if body.get("tools"))
        brief = json.loads(agent_request["messages"][1]["content"].removeprefix("Evidence pack:\n"))
        candidate = brief["wildcard_candidate"]
        assert [side["genre"] for side in candidate["combines"]] == ["Seafood", "Wine Bar"]
        assert candidate["inside_the_area"] == "no place is both"
        wildcard = payload["concepts"][-1]
        assert wildcard["wildcard"] is True and wildcard["name"] == "Shuck & Pour"
        assert wildcard["one_liner"] == "Oysters at the counter, a wine list to match"
        assert wildcard["signature"] == ["Oysters", "Orange wine"] and wildcard["gap_score"] is None
        assert payload["concepts"][0]["name"] == "Tide & Table"
        assert not any(c.get("wildcard") for c in payload["concepts"][:-1])
        # It has a design sheet like any concept.
        run_id = first(events, "run")["run_id"]
        sheet = client.post("/api/design", json={"run_id": run_id, "index": len(payload["concepts"]) - 1}).json()
        assert sheet["name"] == "Shuck & Pour" and sheet["offer"][:2] == ["Oysters", "Orange wine"]


def test_a_wildcard_item_the_rules_forbid_never_reaches_the_owner():
    loved = [venue(f"Bean There {i}", "Coffee shop", 20 + i, 2, ("Churros", "Ube latte")) for i in range(3)]
    run = world("no hood", rows=[cocktail_bar(), gap("Coffee shop", loved, [], rank=5, score=45)])
    wildcard = wildcard_of(concepts.rule_concepts(run))
    assert "Churros" not in wildcard["signature"] and "Ube latte" in wildcard["signature"]
    assert all(item["item"] != "Churros" for item in concepts.offer_items(concepts.gap_for(run, "Coffee shop"), run.constraints))
