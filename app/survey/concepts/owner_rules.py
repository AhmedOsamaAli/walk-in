"""How each concept meets the owner's rules (the unit's size and kitchen, the price band) in lines it carries, and the
problems that drop a concept that still breaks one.
"""
from __future__ import annotations

import re

from ... import scoring, space
from ..evidence import fits
from ..models import RunState
from .names import placeholder_name


def misfit(row: dict) -> str:
    """Why a category cannot be proposed here, after 'Dropped X:'."""
    if row.get("ruled_out"):
        return f"your notes rule it out (it {row['ruled_out']})"
    return f"the unit cannot host it (it {(row.get('fit') or {}).get('reason')})"


def removed_text(removed: list[tuple[str, str]]) -> str:
    """'Crispy potatoes (it needs a deep fryer under an extraction hood) and Truffle pizza (it needs a pizza oven …)'."""
    return scoring.natural_list([f"{item} (it {why})" for item, why in removed])


# Food a ventless oven finishes; anything else on a no-hood menu is assembled cold.
BAKED_ITEM = re.compile(
    r"\b(bak(e|ed|es|ery)|breads?|buns?|rolls?|muffins?|croissants?|pastr(y|ies)|cakes?|cookies?|brownies?|tarts?|"
    r"pies?|scones?|focaccia|flatbreads?|toasts?|toasties|quiches?|galettes?|kolaches?|danish|biscuits?|bagels?|"
    r"loaf|loaves|pretzels?|gratin|lasagn[ae]|roast(ed)?|feteer|fatayer|man[a']?(kish|oushe)|pitas?|sourdough|"
    r"crumble|cobbler|brul[eé]e|souffl[eé]|madeleines?|cinnamon|knafeh|kunafa|basbousa|baklava)\b",
    re.IGNORECASE,
)


DRINK_ITEM = re.compile(
    r"\b(lattes?|coffee|espresso|cappuccino|americano|macchiato|mocha|cold brew|teas?|matcha|chai|juices?|smoothies?|"
    r"shakes?|milkshakes?|lemonade|sodas?|tonic|wines?|cocktails?|martinis?|beers?|cider|spritz|kombucha|cocoa|"
    r"hot chocolate|sahlab|horchata|drinks?|mocktails?|sake|whiske?y|mead|flights?|floats?|egg creams?)\b",
    re.IGNORECASE,
)


def unit_line(run: RunState, genre: str) -> str | None:
    """How a concept of this kind fits the unit, when the owner gave its size: 'Fits 45 m² (484 ft²): a bar counter
    and about 20–24 seats at most.' Capacity is the building-code estimate the design sheet uses."""
    size = run.site.size_m2 or run.constraints.size_m2
    if not size:
        return None
    area = space.size_text(size)
    cap = space.capacity(size, genre)
    kind = scoring.genre_kind(genre)
    if cap:
        count = f"{cap['low']}" if cap["low"] == cap["high"] else f"{cap['low']}–{cap['high']}"
        if cap["mode"] == "standing":
            return f"Fits {area}: a bar along one wall and room for about {count} standing guests at most."
        counter = "a bar counter" if kind == "bar" else "a counter"
        return f"Fits {area}: {counter} and about {count} seats at most."
    if kind == "retail":
        return f"Fits {area}: a shop floor with a counter."
    return f"Fits {area}: a front desk and a studio or treatment room."


def kitchen_line(run: RunState, genre: str, items: list[str]) -> str | None:
    """How a concept works without an extraction hood (or a kitchen), when the unit has none: the method for its menu."""
    rules = run.constraints
    if not rules.hood_free:
        return None
    kind = scoring.genre_kind(genre)
    if kind in ("retail", "wellness"):
        return "Needs no kitchen: nothing is cooked." if rules.no_cooking else "Needs no hood: nothing is cooked."
    counter = "the bar" if kind in ("bar", "venue") else "the counter"
    if rules.no_cooking:
        return (f"Needs no kitchen: nothing is cooked on site; drinks are made at {counter} and the food comes in ready to "
                f"serve or is assembled cold.")
    food = [item for item in items if not DRINK_ITEM.search(item)]
    drinks = kind in ("bar", "venue") or any(DRINK_ITEM.search(item) for item in items)
    if kind == "venue" and not any(BAKED_ITEM.search(item) for item in food):
        made = "drinks come from the bar and snacks are assembled cold"
    elif not food:
        made = f"drinks are made at {counter} and any food is assembled cold or comes in ready to serve"
    else:
        ways = [way for way, used in (
            ("baked in a ventless oven", any(BAKED_ITEM.search(item) for item in food)),
            ("assembled cold", any(not BAKED_ITEM.search(item) for item in food)),
        ) if used]
        made = (f"drinks are made at {counter} and " if drinks else "") + f"the food is {' or '.join(ways)}"
    return f"No hood needed: {made}; nothing is fried, grilled or cooked on a flat-top."


# How a concept keeps the owner's price band, in words: no price level is given, so the band is kept in what the
# concept says about itself (Constraints.price_words).
PRICE_LINES = {
    "budget": "Budget prices: nothing in it is called upscale or premium.",
    "mid-range": "Mid-range prices: nothing in it is called upscale or cheap.",
    "upscale": "Upscale prices: nothing in it is called cheap or budget.",
}


def price_line(run: RunState) -> str | None:
    """How the concept keeps the price band the owner's notes set; None when they set none."""
    return PRICE_LINES.get(run.constraints.price or "")


def owner_rule_lines(run: RunState, row: dict | None, concept: dict) -> list[str]:
    """How the concept meets each rule the owner gave, in plain words: the unit's size, the kitchen, the price band,
    the diet and who it is for."""
    rules = run.constraints
    genre = concept.get("genre") or (row or {}).get("genre") or ""
    items = [item for item in concept.get("signature") or [] if isinstance(item, str)]
    lines = [unit_line(run, genre), kitchen_line(run, genre, items), price_line(run)]
    if rules.vegetarian:
        lines.append("Vegetarian: no meat or fish on the menu.")
    if rules.halal:
        lines.append("Halal: no pork and no alcohol.")
    elif rules.no_alcohol:
        lines.append("No alcohol on the menu.")
    if rules.family:
        lines.append("Family friendly: no bar and no nightlife.")
    return [line for line in lines if line]


def rule_problems(run: RunState, row: dict, concept: dict) -> list[str]:
    """What still breaks the owner's rules after the repair, each as a phrase; empty when the concept keeps them all."""
    rules = run.constraints
    problems = [] if fits(row) else [misfit(row)]
    problems += [f"{item} {why}" for item in concept.get("signature") or [] if (why := rules.item_problem(item))]
    for key, label in (("name", "name"), ("one_liner", "one-liner")):
        why = rules.item_problem(str(concept.get(key) or ""))
        if why:
            problems.append(f"its {label} names something that {why}")
    if placeholder_name(str(concept.get("name") or ""), concept["genre"], run.site.label):
        problems.append("it has no real name")
    said = " ".join(concept.get("owner_rules") or [])
    if (run.site.size_m2 or rules.size_m2) and "Fits " not in said:
        problems.append("it does not say how it fits the unit")
    if rules.hood_free and not re.search(r"\b(hood|kitchen)\b", said):
        problems.append("it does not say how it works without a hood")
    if rules.price and price_line(run) not in (concept.get("owner_rules") or []):
        problems.append("it does not say how it keeps your price band")
    return problems
