"""The owner's free-text notes read as hard constraints, so both the agent and the evidence rules respect them.

Only plain, common instructions are recognized (alcohol, family friendly, halal, vegetarian, price range, unit size,
kitchen and outdoor space); anything else stays a note the agent reads. What was understood is listed back to the user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import scoring

FT2_PER_M2 = 10.7639

NO_ALCOHOL = re.compile(
    r"\b(no|without|not? an?|non[- ]?|zero)[- ]?(alcohol|booze|liquor|drinks? licen[cs]e|alcohol licen[cs]e|"
    r"licen[cs]e|alcoholic|bar)\b|\balcohol[- ]free\b|\bdry (venue|concept|shop)\b|\bsober\b|\bhalal\b",
    re.IGNORECASE,
)
HALAL = re.compile(r"\bhalal\b|\bno pork\b|\bpork[- ]free\b", re.IGNORECASE)
FAMILY = re.compile(r"\b(family|families|kids?|children|child[- ]friendly|all ages)\b", re.IGNORECASE)
VEGETARIAN = re.compile(r"\b(vegetarian|vegan|plant[- ]based|meat[- ]free)\b", re.IGNORECASE)
CHEAP = re.compile(r"\b(cheap|budget|affordable|inexpensive|low[- ]cost|low[- ]price[ds]?)\b", re.IGNORECASE)
MID = re.compile(r"\b(mid[- ]?range|mid[- ]?price[ds]?|moderate(ly priced)?|mid[- ]market)\b", re.IGNORECASE)
UPSCALE = re.compile(r"\b(upscale|high[- ]end|premium|luxury|fine[- ]dining)\b", re.IGNORECASE)
SIZE = re.compile(
    r"(\d{1,3}(?:,\d{3})+|\d{2,5}(?:\.\d+)?)\s*(m²|m2|sqm|sq\.? ?m\b|square met(?:er|re)s?|ft²|ft2|sq\.? ?ft|square f(?:ee|oo)t)",
    re.IGNORECASE,
)
NO_KITCHEN = re.compile(r"\bno (kitchen|cooking|stove)\b", re.IGNORECASE)
LIGHT_KITCHEN = re.compile(r"\b(no (hood|extraction|vent(ilation)?)|light (kitchen|prep)|prep only)\b", re.IGNORECASE)
FULL_KITCHEN = re.compile(r"\bfull(y equipped)? kitchen\b|\bhas (a )?(hood|extraction)\b", re.IGNORECASE)
NO_OUTDOOR = re.compile(r"\bno (outdoor|patio|terrace|sidewalk|garden)\b", re.IGNORECASE)
OUTDOOR = re.compile(r"\b(patio|terrace|garden|outdoor (space|seating)|sidewalk seating)\b", re.IGNORECASE)

# Categories whose business is serving alcohol, or that are adults-only at night.
ALCOHOL_GENRE = re.compile(
    r"\b(bar|pub|wine|cocktail|brewery|brewpub|beer|taproom|tavern|distillery|winery|cider|sake|izakaya|"
    r"night ?club|lounge|speakeasy|gastropub|biergarten|beer garden)\b",
    re.IGNORECASE,
)
ADULTS_GENRE = re.compile(r"\b(night ?club|cocktail|wine bar|pub|bar|lounge|hookah|shisha|cigar|strip|adult|casino|tattoo)\b", re.IGNORECASE)
# Bars that are mostly about something else a family can share.
FAMILY_SAFE = re.compile(r"\b(juice|salad|sushi|snack|oyster|raw|espresso|coffee|tea|dessert|ice cream|milk|yogurt)\b", re.IGNORECASE)
# Places that never serve alcohol, whatever their name says.
DRY_BY_NATURE = re.compile(rf"{FAMILY_SAFE.pattern}|\b(hookah|shisha|cafe|café)\b", re.IGNORECASE)
ALCOHOL_ITEM = re.compile(
    r"\b(wine|wines|beer|beers|ale|ipa|lager|stout|cocktails?|mimosas?|bloody mary|margaritas?|sangria|spritz|"
    r"aperol|mezcal|tequila|whiske?y|bourbon|rum|gin|vodka|sake|soju|cider|prosecco|champagne|martinis?|negroni|"
    r"old fashioned|amaro|pisco|punch bowls?|happy hour|brewery tours?|beer tasting|wine tasting|tasting flights?|"
    r"craft beer|on tap|drinks list|mulled wine|booze|liquor|shots?)\b",
    re.IGNORECASE,
)
PORK_ITEM = re.compile(r"\b(pork|bacon|ham|prosciutto|chorizo|pancetta|lechon|carnitas|salami|pepperoni|sausages?|bratwurst|brats|hot dogs?|currywurst|ribs)\b", re.IGNORECASE)
MEAT_ITEM = re.compile(
    r"\b(beef|steak|brisket|burgers?|chicken|wings|pork|bacon|ham|lamb|veal|duck|turkey|sausages?|ribs|meatballs?|"
    r"carnitas|lechon|chorizo|pastrami|corned beef|hot dogs?|kebab|shawarma|shawerma|fish|salmon|tuna|shrimp|prawns?|"
    r"crab|lobster|oysters?|wagyu|goat|suadero|al pastor|barbacoa|birria|octopus|mussels?|clams?|squid|calamari|"
    r"scallops?|anchov(y|ies)|sardines?|cod|halibut|branzino|mackerel|trout|eel|caviar|roe|uni|ceviche|sashimi|seafood|"
    r"chowder|gumbo|foie gras|bone marrow|prosciutto|salami|pepperoni|pancetta|guanciale|carbonara|bolognese|jerky|"
    r"meatloaf|oxtail|tripe|liver|charcuterie|poke)\b",
    re.IGNORECASE,
)


@dataclass
class Constraints:
    no_alcohol: bool = False
    family: bool = False
    halal: bool = False
    vegetarian: bool = False
    price: tuple[int, int] | None = None  # allowed price levels, inclusive
    size_m2: float | None = None
    kitchen: str | None = None
    outdoor: bool | None = None
    understood: list[str] = field(default_factory=list)

    def allows_genre(self, genre: str) -> tuple[bool, str | None]:
        """Whether a category can be proposed at all, and why not (a phrase that follows 'it')."""
        if self.no_alcohol and ALCOHOL_GENRE.search(genre) and not DRY_BY_NATURE.search(genre):
            return False, "serves alcohol"
        if self.family and ADULTS_GENRE.search(genre) and not FAMILY_SAFE.search(genre):
            return False, "is nightlife, not a place for families"
        return True, None

    def allows_item(self, item: str) -> bool:
        """Whether a dish, drink or activity can be part of the offer."""
        forbidden = (
            self.no_alcohol and ALCOHOL_ITEM.search(item)
            or self.halal and PORK_ITEM.search(item)
            or self.vegetarian and MEAT_ITEM.search(item)
        )
        return not forbidden

    def price_level(self, level: int | None) -> int | None:
        if level is None or not self.price:
            return level
        low, high = self.price
        return max(low, min(high, level))

    def as_evidence(self) -> dict | None:
        """What the agent must respect, spelled out."""
        if not self.understood:
            return None
        rules = {"understood_from_owner_notes": self.understood}
        if self.no_alcohol:
            rules["no_alcohol"] = "never propose a category whose business is alcohol (bars, pubs, breweries, wine) or alcoholic items"
        if self.family:
            rules["family_friendly"] = "never propose nightlife or adults-only categories; design for families"
        if self.halal:
            rules["halal"] = "no pork and no alcohol in the offer"
        if self.vegetarian:
            rules["vegetarian"] = "the offer is meat-free"
        if self.price:
            rules["price_levels_allowed"] = list(range(self.price[0], self.price[1] + 1))
        return rules


def parse(notes: str) -> Constraints:
    text = notes or ""
    found = Constraints()
    if HALAL.search(text):
        found.halal = True
        found.no_alcohol = True
        found.understood.append("halal: no pork or alcohol")
    elif NO_ALCOHOL.search(text):
        found.no_alcohol = True
        found.understood.append("no alcohol")
    if FAMILY.search(text):
        found.family = True
        found.understood.append("family friendly")
    if VEGETARIAN.search(text):
        found.vegetarian = True
        found.understood.append("vegetarian offer")
    if CHEAP.search(text):
        found.price = (1, 2)
        found.understood.append("budget prices ($–$$)")
    elif MID.search(text):
        found.price = (2, 2)
        found.understood.append("mid-range prices ($$)")
    elif UPSCALE.search(text):
        found.price = (3, 4)
        found.understood.append("upscale prices ($$$–$$$$)")
    size = SIZE.search(text)
    if size:
        value = float(size.group(1).replace(",", ""))
        square_feet = "f" in size.group(2).lower()
        area = value / FT2_PER_M2 if square_feet else value
        found.size_m2 = round(area, 1)
        found.understood.append(f"unit of about {round(area)} m²")
    if NO_KITCHEN.search(text):
        found.kitchen = "none"
        found.understood.append("no kitchen")
    elif LIGHT_KITCHEN.search(text):
        found.kitchen = "light"
        found.understood.append("light prep only, no extraction")
    elif FULL_KITCHEN.search(text):
        found.kitchen = "full"
        found.understood.append("full kitchen")
    if NO_OUTDOOR.search(text):
        found.outdoor = False
        found.understood.append("no outdoor space")
    elif OUTDOOR.search(text):
        found.outdoor = True
        found.understood.append("outdoor space")
    return found


def allows(constraints: Constraints, genre: str) -> bool:
    return constraints.allows_genre(scoring.genre_title(genre))[0]
