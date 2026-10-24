"""The owner's free-text notes read as hard constraints, so both the agent and the evidence rules respect them.

Only plain, common instructions are recognized (alcohol, family friendly, halal, vegetarian, price range, unit size,
kitchen, extraction hood and outdoor space); anything else stays a note the agent reads. What was understood is listed
back to the user. The unit the owner describes in the form counts too (adopt_unit): a light kitchen or none means no
extraction hood, so nothing on the menu may need one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import scoring, space

FT2_PER_M2 = 10.7639

NO_ALCOHOL = re.compile(
    r"\b(no|without|not? an?|non[- ]?|zero)[- ]?(alcohol|booze|liquor|drinks? licen[cs]e|alcohol licen[cs]e|"
    r"licen[cs]e|alcoholic|bar)\b|\balcohol[- ]free\b|\bdry (venue|concept|shop)\b|\bsober\b|\bhalal\b",
    re.IGNORECASE,
)
HALAL = re.compile(r"\bhalal\b|\bno pork\b|\bpork[- ]free\b", re.IGNORECASE)
FAMILY = re.compile(r"\b(family|families|kids?|children|child[- ]friendly|all ages)\b", re.IGNORECASE)
VEGETARIAN = re.compile(r"\b(vegetarian|vegan|plant[- ]based|meat[- ]free)\b", re.IGNORECASE)
CHEAP = re.compile(
    r"\b(cheap(er|ly)?|budget([- ]friendly)?|on a budget|affordabl[ey]|inexpensive|low[- ]?(cost|budget)|low[- ]priced|"
    r"low(er)? prices?( points?)?|keep(ing)? prices? low|prices? (kept )?low|(good |great )?value (for money|menu|prices?)|"
    r"bargains?|economical|wallet[- ]friendly|pocket[- ]friendly|not (too |very )?(expensive|pricey)|student prices|"
    r"price[- ]conscious)\b",
    re.IGNORECASE,
)
# "Not cheap", "no budget limit": a price word the notes negate asks for nothing.
NEGATED = re.compile(r"\b(not|no|never|nothing|isn'?t|aren'?t|won'?t|don'?t)\s+((a|an|too|very|so|that|really)\s+)?$",
                     re.IGNORECASE)
MID = re.compile(r"\b(mid[- ]?range|mid[- ]?price[ds]?|moderate(ly priced)?|mid[- ]market)\b", re.IGNORECASE)
UPSCALE = re.compile(r"\b(upscale|high[- ]end|premium|luxury|fine[- ]dining)\b", re.IGNORECASE)
# What a concept must not call itself when the owner set a price band: a budget place is never upscale, an upscale
# place never cheap, and a mid-range place neither.
CHEAP_SAID = re.compile(r"\b(cheap(er|est)?|budget|bargains?|inexpensive|low[- ]priced|discount(ed)?)\b", re.IGNORECASE)
PRICE_BANDS = {
    "budget": "never describe it, its name or its offer as upscale, premium, luxury, high-end or fine dining",
    "mid-range": "never describe it as upscale, premium or luxury, nor as cheap, budget or a bargain",
    "upscale": "never describe it, its name or its offer as cheap, budget, a bargain or discounted",
}
SIZE = re.compile(
    r"(\d{1,3}(?:,\d{3})+|\d{2,5}(?:\.\d+)?)\s*(m²|m2|sqm|sq\.? ?m\b|square met(?:er|re)s?|ft²|ft2|sq\.? ?ft|square f(?:ee|oo)t)",
    re.IGNORECASE,
)
NO_KITCHEN = re.compile(r"\bno (kitchen|cooking|stove)\b", re.IGNORECASE)
LIGHT_KITCHEN = re.compile(r"\b(no (hood|extraction|vent(ilation)?)|light[- ](kitchen|prep)|prep only)\b", re.IGNORECASE)
# The unit cannot vent cooking fumes, however its kitchen is described.
NO_HOOD = re.compile(
    r"\b(no|without( an?)?|lacks?( an?)?|not? allowed( an?)?) (range |kitchen |extraction |exhaust )?(hood|extraction|"
    r"extractor|exhaust|vent(ilation|ing)?|ducting|flue)\b|\bventless\b|\bhood[- ]?less\b",
    re.IGNORECASE,
)
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
    r"craft beer|on tap|drinks list|mulled wine|booze|liquor|(?<!espresso )(?<!wheatgrass )(?<!ginger )shots?)\b",
    re.IGNORECASE,
)
PORK_ITEM = re.compile(r"\b(pork|bacon|ham|prosciutto|chorizo|pancetta|lechon|carnitas|salami|pepperoni|sausages?|bratwurst|brats|hot dogs?|currywurst|ribs)\b", re.IGNORECASE)
MEAT_ITEM = re.compile(
    r"\b(beef|steak|brisket|burgers?|chicken|wings|pork|bacon|ham|lamb|veal|duck|turkey|sausages?|ribs|meatballs?|"
    r"carnitas|lechon|chorizo|pastrami|corned beef|hot dogs?|kebab|shawarma|shawerma|fish|salmon|tuna|shrimp|prawns?|"
    r"crab|lobster|oysters?|wagyu|goat|suadero|al pastor|barbacoa|birria|octopus|mussels?|clams?|squid|calamari|"
    r"scallops?|anchov(y|ies)|sardines?|cod|halibut|branzino|mackerel|trout|eel|caviar|roe|uni|ceviche|sashimi|seafood|"
    r"chowder|gumbo|foie gras|bone marrow|prosciutto|salami|pepperoni|pancetta|guanciale|carbonara|bolognese|jerky|"
    r"meatloaf|oxtail|tripe|liver|charcuterie|poke|kofta|kebda|mombar|hawawshi|tawook)\b",
    re.IGNORECASE,
)
# Categories whose business is meat or fish: a vegetarian owner cannot open them.
MEAT_GENRE = re.compile(
    r"\b(seafood|fish|oysters?|crab|lobster|poke|steak ?house|steak|barbecue|bbq|smokehouse|\w*burgers?|chicken|wings|"
    r"kebab|shawarma|gyros?|butcher|rotisserie|charcuterie)\b",
    re.IGNORECASE,
)
MEAT_FREE_GENRE = re.compile(r"\b(vegan|vegetarian|plant[- ]based|veggie)\b", re.IGNORECASE)
# Words that name meat but not here: goat's cheese, a cauliflower 'steak', vegan 'chicken'.
NOT_MEAT = re.compile(
    r"\bgoat(?:'s)?\s+(?:cheese|milk|curd|yogh?urt|labneh|feta|butter)\b|"
    r"\b(?:vegan|veggie|vegetarian|plant[- ]based|meatless|meat[- ]free|tofu|tempeh|seitan|jackfruit|cauliflower|"
    r"mushroom|eggplant|aubergine|beet|bean|lentil|chickpea|beyond|impossible)\s+(?:burgers?|wings|nuggets?|steaks?|"
    r"chicken|bacon|sausages?|meatballs?|kebabs?|shawarma|tacos?|chorizo|jerky|ribs|bolognese|carbonara|tuna|calamari|"
    r"ceviche|poke)\b",
    re.IGNORECASE,
)
# What an item says it is made without: 'brisket-free', 'no anchovies', 'without bacon'.
WITHOUT_ITEM = re.compile(r"\b[\w']+-free\b|\b(?:no|without)[\s-]+[\w']+", re.IGNORECASE)
# Dashes and spaces a model may type for plain ones: 'wood‑fired' with a non-breaking hyphen is 'wood-fired'.
ODD_DASHES = re.compile("[\u2010-\u2015\u2212]")
ODD_SPACES = re.compile("[\u00a0\u2007\u202f]")

# What an extraction hood is for, by the equipment that needs it; checked in this order, so a stir-fry is the wok's and
# a pan-fried dumpling the flat-top's, not the fryer's.
HOOD_EQUIPMENT = (
    ("a wok burner", re.compile(
        r"\b(woks?|stir[- ]?fr(y|ies|ied)|fried rice|pad thai|lo mein|chow mein|kung pao)\b", re.IGNORECASE)),
    ("a pizza oven", re.compile(
        r"\b(pizzas?|pizzettas?|pizzette|calzones?|stromboli|wood[- ]?fired|brick[- ]?oven|coal[- ]?fired)\b",
        re.IGNORECASE)),
    ("a grill", re.compile(
        r"\b(grill(ed|ing|s)?|char[- ]?grill(ed)?|flame[- ]?grilled|charred|charcoal|barbecue[ds]?|barbeque|bbq|kebabs?|"
        r"kababs?|kebaps?|kofta|kofte|kufta|shish|tawook|taouk|shashlik|souvlaki|yakitori|robata|satay|suya|asado|"
        r"churrasco|rotisserie|shawarmas?|shawermas?|doner|döner|gyros?|tandoori|tandoor|seekh|steaks?|steakhouse|"
        r"rib[- ]?eyes?|sirloin|t-bone|porterhouse|tomahawk|filet mignon|ribs|brisket|wagyu|smoked meats?|smokehouse|"
        r"blackened|broiled)\b", re.IGNORECASE)),
    ("a griddle or flat-top", re.compile(
        r"\b(griddle[ds]?|flat[- ]?tops?|plancha|teppan(yaki)?|\w*burgers?|sliders?|cheesesteaks?|philly|pancakes?|"
        r"hotcakes?|french toast|omelet(te)?s?|hash|pan[- ]?(fried|seared)|seared|saut[eé](ed)?|gyoza|potstickers?|"
        r"quesadillas?|okonomiyaki|kebda)\b", re.IGNORECASE)),
    ("a deep fryer", re.compile(
        r"\b(deep[- ]?fr(y|ied|ies)|fr(y|ies|ied)|fryers?|fritters?|fritto|frites|tempura|katsu|tonkatsu|karaage|"
        r"schnitzels?|croquet(te|a)s?|arancini|pakoras?|bhajis?|samosas?|(?<!fresh )spring rolls?|egg rolls?|falafel|"
        r"ta'?a?m[ei]ya|do(ugh)?nuts?|churros?|beignets?|zeppole|loukoumades|zalabia|luqaimat|funnel cakes?|"
        r"hush ?puppies|corn ?dogs?|onion rings?|mozzarella sticks?|nuggets?|(chicken )?tenders|wings|tater tots|"
        r"hash ?browns?|chicharr[oó]n(es)?|tostones|crispy|mombar|fish (and|&|n) chips)\b", re.IGNORECASE)),
)
# With no kitchen at all, anything cooked on site: baked, roasted, toasted, steamed, boiled or simmered.
COOKED_ITEM = re.compile(
    r"\b(bak(e|ed|es|ing)|roast(ed|s|ing)?|toast(ed|ie|ies|s)?|panini|paninis|steam(ed)?|braise[ds]?|stew(s|ed)?|"
    r"simmer(ed)?|poach(ed)?|boil(ed)?|cooked|soups?|chowders?|broths?|ramen|pho|noodles?|pasta|spaghetti|lasagn[ae]|"
    r"risotto|curr(y|ies)|tagines?|koshar[iy]|ful|foul|fava|eggs?|frittatas?|shakshuka|quiches?|waffles?|crepes?|"
    r"dumplings?|bao|dim sum|tacos?|burritos?|enchiladas?|tamales?|empanadas?|gratin|mac(aroni)? (and|&|n) cheese|"
    r"hot dogs?|hot ?pot)\b",
    re.IGNORECASE,
)


def plain_text(text: str) -> str:
    """Text with its dashes and spaces made plain, so the rules read 'deep‑fried' (a non-breaking hyphen) as 'deep-fried'."""
    return ODD_SPACES.sub(" ", ODD_DASHES.sub("-", text))


def hood_equipment(item: str) -> str | None:
    """The equipment an item needs an extraction hood for ('a deep fryer'), or None when it needs none."""
    item = plain_text(item)
    return next((name for name, pattern in HOOD_EQUIPMENT if pattern.search(item)), None)


def hood_match(item: str) -> re.Match | None:
    """The words of an item that need an extraction hood ('crispy'), or None."""
    item = plain_text(item)
    return next((found for _, pattern in HOOD_EQUIPMENT if (found := pattern.search(item))), None)


def asks(pattern: re.Pattern, text: str) -> bool:
    """Whether the notes say this, and do not negate it ('not cheap')."""
    return any(not NEGATED.search(text[:match.start()]) for match in pattern.finditer(text))


@dataclass
class Constraints:
    no_alcohol: bool = False
    family: bool = False
    halal: bool = False
    vegetarian: bool = False
    price: str | None = None  # the price band the notes ask for: "budget", "mid-range" or "upscale"
    size_m2: float | None = None
    kitchen: str | None = None
    outdoor: bool | None = None
    understood: list[str] = field(default_factory=list)
    no_hood: bool = False  # the notes say the unit has no extraction hood, whatever its kitchen

    @property
    def budget(self) -> bool:
        return self.price == "budget"

    def price_words(self, text: str) -> tuple[str, str] | None:
        """The words that break the owner's price band, and why ('premium', 'calls a budget place upscale'): a budget
        place is never upscale, an upscale place never cheap, and a mid-range place neither."""
        if self.price in ("budget", "mid-range") and (found := UPSCALE.search(text)):
            return found.group(0), f"calls a {self.price} place upscale"
        if self.price in ("upscale", "mid-range") and (found := CHEAP_SAID.search(text)):
            return found.group(0), f"calls {'an upscale' if self.price == 'upscale' else 'a mid-range'} place cheap"
        return None

    @property
    def hood_free(self) -> bool:
        """Nothing may need an extraction hood: the notes say so, or the unit has a light kitchen or none."""
        return self.no_hood or self.kitchen in ("light", "none")

    @property
    def no_cooking(self) -> bool:
        return self.kitchen == "none"

    def adopt_unit(self, size_m2: float | None, kitchen: str | None) -> None:
        """The unit as the owner described it in the form counts as a rule too: its size, and the stricter kitchen of
        the form's and the notes'."""
        if size_m2:
            self.size_m2 = size_m2
        if kitchen in space.KITCHENS and (
            self.kitchen not in space.KITCHENS or space.KITCHENS.index(kitchen) < space.KITCHENS.index(self.kitchen)
        ):
            self.kitchen = kitchen

    def allows_genre(self, genre: str) -> tuple[bool, str | None]:
        """Whether a category can be proposed at all, and why not (a phrase that follows 'it')."""
        if self.no_alcohol and ALCOHOL_GENRE.search(genre) and not DRY_BY_NATURE.search(genre):
            return False, "serves alcohol"
        if self.family and ADULTS_GENRE.search(genre) and not FAMILY_SAFE.search(genre):
            return False, "is nightlife, not a place for families"
        if self.vegetarian and MEAT_GENRE.search(genre) and not MEAT_FREE_GENRE.search(genre):
            return False, "serves meat or fish"
        return True, None

    def item_problem(self, item: str) -> str | None:
        """Why a dish, drink or activity breaks the owner's rules, as a phrase that follows 'it'; None when it does not."""
        clash = self.item_clash(item)
        return clash[1] if clash else None

    def item_clash(self, item: str) -> tuple[str, str] | None:
        """The words of a dish, drink or text that break the owner's rules, and why ('fried', 'needs a deep fryer …').
        What an item says it is made without ('brisket-free', 'no-bake') is not held against it, except alcohol: an
        'alcohol-free' wine is still wine. A price band counts too: 'premium' on a budget."""
        item = plain_text(item)
        if self.no_alcohol and (found := ALCOHOL_ITEM.search(item)):
            return found.group(0), "is alcohol"
        if priced := self.price_words(item):
            return priced
        said = WITHOUT_ITEM.sub(" ", item)
        meatless = NOT_MEAT.sub(" ", said)
        if self.halal and (found := PORK_ITEM.search(meatless)):
            return found.group(0), "has pork"
        if self.vegetarian and (found := MEAT_ITEM.search(meatless)):
            return found.group(0), "has meat or fish"
        if self.no_cooking and (found := COOKED_ITEM.search(said) or hood_match(said)):
            return found.group(0), "needs cooking, and the unit has no kitchen"
        if self.hood_free and (found := hood_match(said)):
            return found.group(0), f"needs {hood_equipment(said)} under an extraction hood"
        return None

    def allows_item(self, item: str) -> bool:
        """Whether a dish, drink or activity can be part of the offer."""
        return self.item_problem(item) is None

    def as_evidence(self) -> dict | None:
        """What the agent must respect, spelled out."""
        if not self.understood and not self.hood_free:
            return None
        rules: dict = {"understood_from_owner_notes": self.understood} if self.understood else {}
        if self.no_alcohol:
            rules["no_alcohol"] = "never propose a category whose business is alcohol (bars, pubs, breweries, wine) or alcoholic items"
        if self.family:
            rules["family_friendly"] = "never propose nightlife or adults-only categories; design for families"
        if self.halal:
            rules["halal"] = "no pork and no alcohol in the offer"
        if self.vegetarian:
            rules["vegetarian"] = "no meat or fish in any item, and never a category whose business is meat or fish"
        if self.price:
            rules["price"] = f"{self.price}: {PRICE_BANDS[self.price]}; state no price level or amount"
        if self.no_cooking:
            rules["no_kitchen"] = "nothing is cooked on site: drinks, cold food and food bought in ready to serve"
        elif self.hood_free:
            rules["no_hood"] = (
                "no item that needs an extraction hood: nothing deep-fried, griddled, grilled, charcoal-cooked, wok-fried "
                "or from a pizza oven (no fries, crispy potatoes, tempura, katsu, karaage, falafel, donuts, churros, "
                "burgers, kebabs, steaks or pizza); food is baked in a ventless oven or assembled cold"
            )
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
    if asks(CHEAP, text):
        found.price = "budget"
    elif asks(MID, text):
        found.price = "mid-range"
    elif asks(UPSCALE, text):
        found.price = "upscale"
    if found.price:
        found.understood.append(f"{found.price} prices")
    size = SIZE.search(text)
    if size:
        value = float(size.group(1).replace(",", ""))
        square_feet = "f" in size.group(2).lower()
        area = value / FT2_PER_M2 if square_feet else value
        found.size_m2 = round(area, 1)
        found.understood.append(f"unit of about {round(area)} m²")
    found.no_hood = bool(NO_HOOD.search(text))
    if NO_KITCHEN.search(text):
        found.kitchen = "none"
        found.understood.append("no kitchen")
    elif LIGHT_KITCHEN.search(text) or found.no_hood:
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
