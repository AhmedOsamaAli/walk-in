"""Pure scoring and summarizing logic over Qloo responses (no network calls)."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from functools import lru_cache
from statistics import mean, median

from .geo import distance_m

# Rank given to a genre that is missing from a top-50 ranking.
UNRANKED = 51

GENRE_TYPE = "urn:tag:genre:place"

# Too broad to describe a business concept.
GENERIC_GENRES = {
    "place", "restaurant", "tourist attraction", "hotel", "shopping", "landmark", "event venue",
    "wedding venue", "bar", "park", "lodging", "food", "store", "point of interest", "american",
}

# Strong local interests that are not a storefront business, used as taste cues for the design instead.
TASTE_CUE_GENRES = {
    "museum", "art museum", "history museum", "art gallery", "garden", "library", "theater",
    "performing arts theater", "stadium", "zoo", "aquarium", "church", "mosque", "temple",
    "university", "school", "hospital", "cemetery", "monument", "historical landmark", "beach",
    "concert hall", "opera house", "national park", "state park",
}

# Real place types that cannot fit in a vacant storefront.
NOT_STOREFRONT_GENRES = {
    "shopping mall", "resort hotel", "hotel", "motel", "hostel", "inn", "casino", "amusement park",
    "theme park", "water park", "golf course", "arena", "airport", "train station", "marina",
    "campground", "ski resort", "convention center", "department store", "supermarket", "hypermarket",
    "stadium", "amphitheater", "amphitheatre", "banquet hall",
}

# Offerings so common they say nothing about a concept; used only when nothing more specific exists.
GENERIC_OFFERINGS = {
    "alcohol", "hard liquor", "beer", "wine", "coffee", "food", "drinks", "corporate events", "wedding services",
    "marketplace", "private events", "event space", "catering", "parking", "restroom", "vegetarian options",
    "vegan options", "quick bite", "comfort food", "healthy options", "kids menu", "late-night food", "late night food", "dine-in",
    "takeout", "delivery", "seating", "outdoor seating", "wi fi", "wifi", "bar", "full bar", "restaurant",
    # Activity and attribute tags that describe nearly every bar or restaurant.
    "dining drinking", "social community", "nightlife", "entertainment", "ok to order just drinks",
    "sports recreation", "culture arts", "nature outdoors", "tours", "celebrations", "people watching",
    "coffee culture", "date night", "brunching", "hanging out", "group outings", "meeting friends", "family friendly",
    # What every venue and bar does; a signature must be something specific.
    "live events", "events", "concerts", "live performances", "cocktails", "happy hour", "happy hour drinks",
    "happy hour food",
}

NON_COMMERCIAL_BRAND = re.compile(r"nonprofit|non-profit|political|government|religious|advocacy", re.IGNORECASE)

DESIGN_FAMILIES = {
    "decor": "urn:tag:decor",
    "setting": "urn:tag:setting",
    "ambience": "urn:tag:ambience",
    "menu": "urn:tag:menu_highlight",
    "offerings": "urn:tag:offerings",
    "cuisine": "urn:tag:cuisine",
    "amenities": "urn:tag:amenity",
    "activities": "urn:tag:activity_type",
    "interests": "urn:tag:interests",
}

# Qloo returns raw catalog names and review keywords; keep slurs out of the UI.
OFFENSIVE_PATTERN = re.compile(r"n[i1!]gg(a|ah|as|az|er|ers)\b|f[a@]gg?[o0]ts?\b|r[e3]t[a@]rd|\bredskins?\b", re.IGNORECASE)


def is_safe_name(name: str | None) -> bool:
    return bool(name) and not OFFENSIVE_PATTERN.search(name)


FOCUS_KEYWORDS = {
    "food_drink": (
        "restaurant", "cafe", "café", "coffee", "bar", "brunch", "breakfast", "bakery", "pub", "lounge", "wine",
        "cocktail", "tea", "juice", "dessert", "ice cream", "pizza", "burger", "hamburger", "sandwich", "sushi",
        "ramen", "diner", "deli", "grill", "steak", "steak house", "seafood", "kitchen", "bistro", "brasserie",
        "taco", "tex-mex", "noodle", "food", "dining", "american", "italian", "french", "mexican", "japanese",
        "thai", "chinese", "korean", "indian", "mediterranean", "middle eastern", "lebanese", "egyptian", "greek",
        "spanish", "tapas", "vegan", "vegetarian", "fast food", "takeout", "caterer", "patisserie", "donut",
        "brewery", "barbecue", "bbq", "gastropub", "koshari", "shawarma", "falafel", "kebab", "shisha", "hookah",
    ),
    "retail": (
        "shop", "store", "boutique", "market", "florist", "bookstore", "book store", "clothing", "fashion",
        "accessories", "jewelry", "jewellery", "furniture", "gift", "record", "pharmacy", "grocery", "outlet",
        "shoe", "cosmetics", "electronics", "toy", "pet", "bike", "optician", "hardware", "thrift", "vintage",
    ),
    "leisure": (
        "gym", "fitness", "yoga", "pilates", "studio", "spa", "salon", "barber", "nail", "beauty", "massage",
        "wellness", "personal care", "tattoo", "club", "venue", "cinema", "movie", "bowling", "climbing",
        "karaoke", "comedy", "music", "dance", "arcade", "game", "sports", "lounge", "coworking",
    ),
}
FOCUS_NAMES = {"food_drink": "food and drink", "retail": "retail", "leisure": "leisure and wellness"}


def _matches(genre_name: str, keywords: Iterable[str]) -> bool:
    lowered = genre_name.lower()
    return any(re.search(rf"\b{re.escape(word)}(s|es)?\b", lowered) for word in keywords)


# Shops that sell goods to take home, even when the goods are food or drink.
RETAIL_GOODS = ("liquor", "wine shop", "wine store", "bottle shop", "cheese shop", "butcher", "grocery", "supermarket",
                "convenience store", "spice", "health food store", "farmers market", "deli shop")


def is_food_service(genre_name: str) -> bool:
    """Eat or drink on the spot: a coffee shop or an ice cream shop is food and drink, not retail."""
    return _matches(genre_name, FOCUS_KEYWORDS["food_drink"]) and not _matches(genre_name, RETAIL_GOODS)


def matches_focus(genre_name: str, focus: str) -> bool:
    keywords = FOCUS_KEYWORDS.get(focus)
    if not keywords:
        return True
    if focus == "retail":
        return (_matches(genre_name, keywords) or _matches(genre_name, RETAIL_GOODS)) and not is_food_service(genre_name)
    return _matches(genre_name, keywords)


# Places people go to for an experience (a game, a show, a tour); checked before plain bars.
VENUE_WORDS = ("sports", "music", "karaoke", "comedy", "cinema", "bowling", "arcade", "club", "venue", "brewery",
               "taproom", "theater", "theatre")
BAR_WORDS = ("bar", "lounge", "pub")
WELLNESS_WORDS = ("spa", "salon", "personal care", "barber", "nail", "beauty", "massage", "gym", "fitness", "yoga", "pilates", "wellness", "tattoo")


def _has_word(text: str, words: Iterable[str]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}s?\b", text) for word in words)


def genre_kind(genre: str) -> str:
    lowered = genre.lower()
    if _has_word(lowered, WELLNESS_WORDS):
        return "wellness"
    if _has_word(lowered, VENUE_WORDS):
        return "venue"
    if _has_word(lowered, BAR_WORDS):
        return "bar"
    if matches_focus(genre, "retail"):
        return "retail"
    return "food"


def strict_kind(genre: str) -> str | None:
    """The kind of business a genre names, or None for what is not a storefront business ('Tourist attraction')."""
    lowered = genre.lower()
    if _has_word(lowered, WELLNESS_WORDS):
        return "wellness"
    if _has_word(lowered, VENUE_WORDS + ("concert hall", "theater", "event venue")):
        return "venue"
    if _has_word(lowered, BAR_WORDS):
        return "bar"
    if matches_focus(genre, "retail"):
        return "retail"
    if is_food_service(genre):
        return "food"
    return None


GENRE_SUFFIXES = {"restaurant", "place", "spot", "eatery", "joint"}


def genre_key(name: str) -> str:
    """'Seafood restaurant' and 'Seafood' are one genre; 'Steak house' and 'Steakhouse', 'Café' and 'Cafe' too."""
    return "".join(word for word in topic_text(name).split() if word not in GENRE_SUFFIXES)


def relevance_tier(entity: dict, genre_id: str, genre_name: str) -> int:
    """How truly a place is of a genre: 1 when it is its main genre, 2 when it is the same kind of business (a bar for a
    cocktail bar, a restaurant for seafood), 3 when Qloo only tags it with the genre (a museum with a bar)."""
    # The main genre as Qloo gives it, generic or not ('Bar', 'Tourist attraction'); the first genre tag without one.
    main = (entity.get("properties") or {}).get("primary_genre") or {}
    tag = (main.get("id"), main["name"]) if isinstance(main.get("name"), str) else next(iter(genre_tags(entity)), None)
    if not tag:
        return 3
    tag_id, name = tag
    if tag_id == genre_id or genre_key(name) == genre_key(genre_name):
        return 1
    kind = strict_kind(genre_name)
    return 2 if kind and strict_kind(name) == kind else 3


def relevant(places: list[dict], genre_id: str, genre_name: str) -> list[dict]:
    """Places of the genre in earnest, in their original order: a museum Qloo tags 'Cocktail bar' is left out."""
    return [place for place in places if relevance_tier(place, genre_id, genre_name) <= 2]


def best_examples(places: list[dict], genre_id: str, genre_name: str) -> list[dict]:
    """Places whose main genre it is first, then the same kind of business, each in their original order."""
    tiers = [(relevance_tier(place, genre_id, genre_name), index, place) for index, place in enumerate(places)]
    return [place for _, _, place in sorted(tiers, key=lambda item: item[:2])]


def signature_items(genre: str, dna: dict, limit: int = 3) -> list[str]:
    """What a concept of this genre should be known for: menus for restaurants, offerings for bars and shops."""
    kind = genre_kind(genre)
    if kind == "food":
        items = (dna.get("menu") or []) + (dna.get("offerings") or [])
    elif kind == "venue":
        # What people go there to do comes first: game day viewing, concerts, brewery tours.
        items = (dna.get("activities") or []) + (dna.get("offerings") or []) + (dna.get("menu") or [])
    elif kind == "bar":
        items = (dna.get("offerings") or []) + (dna.get("activities") or []) + (dna.get("menu") or [])
    else:
        items = (dna.get("offerings") or []) + (dna.get("amenities") or []) + (dna.get("activities") or [])
    unique: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item.lower() not in seen:
            seen.add(item.lower())
            unique.append(item)
    specific = [item for item in unique if item.lower() not in GENERIC_OFFERINGS]
    generic = [item for item in unique if item.lower() in GENERIC_OFFERINGS]
    # "Steak" adds nothing next to "Steak frites"; only specific items can cover others.
    covering = [_words(item) for item in specific]
    specific = [item for item in specific if not any(_words(item) < other for other in covering)]
    generic = [item for item in generic if not any(_words(item) < other for other in covering)]
    # Generic items only pad a short list; they never trail specific ones.
    if len(specific) >= min(limit, 3):
        return specific[:limit]
    return (specific + generic)[: min(limit, 3)]


def _words(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", text.lower()))


def genre_title(name: str) -> str:
    """'Fine dining restaurant' -> 'Fine Dining'; keeps 'Tex-Mex', 'New American' and 'Bar + Grill' intact."""
    base = re.sub(r"\s+restaurant$", "", name.strip(), flags=re.IGNORECASE) or name.strip()
    keep = {"and", "or", "of", "the", "+", "&"}
    words = [w if w.lower() in keep or "-" in w or any(c.isupper() for c in w[1:]) else w[:1].upper() + w[1:] for w in base.split()]
    return " ".join(words)


def entities(data: dict) -> list[dict]:
    results = data.get("results")
    return (results.get("entities") or []) if isinstance(results, dict) else []


def tags(data: dict) -> list[dict]:
    results = data.get("results")
    return (results.get("tags") or []) if isinstance(results, dict) else []


def item_id(item: dict) -> str | None:
    return item.get("entity_id") or item.get("tag_id") or item.get("id")


def tag_id(tag: dict) -> str | None:
    return tag.get("id") or tag.get("tag_id")


def genre_tags(entity: dict) -> list[tuple[str, str]]:
    return [
        (tag_id(t), t["name"])
        for t in entity.get("tags") or []
        if t.get("type") == GENRE_TYPE and t.get("name") and tag_id(t)
    ]


def primary_genre_tag(entity: dict) -> tuple[str, str] | None:
    """Qloo's main category for a place as (tag id, name); its tag list is unordered ('Izakaya' may come first)."""
    tag = (entity.get("properties") or {}).get("primary_genre") or {}
    name, tag_id = tag.get("name"), tag.get("id")
    return (tag_id, name) if isinstance(name, str) and tag_id and is_business_genre(name) else None


def primary_genre(entity: dict) -> str | None:
    tag = primary_genre_tag(entity)
    return tag[1] if tag else None


def is_business_genre(name: str) -> bool:
    lowered = name.strip().lower()
    return lowered not in GENERIC_GENRES and lowered not in TASTE_CUE_GENRES and lowered not in NOT_STOREFRONT_GENRES


def is_taste_cue(name: str) -> bool:
    return name.strip().lower() in TASTE_CUE_GENRES


def is_storefront_place(entity: dict) -> bool:
    """False for hotels, malls and other places whose design cannot inspire a small storefront."""
    return not any(name.lower() in NOT_STOREFRONT_GENRES for _, name in genre_tags(entity))


def is_open(entity: dict) -> bool:
    """False for a place Qloo marks as closed: it is neither a competitor nor an example any more."""
    return not (entity.get("properties") or {}).get("is_closed")


def is_commercial_brand(entity: dict) -> bool:
    for tag in entity.get("tags") or []:
        if tag.get("type") in ("urn:tag:brand_type:qloo", "urn:tag:business_model:qloo") and NON_COMMERCIAL_BRAND.search(tag.get("name") or ""):
            return False
    return True


def place_location(entity: dict) -> tuple[float, float] | None:
    location = entity.get("location") or {}
    lat, lon = location.get("lat"), location.get("lon")
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


# A place with this many TripAdvisor reviews has years of history (the median place in our samples has about 50).
ESTABLISHED_REVIEWS = 250


def standing(entity: dict) -> dict | None:
    """Why a place counts as an established favorite: a Michelin Guide listing or a long review history.

    Qloo has no opening dates, so nothing is ever called new; places without this evidence are simply not marked.
    """
    external = entity.get("external") or {}
    michelin = next(iter(external.get("michelin") or []), None)
    tripadvisor = next(iter(external.get("tripadvisor") or []), None) or {}
    reviews = tripadvisor.get("rating_count")
    reviews = int(reviews) if isinstance(reviews, int | float) else None
    if not michelin and (reviews or 0) < ESTABLISHED_REVIEWS:
        return None
    result: dict = {"reviews": reviews}
    if michelin:
        stars = michelin.get("stars")
        result["michelin"] = f"{int(stars)} star{'s' if int(stars) > 1 else ''}" if stars else "listed"
    return result


def _themes(*pairs: tuple[str, str]) -> tuple[tuple[str, re.Pattern], ...]:
    return tuple((label, re.compile(pattern)) for label, pattern in pairs)


# Review keywords are topics reviews mention, counted but without polarity: "parking" may be easy or a nightmare. Each
# keyword is read as one kind: a complaint theme, an experience theme, a menu item, or nothing (a neutral topic such as
# "prices"). Themes gather what reviews say in different words ("long lines", "wait time", "on line"), so a summary never
# lists the same point twice. Patterns run on topic_text(): lowercase, accents and punctuation folded.

# Dishes, dances, design terms and names that contain a complaint word.
NOT_COMPLAINT_PATTERN = re.compile(
    r"\bdirty (martinis?|chai|rice|fries|soda|horchata|circus|dancing|south|dozen|shirley)\b|\bwait ?staff\b|\bbad bunny\b|"
    r"\bline ?cooks?\b|\bpoor mans?\b|\bloud(er)? than words\b|\bline danc\w*|\bsight ?lines?\b|\bclean lines?\b|"
    r"\b(line|queue) (skipp|jump)\w*|\bskip (the )?(line|queue)s?\b|\bfixing bad\b|\bready to wait\b|\bworth (the )?wait\w*|"
    r"\bburnt (ends?|butter|sugar|honey|caramel|orange|basque|cheesecake|toffee|onions?)\b|\bsalty (honey|dog|caramel|pretzels?|lassi)\b|"
    r"\bbroken (rice|yolks?|eggs?|noodles)\b|\bslow (cooked|cooker|roasted|braised|smoked|food|jams?|danc\w*|drip|pour|burn|"
    r"fermented|rise)\b|\bgreasy spoon\b|\bpacked with\b|\b(subway|train|bus|metro|tram|ferry|phone|front|punch|straight) lines?\b|"
    r"\bnoise (cancel\w*|machines?)\b|\bwhite noise\b|\b(good|great|positive|friendly|nice|fun) attitude\b|\bgummy (worms?|bears?)\b"
)
# A positive word turns a complaint word around: "short wait time", "no long lines", "not crowded", "free parking".
NEGATED_COMPLAINT_PATTERN = re.compile(
    r"\b(not|never|hardly|no|without|short|shorter|quick|quicker|fast|faster|minimal|zero|little|reasonable)"
    r"( too| very| long| much| moving| a)? (waits?|waiting|wait ?times?|lines?|queues?|crowds?|crowded|busy|noise|noisy|loud|"
    r"rude|dirty|smells?|smelly|expensive|overpriced|pricey)\b|"
    r"\b(free|valet|easy|ample|plenty of|lots of|street|validated|convenient|cheap|on ?site|private|covered|underground|nearby) "
    r"parking\b|\bparking (lots?|garages?|available|validation)\b|\bfast ?moving lines?\b|\blines? (moves?|moved|moving) (fast|quickly)\b"
)
COMPLAINT_THEMES = _themes(
    ("Long waits and lines", r"\b(waits?|waiting|wait ?times?|wait ?list|lines?|line up|queues?|queuing|queueing)\b"),
    ("Crowding", r"\b(crowded|overcrowded|crowds|packed|cramped|claustrophobic|oversold|overselling|tight (seating|space|quarters)|"
                 r"(no|limited|not enough|lack of) (indoor |outdoor )?(seats|seating))\b"),
    ("Noise", r"\b(loud|louder|loudness|noise|noises|noisy|deafening)\b"),
    ("Rude staff", r"\b(rude|rudeness|rudely|unfriendly|unhelpful|unprofessional|disrespectful|arrogant|condescending|impolite|"
                   r"attitude)\b"),
    ("Slow service", r"\b(slow|slowly|slowness|delays?|delayed|understaffed|short ?staffed|"
                     r"(bad|poor|terrible|horrible|awful|worst|inattentive) service)\b"),
    ("Prices", r"\b(expensive|overpriced|over priced|pricey|rip ?offs?|price gouging|(high|steep) prices)\b"),
    ("Hygiene", r"\b(dirty|dirtiness|filthy|hygiene|unhygienic|unclean|smells?|smelly|stinks?|stinky|odou?rs?|flies|roach(es)?|"
                r"cockroach(es)?|rats|mice|bugs|insects?|aphids?|worms?)\b"),
    ("Food quality", r"\b(bland|stale|greasy|oily|burnt|burned|soggy|tasteless|flavou?rless|mediocre|overcooked|undercooked|"
                     r"inedible|cold food|food (was |is )?cold|poisoning|(bad|poor|terrible|horrible|awful|worst) (food|quality|taste))\b|"
                     r"^(too |very |overly )?salty( (food|dish|dishes|meals?|sauce|broth))?$"),
    ("Small portions", r"\b(small|smaller|tiny|skimpy|stingy|meager|meagre) portions?\b|\bportions? (are |were |too )?small\b"),
    ("Parking", r"\bparking\b"),
    ("Broken equipment", r"\b(broken|out of order|not working)\b"),
    ("Touts and tourist traps", r"\b(touts?|touting|hustlers?|scams?|scammers?|scammy|tourist traps?)\b"),
    ("Uncomfortable seats", r"\buncomfortable (seats?|seating|chairs?|benches|stools|booths?)\b|\bhard (seats|chairs|benches)\b"),
)
# Experience themes that read as a complaint turned around; they come before policies, since "no wait" is not a rule.
TURNED_THEMES = _themes(
    ("Short waits", r"\b(quick|quickly|prompt|immediate|immediately|instant|fast|easy) seat(ing|ed)\b|\bseated (quickly|immediately)\b|"
                    r"\b(no|short|shorter|quick|quicker|fast|faster|minimal|little|zero|reasonable) (long )?(waits?|waiting|wait ?times?|"
                    r"lines?|queues?)\b|\bfast ?moving lines?\b|\blines? (moves?|moving) (fast|quickly)\b|\b(quick|fast|speedy|prompt) service\b"),
    ("Spacious", r"\bspacious\w*|\b(plenty of|ample|lots of|enough) (seating|seats|space|room|tables)\b|\b(not|never|un) ?crowded\b|"
                 r"\bno crowds?\b|\broomy\b"),
    ("Quiet", r"\b(quiet\w*|peaceful\w*|tranquil\w*|serene|serenity|calm\w*)\b|\b(not|never) (noisy|loud)\b|\bno noise\b"),
)
# "no reservations", "no laptops allowed", "bring your own wine": house rules, neither praise nor complaint.
POLICY_PATTERN = re.compile(r"^(no|not|never|without)\b|\bbring your own\b|\bbyob?\b")
# Phrases that carry an experience word but are something else: hot dogs, cat food, the view of a stage.
NOT_EXPERIENCE_PATTERN = re.compile(
    r"\bview of (the )?stage\b|\bkitchen views?\b|\bpoint of view\b|\bclean (lines?|cut|food|eating|ingredients|label|beauty)\b|"
    r"\b(hot|corn|chili|chilli|cheese|bacon|chicago|coney) dogs?\b|\bcat (food|supplies|toys|litter|treats)\b|\bdated decor\b|"
    r"\bdecor items\b|\blate (entry|orders?|fees?|check ?outs?)\b|\b(olive|square) gardens?\b|\bmusic (schools?|stores?|lessons?)\b|"
    r"\bpiano (stores?|lessons?)\b|\bdog (training|trainers?|grooming)\b|\bbasketball shoes\b|\bdisco (fries|tots)\b|"
    r"\bchess pies?\b|\bmusic memorabilia\b|\bsports (equipment|stores?|shops?|wear|clothing|apparel|nutrition)\b"
)
STAFF_ROLES = (
    r"(staff|wait ?staff|service|team|crew|people|employees?|workers?|bartenders?|baristas?|servers?|waiters?|waitress(es)?|owners?|"
    r"hosts?|hostess(es)?|chefs?|cooks?|managers?|management|docents?|guides?|instructors?|teachers?|stylists?|barbers?|artists?|"
    r"sales ?(reps?|associates?|people|staff)|salesperson|associates|reps|cashiers?|bouncers?|door ?m[ae]n|receptionists?|concierge|"
    r"front desk|nurses?|doctors?|smile)"
)
STAFF_PRAISE = (
    r"(friendly|kind|welcoming|polite|helpful|attentive|accommodating|courteous|respectful|personable|knowledgeable|informative|"
    r"professional|efficient|caring|sweet|warm|lovely|amazing|great|nice|good|excellent|wonderful|awesome|fantastic|outstanding|"
    r"exceptional|pleasant|patient|funny|fun|cool|chill|happy|smiley|smiling|cheerful|generous|talented|skilled|qualified|competent|"
    r"cooperative|responsive|prompt|quick|fast|engaging|passionate|sincere|hospitable|gracious|charming|energetic|thoughtful|"
    r"considerate|honest|best|super)"
)
ATMOSPHERE_ADJECTIVES = (
    r"(cozy|cosy|intimate|beautiful|gorgeous|stunning|charming|cute|elegant|classy|chic|stylish|relaxing|relaxed|chill|lively|fun|"
    r"cool|homey|homely|warm|inviting|comfortable|comfy|quirky|unique|upscale|luxurious|luxury|fancy|swanky|trendy|hip|rustic|"
    r"retro|vintage|aesthetic|welcoming|friendly|vibrant|energetic|eclectic|funky|modern|minimalist|sophisticated|casual|"
    r"laid ?back|whimsical|magical|busy|buzzing|festive)"
)
PLACE_NOUNS = (
    r"(atmosphere|vibes?|ambiance|ambience|place|spot|space|setting|venue|bar|cafe|room|rooms|interior|interiors|decor|environment|"
    r"feel|feeling|experience|restaurant|lounge|pub|shop|store|hotel|property|building|indoors|seating|seats|chairs|couches|sofas|"
    r"booths|area|corner|studio|layout|setup|location)"
)
EXPERIENCE_THEMES = _themes(
    ("Vegan options", r"\b(vegan\w*|vegetarian\w*|veggie options|plant ?based|dairy ?free|meat ?free|meatless)\b"),
    ("Gluten-free options", r"\b(gluten ?free|celiac|coeliac)\b"),
    ("Healthy options", r"\b(healthy|healthier|organic|wholesome|nutritious|low ?carb|keto|paleo|seed oils?)\b|^health$"),
    ("Happy hour", r"\bhappy hours?\b|\bdrinks? specials\b"),
    ("Food truck", r"\b(food|taco|coffee|pizza|bbq|dessert|ice cream) trucks?\b"),
    ("Food hall", r"\bfood (courts?|halls?|stalls?|vendors?)\b|^vendors$|\bmarket stalls\b"),
    ("Late night", r"\blate ?nights?\b|\bopen late\b|\blate hours\b|\b24 ?(hours|7)\b|\bafter hours\b"),
    ("Rooftop and views", r"\broof ?tops?\b|^roof( deck| terrace)?$|\bbalcon(y|ies)\b|\bviews?\b|\bskyline\b|\bsunsets?\b|\bnile\b|"
                          r"\bwater ?front\b|\boverlook\w*|\bpanoram\w*"),
    ("Outdoor seating", r"\boutdoors?\b|\boutside (seating|area|tables?|space|bar|dining)\b|\bal ?fresco\b|\bpatios?\b|\bback ?yards?\b|"
                        r"\bterraces?\b|\bsidewalk\b|\bcourtyards?\b|\bverandas?\b|\bporch\b|\bpicnic tables?\b|\bfire ?pits?\b|"
                        r"\bbeer gardens?\b|\bgardens?( seating| area| patio| space)?$|\bgreen space\b|\bcabanas?\b|\bstreet seating\b"),
    ("Bar seating", r"\b(bar|counter|kitchen counter|chefs? counter|bar ?top|high ?top) (seating|seats|stools)\b|\bseats? at the (bar|counter)\b|"
                    r"\bbar ?stools\b|\bchefs? counter\b|^counter$"),
    ("Drinks list", r"\b(beers?|wines?|whiske?ys?|bourbons?|scotch|mezcals?|tequilas?|sakes?|gins?|rums?|vodkas?|cocktails?|drinks?|"
                    r"teas?|coffees?|beans?|spirits|liquors?|ciders?) (selection|list|menu|program|variety|options|choices|collection|"
                    r"offerings?|range)\b|\bselection of (beers?|wines?|whiske?ys?|cocktails|teas?|spirits)\b"),
    ("Dive bar", r"\bdive bars?\b|^dive$|\bdivey\b"),
    ("Speakeasy", r"\bspeak ?easy\w*|\bspeakeasies\b|\bhidden (bar|entrance|door)\b|\bsecret (door|entrance|bar|room|passage)\b|"
                  r"\bphone booth\b|\bprohibition\b"),
    ("Neighborhood bar", r"\b(neighbou?rhood|local|locals) (bar|pub|tavern|saloon|watering hole)\b"),
    ("Live music and DJs", r"\b(live music|music\w*|musicians?|bands?|djs?|dj sets?|sound ?systems?|soundsystem|acoustics|sound quality|"
                           r"dance ?floors?|dances?|dancing|dancers?|karaoke|jazz|blues|concerts?|gigs?|live (performances?|entertainment)|"
                           r"piano\w*|pianists?|saxophon\w*|violinists?|guitarists?|singers?|singing|sing ?alongs?|songs?|oud|"
                           r"umm kulthum|oum kalthoum|fairuz|fayrouz|juke ?box(es)?|playlists?|hip hop|techno|disco(theque)?s?|"
                           r"disco (balls?|music|nights?)|honky ?tonk|bluegrass|reggae|raves?|edm|drum circle|"
                           r"(reggaeton|salsa|cumbia|bachata|swing|latin|bollywood|80s|90s|70s) nights?)\b|^(sound|speakers|country)$"),
    ("Shows and comedy", r"\b(comedy|comedians?|stand ?up|improv\w*|drag (shows?|brunch|queens?|bingo|performers?)|burlesque|cabaret|"
                         r"magic shows?|shows?|performances?|plays|stages?|lineups?|poetry (slam|readings?)|open mic\w*|theaters?|"
                         r"theatres?|screenings?|movies?|films?|cinema|circus)\b|^comics$"),
    ("Games and sports", r"\b(pool (tables?|hall)|free pool|billiards?|darts?|trivia|tvs?|televisions?|big screens?|screens|"
                         r"watch(ing)? (sports|games?|football|soccer|basketball|the game|a game|matches|liverpool\w*)|sports|"
                         r"football|soccer|basketball|baseball|hockey|game ?(day|night|room|selection|viewing)|games?|arcades?|"
                         r"pinball\w*|skee ?ball|ping ?pong|table tennis|beer pong|cornhole|bocce\w*|shuffleboard|foosball|bowling|"
                         r"axes?|axe throwing|golf|mini golf|putt putt|pickleball|padel|tennis|bingo|"
                         r"(handball|volleyball|squash|king|padel|pickleball) courts?|courts|soccer fields?|climbing|"
                         r"escape rooms?|go ?karts?|video games?|playstation|xbox|nintendo|jenga|chess|photo ?booths?|tokens|"
                         r"claw machines?|ball pit|mtg|dnd|rpg|tabletop|board games?|lawn games?)\b|\baxe \w+"),
    ("Dog friendly", r"^(dog|dogs|pet|pets|pup|pups|puppy|puppies|doggy|doggie)( friendly| allowed| welcome| park| run| treats| menu|"
                     r" cafe| play area| bowls?| watching)?$|\b(dog|pet) friendly\b|\bdog (park|run|treats|menu|cafe)\b"),
    ("Cats", r"^((friendly|active|rescue|sleepy|stray|resident|shop|bar|distillery|petting) )?(cats?|kitties|kitty|kittens?)$|"
             r"\bcat (adoption|cafe|lounge|room|socialization|decor)\b|\b(with|petting) cats\b"),
    ("Date spot", r"\bdate (spot|night|place|ideas?)\b|\bfirst dates?\b|^date$|\bromantic\w*|\bintimate dates?\b"),
    ("People watching", r"\bpeople ?watching\b"),
    ("Laptop friendly", r"^(free |fast |good )?wi ?fi$|^laptops?$|\blaptop (friendly|area|space|spot|seating)\b|"
                        r"\bwork(ing)? (friendly|space|spot)\b|\bstudy (spot|space|area)\b|\b(power )?outlets\b|\bco ?working\b"),
    ("Generous portions", r"\b(large|larger|big|bigger|huge|generous|good|great|massive|giant|hearty|decent|ample|filling) portions?\b|"
                          r"\bportions? (are |were )?(large|big|huge|generous)\b"),
    ("Good value", r"\baffordab\w+|\binexpensive\b|\bcheap\b|^budget( friendly)?$|\b(good|great|fair|reasonable|decent|best|low|cheap) "
                   r"(value|prices?|pricing)\b|\bvalue for money\b|\breasonably priced\b|\bbargains?\b|\bworth the (money|price)\b"),
    ("Cleanliness", r"\b(cleanliness|clean|spotless|tidy|tidiness|sanitary|hygienic)\b"),
    ("Friendly staff", rf"\b{STAFF_PRAISE}( and {STAFF_PRAISE})? {STAFF_ROLES}\b|\b(helpfulness|hospitality|hospitable|friendliness|"
                       r"kindness|politeness|professionalism|attentiveness|warm welcome|customer care)\b|"
                       r"^(friendly|helpful|polite|kind|welcoming|attentive|patient|professional|informative|knowledgeable|courteous|"
                       r"accommodating|respectful|personable)$"),
    ("Atmosphere", rf"\b{ATMOSPHERE_ADJECTIVES} {PLACE_NOUNS}\b|\b(atmosphere|atmospheric|ambiance|ambience|vibes?|vibey|decor|"
                   r"decorations?|decorated|interior design|lighting|lights|lit|candle ?lit|candlelight|fireplaces?|natural light|"
                   r"skylights?|plant wall|aesthetics?|charm|setting|environment|(beautifully|nicely|well) (furnished|decorated|designed))\b|"
                   r"^(cozy|cosy|intimate|beautiful|gorgeous|stunning|charming|cute|elegant|classy|chic|stylish|relaxing|chill|lively|"
                   r"fun|funky|homey|comfortable|comfy|upscale|luxury|luxurious|fancy|trendy|aesthetic|light|eclectic|vibrant|unique|"
                   r"quirky|whimsical|magical)$"),
)
# Leading words that only praise or qualify, dropped so "great croissants" and "croissants" are one dish.
FILLER_WORDS = frozenset({
    "great", "good", "amazing", "delicious", "excellent", "nice", "best", "tasty", "awesome", "fantastic", "wonderful", "fresh",
    "really", "very", "super", "so", "incredible", "perfect", "yummy", "lovely", "favorite", "favourite", "the", "quality",
    "creative", "craft", "signature", "specialty", "speciality", "unique", "homemade", "housemade", "house", "made", "authentic",
    "local", "legit", "solid", "decent", "classic", "high", "outstanding", "exceptional", "phenomenal",
})
# Too generic to tell anything about a menu; "food" and "dishes" after a cuisine name it instead ("egyptian food").
GENERIC_MENU_TOPICS = frozenset({
    "food", "foods", "cuisine", "dish", "dishes", "drink", "drinks", "beverage", "beverages", "wine", "wines", "water", "booze",
    "alcohol", "liquor", "topping", "toppings",
})
# Words a dish or a drink never ends on: people, places, money, time, events, goods and services. A keyword whose main
# word is one of these is about something else ("cookie size", "pasta making class", "history of ice cream").
NOT_MENU_WORDS = frozenset({
    "price", "pricing", "priced", "cost", "fee", "charge", "tip", "tipping", "gratuity", "cash", "card", "credit", "money",
    "deal", "sale", "discount", "coupon", "value", "payment", "pay", "purchase", "refund", "receipt", "bill", "check",
    "dollar", "commission", "warranty", "shipping", "exchange", "budget", "staff", "team", "crew", "management", "manager",
    "owner", "chef", "cook", "bartender", "barista", "server", "waiter", "waitress", "employee", "worker", "sommelier",
    "host", "hostess", "cashier", "bouncer", "doorman", "doormen", "security", "guard", "concierge", "receptionist",
    "reception", "people", "person", "crowd", "local", "tourist", "kid", "kids", "children", "child", "family", "families",
    "student", "customer", "patron", "guest", "regular", "clientele", "homeless", "friend", "couple", "group", "nurse",
    "doctor", "docent", "instructor", "teacher", "professor", "faculty", "artist", "engineer", "porter", "supervisor",
    "guide", "grandmother", "service", "ordering", "order", "delivery", "takeout", "pickup", "reservation", "booking",
    "checkout", "process", "system", "policy", "rule", "code", "accuracy", "availability", "communication", "experience",
    "experiment", "quality", "consistency", "speed", "help", "support", "question", "answer", "appointment", "registration",
    "membership", "loyalty", "reward", "website", "online", "email", "gmail", "instagram", "phone", "place", "spot",
    "space", "area", "room", "venue", "location", "neighborhood", "neighbourhood", "region", "street", "block", "corner",
    "branch", "building", "floor", "upstairs", "downstairs", "basement", "door", "entrance", "entry", "exit", "elevator",
    "stairs", "bathroom", "restroom", "toilet", "sink", "mirror", "lobby", "hallway", "layout", "size", "setup",
    "renovation", "construction", "garage", "parking", "valet", "access", "subway", "station", "train", "bus",
    "transportation", "transit", "walk", "walking", "walkability", "proximity", "distance", "hotel", "motel", "hostel",
    "school", "college", "university", "campus", "office", "church", "mosque", "temple", "park", "beach", "pool",
    "swimming", "pond", "lake", "island", "tree", "statue", "monument", "bridge", "square", "tower", "landmark", "mall",
    "market", "store", "shop", "boutique", "outlet", "supermarket", "grocery", "groceries", "bodega", "deli", "bakery",
    "cafe", "coffeeshop", "restaurant", "diner", "eatery", "bar", "pub", "lounge", "club", "nightclub", "saloon", "tavern",
    "brewery", "taproom", "winery", "distillery", "gym", "spa", "salon", "studio", "gallery", "museum", "library", "arena",
    "stadium", "apartment", "unit", "suite", "property", "facility", "amenity", "table", "seating", "seat", "chair",
    "couch", "sofa", "booth", "stool", "bench", "bed", "cabin", "window", "ceiling", "wall", "glass", "desk", "dryer",
    "washer", "dishwasher", "refrigerator", "fridge", "night", "morning", "evening", "afternoon", "day", "weekend",
    "weekday", "summer", "winter", "spring", "fall", "autumn", "holiday", "christmas", "halloween", "season", "sunday",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "hour", "time", "lunchtime", "party", "birthday",
    "celebration", "wedding", "event", "gathering", "meeting", "occasion", "anniversary", "graduation", "festival", "class",
    "workshop", "lesson", "camp", "tour", "trip", "visit", "ride", "cruise", "rental", "concept", "idea", "theme", "name",
    "sign", "hope", "faith", "problem", "issue", "solid", "gem", "business", "variety", "selection", "option", "choice",
    "item", "product", "brand", "stuff", "thing", "supply", "inventory", "collection", "range", "presentation",
    "ingredient", "flavor", "flavour", "taste", "portion", "temperature", "level", "volume", "design", "style", "color",
    "colour", "mood", "energy", "spirit", "culture", "history", "heritage", "architecture", "art", "artwork", "mural",
    "graffiti", "exhibit", "exhibition", "painting", "photo", "picture", "photography", "memorabilia", "artifact",
    "antique", "prop", "character", "actor", "celebrity", "robot", "taxidermy", "book", "comic", "magazine", "record",
    "vinyl", "cassette", "toy", "gift", "souvenir", "merch", "merchandise", "clothes", "clothing", "apparel", "fashion",
    "shoe", "sneaker", "boot", "jean", "shirt", "jacket", "coat", "bag", "wallet", "jewelry", "accessory", "candle",
    "plant", "flower", "furniture", "mattress", "appliance", "electronics", "computer", "produce", "sample", "cosmetic",
    "fragrance", "perfume", "lotion", "skincare", "makeup", "sunglasses", "hat", "umbrella", "luggage", "massage", "facial",
    "sauna", "steam", "haircut", "fade", "trim", "shave", "manicure", "pedicure", "nail", "wax", "waxing", "tattoo",
    "piercing", "treatment", "therapy", "yoga", "pilates", "workout", "training", "equipment", "machine", "locker",
    "shower", "bath", "cleaning", "viewing", "instruction", "sip", "line", "skipping", "ready", "worth", "smoking",
    "conditioning", "only", "free", "included", "allowed", "friendly", "out", "up", "menu", "dinner", "lunch", "breakfast",
    "brunch", "supper", "meal", "special", "feel", "feeling", "star", "michelin", "job", "attention", "playground",
    "admission", "historic", "historical", "palace", "picnic", "bike", "car", "motorcycle", "hiking", "reading",
    "organized", "curfew", "tub", "plunge", "programming", "wristband", "tailoring", "alteration", "grooming",
    "maintenance", "repair", "suit", "opportunity", "dining", "kosher", "halal", "thru", "through", "suitable", "handshake",
    "smoke", "sawdust", "anime", "airport", "sand", "cellar", "swing", "recliner", "cup", "weight", "tooth", "paper", "tax",
    "stuffed", "fan", "felt", "home", "entertainment", "voicemail", "photographer", "degree", "oven", "rehearsal", "moment",
    "dome", "potty", "projector", "chilling", "underground", "learning", "glove", "usage", "recommendation", "cantina",
    "convenience", "feature", "busy", "dark", "hall", "orderliness", "academy", "ramadan", "director", "licence", "license",
    "privacy", "session", "dealing", "butcher", "work", "print", "mezzanine", "cage", "tow", "department", "counter",
    "section", "view", "comfort", "cold",
})
# A role followed by a name ("chef hassan", "employee tarek") is about a person, not a dish.
ROLE_WORDS = frozenset({
    "chef", "employee", "waiter", "waitress", "bartender", "barista", "server", "manager", "owner", "cashier", "captain", "staff",
})
# Dishes and drinks that end on one of the words above: "salad bar", "seafood tower", "tasting menu".
FOOD_COMPOUND_PATTERN = re.compile(
    r"\b(salad|raw|sauce|salsa|oyster|taco|sushi|juice|smoothie|poke|hot food|cereal|candy|toppings?|olive|mezze|antipasti|bagel|"
    r"waffle|pancake|nacho|condiment|dessert|sundae)s? bars?$|\b(seafood|shellfish|oyster|pancake|donut|cake) towers?$|"
    r"\b(tasting|prix fixe|degustation|omakase|chefs?|course|set) menus?$"
)
# Spellings of one word in dish names, by stem: "doughnuts" and "donuts", "margs" and "margaritas", "parmesan" and "parm".
MENU_SPELLINGS = {
    "doughnut": "donut", "shawerma": "shawarma", "kushari": "koshari", "taameya": "tameya", "labn": "labneh",
    "expresso": "espresso", "cappucino": "cappuccino", "marg": "margarita", "barbecu": "bbq", "barbequ": "bbq",
    "parmesan": "parm", "parmigiana": "parm", "chilli": "chili", "omelett": "omelet", "yoghurt": "yogurt", "kabob": "kebab",
    "kebap": "kebab", "bahn": "banh", "texmex": "tex mex", "felafel": "falafel", "desert": "dessert",
}
# One dish under different names, by key: Cairo's ta'ameya is falafel and its foul is fava beans; hookah is shisha.
MENU_SYNONYMS = {
    "tameya": "falafel", "foul": "fava bean", "ful": "fava bean", "fava": "fava bean", "feteer meshaltet": "feteer",
    "hookah": "shisha", "ayc": "all you can eat", "chees cak": "cheesecak",
}
PREPOSITIONS = frozenset({"of", "on", "in", "at", "with", "for", "from", "to", "by", "over", "near", "inside", "around"})
# Genres that mention food or drink but sell neither: a kitchen supply store, a pet food store, a grill store, a B&B.
NOT_FOOD_GENRE = re.compile(
    r"\b(supply|supplies|equipment|appliances?|furniture|pet|grill store|bed (and )?breakfast)\b", re.IGNORECASE
)
# Shops: what they sell can share a word with an experience (an electronics store's TVs, a game store's games).
STORE_GENRE = re.compile(r"\b(stores?|shops?|shopping|boutiques?|outlets?|malls?|supermarkets?|showrooms?|pharmac(y|ies))\b",
                         re.IGNORECASE)
# The experience themes a shop can offer; the others would be its merchandise.
STORE_THEMES = frozenset({
    "Friendly staff", "Cleanliness", "Atmosphere", "Short waits", "Spacious", "Quiet", "Good value", "Outdoor seating",
    "Dog friendly", "Cats", "Vegan options", "Gluten-free options", "Healthy options", "Late night", "Food hall", "Food truck",
})
# Kinds of topic groups, in the order cards list them.
TOPIC_KINDS = ("menu", "experience", "complaint")


def topic_text(name: str) -> str:
    """A keyword as plain words: lowercase, accents and punctuation folded ('Crème brûlée' -> 'creme brulee')."""
    folded = "".join(ch for ch in unicodedata.normalize("NFKD", name or "") if not unicodedata.combining(ch))
    folded = re.sub(r"['’`]", "", folded.lower().replace("&", " and "))
    return " ".join(re.sub(r"[^\w]+|_", " ", folded).split())


def complaint_theme(text: str) -> str | None:
    """The complaint a keyword makes, once dishes named after complaint words and turned-around phrases are set aside."""
    cleaned = " ".join(NEGATED_COMPLAINT_PATTERN.sub(" ", NOT_COMPLAINT_PATTERN.sub(" ", text)).split())
    return next((label for label, pattern in COMPLAINT_THEMES if pattern.search(cleaned)), None)


def experience_theme(text: str) -> str | None:
    """The part of a visit a keyword describes; None for house rules ('no laptops') and topics no theme covers."""
    for label, pattern in TURNED_THEMES:
        if pattern.search(text):
            return label
    if POLICY_PATTERN.search(text):
        return None
    cleaned = " ".join(NOT_EXPERIENCE_PATTERN.sub(" ", text).split())
    return next((label for label, pattern in EXPERIENCE_THEMES if pattern.search(cleaned)), None)


def _singular(word: str) -> str:
    """'bartenders' -> 'bartender', to match a keyword's main word against NOT_MENU_WORDS; gentler than _stem, so a
    'code' never meets a 'cod'."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "ches", "shes", "xes")):
        return word[:-2]
    if word.endswith("s") and len(word) > 3 and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


NOT_MENU_HEADS = frozenset(_singular(word) for word in NOT_MENU_WORDS)


def _stem(word: str) -> str:
    """One form for a word's spellings: 'pastries' and 'pastry', 'cookies' and 'cookie', 'quiches' and 'quiche' meet."""
    if len(word) < 3 or not word.isascii():
        return word
    if word.endswith("ies"):
        word = word[:-3] + "i"
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    if word.endswith("y") and len(word) > 2 and word[-2] not in "aeiou":
        return word[:-1] + "i"
    return word[:-1] if word.endswith("e") and len(word) > 2 else word


def _head(core: str) -> str:
    """The word a keyword is about: its last, or the last before a preposition ('history of ice cream' -> 'history')."""
    words = core.split()
    cut = next((i for i, word in enumerate(words) if i and word in PREPOSITIONS), len(words))
    return words[cut - 1]


def _drop_fillers(words: list[str]) -> list[str]:
    while words and words[0] in FILLER_WORDS:
        words = words[1:]
    return words


def _names_a_dish(core: str) -> bool:
    """Whether a keyword, its filler words dropped, names a dish or a drink rather than people, places, money or goods."""
    words = core.split()
    if core in GENERIC_MENU_TOPICS or not any(len(word) >= 3 and any(ch.isalpha() for ch in word) for word in words):
        return False
    if FOOD_COMPOUND_PATTERN.search(core):
        return True
    return not (len(words) == 2 and words[0] in ROLE_WORDS) and _singular(_head(core)) not in NOT_MENU_HEADS


def menu_key(core: str) -> str:
    """One key for the ways reviews write a dish: 'croissants' and 'croissant', 'egyptian food' and 'egyptian'."""
    stems = [MENU_SPELLINGS.get(_stem(word), _stem(word)) for word in ("and" if word == "n" else word for word in core.split())]
    if len(stems) > 1 and stems[-1] in ("food", "cuisin", "dish"):
        stems = stems[:-1]
    key = " ".join(stems)
    return MENU_SYNONYMS.get(key, key)


def item_key(name: str) -> str:
    """One key for any wording of a dish, drink or activity: 'Great croissants', 'croissant' and 'Croissants' meet."""
    text = topic_text(name)
    return menu_key(" ".join(_drop_fillers(text.split())) or text)


@lru_cache(maxsize=16384)
def topic(keyword: str, setting: str = "food") -> tuple[str, str] | None:
    """What one review keyword is about: ('complaint' | 'experience', theme label), ('menu', dish key), or None.

    None covers neutral topics ('prices', 'cash only', 'bathroom') and experience topics without a theme. `setting` is the
    place's kind (place_setting): only places that sell food or drink have a menu, so a barber's 'fade' or a mattress
    store's 'mattress selection' is no dish, and a store's merchandise is no experience (an electronics store's 'tvs').
    """
    text = topic_text(keyword)
    theme = complaint_theme(text)
    if theme:
        return "complaint", theme
    theme = experience_theme(text)
    if theme:
        return ("experience", theme) if setting != "store" or theme in STORE_THEMES else None
    core = " ".join(_drop_fillers(text.split()))
    if setting != "food" or POLICY_PATTERN.search(text) or not _names_a_dish(core):
        return None
    return "menu", menu_key(core)


def place_setting(entity: dict) -> str:
    """'food' for places that sell food or drink, 'store' for shops, 'other' for venues, hotels, parks and services.

    Judged by the place's genres; a place without genres sells food when it has a price level or a cuisine.
    """
    names = [name for _, name in genre_tags(entity)]
    if not names:
        props = entity.get("properties") or {}
        return "food" if props.get("price_level") or props.get("cuisine_description") else "other"
    if any(matches_focus(name, "food_drink") and not NOT_FOOD_GENRE.search(name) for name in names):
        return "food"
    stores = [name for name in names if STORE_GENRE.search(name)]
    venues = [name for name in names if genre_kind(name) == "venue" and name not in stores]
    return "store" if stores and not venues else "other"


def review_keywords(entity: dict) -> list[dict]:
    """A place's review keywords, without slurs and without the ones that repeat its name, address or neighborhood.

    Movies and shows carry keywords as plain strings; only {"name", "count"} records are review topics.
    """
    props = entity.get("properties") or {}
    neighborhood = props.get("neighborhood") if isinstance(props.get("neighborhood"), str) else ""
    own = _fold(f"{entity.get('name') or ''} {props.get('address') or ''} {neighborhood}")
    return [
        k for k in props.get("keywords") or []
        if isinstance(k, dict) and isinstance(k.get("name"), str) and k["name"].strip() and is_safe_name(k["name"])
        and not _repeats(k["name"], own)
    ]


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)).lower()


def _repeats(keyword: str, own: str) -> bool:
    """Whether a keyword repeats whole words of a place's name or address: 'zamalek' or 'el zamalek' in Zamalek, 'katz' at
    Katz's; 'tea' is not in 'Steak House'."""
    words = re.sub(r"^(el|al|the) ", "", _fold(keyword.strip()))
    return bool(re.search(rf"(?<!\w){re.escape(words)}(?!\w)", own))


def topic_keys(entity: dict) -> set[tuple[str, str]]:
    """The (kind, theme or dish) pairs a place's reviews mention."""
    setting = place_setting(entity)
    return {found for keyword in review_keywords(entity) if (found := topic(keyword["name"], setting))}


def topic_groups(places: Iterable[dict], skip: set[tuple[str, str]] | frozenset = frozenset()) -> dict[str, list[dict]]:
    """What reviews of these places mention, grouped per kind ('menu', 'experience', 'complaint'), most mentioned first.

    A group is {"label", "mentions", "places", "keywords"}: the theme (or, for a dish, the form reviews use most), the
    mentions of all its keywords, the places that mention any of them, and its keywords as reviews write them, most
    mentioned first. Groups whose (kind, key) is in `skip` are left out.
    """
    found: dict[tuple[str, str], dict] = {}
    for index, place in enumerate(places):
        setting = place_setting(place)
        for keyword in review_keywords(place):
            kind_key = topic(keyword["name"], setting)
            if not kind_key or kind_key in skip:
                continue
            group = found.setdefault(kind_key, {"mentions": 0, "places": set(), "forms": Counter()})
            count = int(keyword.get("count") or 0)
            group["mentions"] += count
            group["places"].add(item_id(place) or index)
            group["forms"][" ".join(keyword["name"].lower().split())] += count
    grouped: dict[str, list[dict]] = {kind: [] for kind in TOPIC_KINDS}
    for (kind, key), group in found.items():
        forms = [form for form, _ in sorted(group["forms"].items(), key=lambda item: (-item[1], item[0]))]
        grouped[kind].append({
            "label": forms[0] if kind == "menu" else key,
            "mentions": group["mentions"],
            "places": len(group["places"]),
            "keywords": forms[:5],
        })
    for groups in grouped.values():
        groups.sort(key=lambda g: (-g["mentions"], -g["places"], g["label"]))
    return grouped


def inline_label(label: str) -> str:
    """A label as it reads inside a sentence or a lowercase list: 'Live music and DJs' -> 'live music and DJs'."""
    return label[:1].lower() + label[1:] if label[:1].isupper() and label[1:2].islower() else label


def natural_list(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def known_for(groups: dict[str, list[dict]], limit: int) -> list[str]:
    """What a place is known for, as a lowercase list: its dishes first, then its experience themes."""
    return [inline_label(g["label"]) for g in groups["menu"] + groups["experience"]][:limit]


def place_link(entity: dict) -> tuple[str | None, str | None]:
    """A place's own page, where its offer and prices can be checked: its menu page, else its website, as
    (url, "menu" | "site")."""
    props = entity.get("properties") or {}
    for key, kind in (("menu_url", "menu"), ("website", "site")):
        url = props.get(key)
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            return url, kind
    return None, None


def place_card(entity: dict, site: tuple[float, float] | None = None) -> dict:
    """Compact, UI-friendly view of a place entity."""
    props = entity.get("properties") or {}
    groups = topic_groups([entity])
    location = place_location(entity)
    rating = props.get("business_rating")
    url, link = place_link(entity)
    card = {
        "id": item_id(entity),
        "name": entity.get("name"),
        "address": props.get("address"),
        "rating": round(float(rating), 1) if rating else None,
        "genres": [name for _, name in genre_tags(entity) if is_business_genre(name)][:3],
        "known_for": known_for(groups, 4),
        "complaints": [inline_label(g["label"]) for g in groups["complaint"]][:3],
        "standing": standing(entity),
        "lat": location[0] if location else None,
        "lon": location[1] if location else None,
        "image": (props.get("image") or {}).get("url"),
        "url": url,
        "link": link,
    }
    if site and location:
        card["distance_m"] = round(distance_m(site[0], site[1], *location))
    return card


def summarize_block(places: Iterable[dict]) -> dict:
    places = list(places)
    genres: Counter = Counter()
    ratings: list[float] = []
    classics: list[tuple[tuple, dict]] = []
    for place in places:
        props = place.get("properties") or {}
        business = [name for _, name in genre_tags(place) if is_business_genre(name)]
        for name in business:
            genres[name] += 1
        if props.get("business_rating"):
            ratings.append(float(props["business_rating"]))
        evidence = standing(place)
        if evidence and place.get("name") and business and is_storefront_place(place):
            order = ("michelin" not in evidence, -(evidence.get("reviews") or 0))
            # The badge already says Michelin; review keywords repeating it are not what people come for.
            liked = [label for label in known_for(topic_groups([place]), 6) if "michelin" not in label.lower()]
            classics.append((order, {
                "id": item_id(place), "name": place["name"], "genre": genre_title(primary_genre(place) or business[0]),
                **evidence,
                "known_for": liked[:3],
            }))
    topics = topic_groups(places)
    return {
        "place_count": len(places),
        "top_genres": genres.most_common(12),
        "avg_rating": round(mean(ratings), 2) if ratings else None,
        "menu": topics["menu"][:12],
        "experience": topics["experience"][:10],
        "complaints": topics["complaint"][:8],
        "classics": [card for _, card in sorted(classics, key=lambda item: item[0])[:6]],
    }


DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_GROUPS = (("Mon–Thu", DAYS[:4]), ("Fri–Sat", DAYS[4:6]), ("Sun", DAYS[6:]))


def _clock(value: str | None) -> float | None:
    """'T11:30:00' -> 11.5"""
    match = re.match(r"T?(\d{1,2}):(\d{2})", value or "")
    return int(match.group(1)) + int(match.group(2)) / 60 if match else None


def day_span(intervals: list[dict] | None) -> tuple[float, float] | None:
    """Opening and closing hour of one day, closing after midnight counted past 24; None when closed or unknown."""
    spans = []
    for interval in intervals or []:
        opens, closes = _clock(interval.get("opens")), _clock(interval.get("closes"))
        if interval.get("closed") or opens is None or closes is None:
            continue
        spans.append((opens, closes + 24 if closes <= opens else closes))
    return (min(o for o, _ in spans), max(c for _, c in spans)) if spans else None


def clock_text(hour: float) -> str:
    hour = hour % 24
    if hour == 0:
        return "midnight"
    if hour == 12:
        return "noon"
    whole, minutes = int(hour), round((hour - int(hour)) * 60)
    suffix = "am" if whole < 12 else "pm"
    shown = whole % 12 or 12
    return f"{shown}{f':{minutes:02d}' if minutes else ''} {suffix}"


def hours_by_group(places: Iterable[dict], minimum: int = 3) -> tuple[dict[str, tuple[float, float] | str], int] | None:
    """Median opening and closing hour per day group ('closed' when most places close then), and the sample size.

    Medians are rounded to the half hour. About 7 % of places are listed as closed every day, including busy chains and
    cinemas, which means their hours are unknown, so only places listed as open on at least one day count.
    """
    weekly = [
        hours for p in places
        if isinstance(hours := (p.get("properties") or {}).get("hours"), dict) and any(day_span(hours.get(d)) for d in DAYS)
    ]
    if len(weekly) < minimum:
        return None
    groups: dict[str, tuple[float, float] | str] = {}
    for label, days in DAY_GROUPS:
        spans = [span for hours in weekly for day in days if (span := day_span(hours.get(day)))]
        closed = sum(1 for hours in weekly for day in days if any(i.get("closed") for i in hours.get(day) or []))
        if closed > len(spans):
            groups[label] = "closed"
        elif spans:
            groups[label] = (round(median(o for o, _ in spans) * 2) / 2, round(median(c for _, c in spans) * 2) / 2)
    return groups, len(weekly)


def span_text(span: tuple[float, float] | str) -> str:
    if isinstance(span, str):
        return span
    opens, closes = span
    return "24 hours" if closes - opens >= 24 else f"{clock_text(opens)}–{clock_text(closes)}"


def typical_hours(places: Iterable[dict], minimum: int = 3) -> dict | None:
    """The opening hours most places of a type keep, per day group, from Qloo's listed hours."""
    found = hours_by_group(places, minimum)
    if not found:
        return None
    groups, sample = found
    merged: list[list[str]] = []
    for label, span in groups.items():
        text = span_text(span)
        if merged and merged[-1][1] == text:
            merged[-1][0] = f"{merged[-1][0].split('–')[0]}–{label.split('–')[-1]}"
        else:
            merged.append([label, text])
    if len(merged) == 1:
        merged[0][0] = "Daily"
    return {"text": " · ".join(f"{label} {text}" for label, text in merged), "sample": sample}


def reference_rank(ranks: list[int | None], missing: int = UNRANKED) -> float | None:
    """Median rank of a genre across same-size reference areas; absent genres count as rank `missing`."""
    if not ranks:
        return None
    return float(median([rank if rank is not None else missing for rank in ranks]))


def split_favorites(local: list[dict], city: list[dict], minimum: int = 4) -> tuple[str, list[dict]]:
    """Places locals love more than the city does ('local'), or, if too few, the shared list ('citywide')."""
    city_ids = {item_id(e) for e in city}
    own = [e for e in local if item_id(e) not in city_ids]
    if len(own) >= minimum:
        return "local", own[:10]
    return "citywide", local[:10]


def storefront_share(places: list[dict]) -> float:
    return sum(1 for p in places if is_storefront_place(p)) / len(places) if places else 1.0


def gap_signals(
    genre_id: str,
    genre_name: str,
    local_rank: int,
    ref_rank: float | None,
    nearby: list[dict],
    around: list[dict],
    favorites: list[dict],
    favorites_kind: str,
    storefront: float,
    site: tuple[float, float],
    within: Callable[[float, float], bool],
    nearby_capped: bool | None = None,
    around_capped: bool | None = None,
) -> dict:
    """Raw evidence for one genre. `within(lat, lon)` says whether a point is inside the walking catchment.

    The capped flags say a count reached the most places that were fetched, so the true count may be higher.
    """
    locations = [loc for loc in (place_location(f) for f in favorites) if loc]
    distances = [distance_m(site[0], site[1], *loc) for loc in locations]
    far = [loc for loc in locations if not within(*loc)]
    far_distances = [distance_m(site[0], site[1], *loc) for loc in far]
    return {
        "genre_id": genre_id,
        "genre": genre_name,
        "demand_rank": local_rank,
        "ref_rank": ref_rank,
        "nearby_count": len(nearby),
        "nearby_capped": len(nearby) >= 50 if nearby_capped is None else nearby_capped,
        "around_count": len(around),
        "around_capped": len(around) >= 50 if around_capped is None else around_capped,
        "favorites_kind": favorites_kind,
        "favorites_total": len(locations),
        "favorites_far": len(far),
        "median_favorite_km": round(median(distances) / 1000, 1) if distances else None,
        # How far people go for the favorites outside the walk: the trip a place inside it would save them.
        "median_far_km": round(median(far_distances) / 1000, 1) if far_distances else None,
        "storefront_share": round(storefront, 2),
    }


def score_gaps(
    rows: list[dict], catchment_area_m2: float, around_area_m2: float, baseline_rows: list[dict] | None = None,
) -> list[dict]:
    """Score every genre against same-size areas around the site (demand) and its own surroundings (supply).

    - demand: how highly people here rank the genre, plus how much higher they rank it than same-size areas around
      the site do (up to six, on land; comparing against the whole city inflates genres that rank high at any
      small scale);
    - supply: places within the walk versus what the surrounding density predicts, divided by the site's
      median ratio so parks, rivers and highways in the surroundings do not bias every genre. The places
      within the walk are Qloo's plus those only OpenStreetMap shows there (row['osm'], app.osm), so a
      kind of place Qloo's list lacks is not scored as missing; the site's median ratio stays Qloo's own,
      so a category OpenStreetMap cannot check is scored as it was;
    - leakage: share of the places locals love more than the city does that lie outside the walk. The
      city's famous places are excluded because every neighborhood's favorites include them.

    baseline_rows: an already-scored gap table whose supply baseline new rows must share, so a genre the
    agent tests later is scored on the same scale as the table.
    """
    if not rows:
        return []
    area_ratio = catchment_area_m2 / around_area_m2 if around_area_m2 else 0.25
    for row in rows:
        row["expected_raw"] = round(row["around_count"] * area_ratio, 2)
    # One pseudo-count on both sides: finding none where the surroundings predict 0.25 is not evidence of a gap.
    informative = [_supply_ratio(row, qloo_only=True) for row in (baseline_rows or rows) if row["around_count"] >= 3]
    baseline = median(informative) if informative else 1.0
    baseline = baseline if baseline > 0 else 1.0
    for row in rows:
        local = row["demand_rank"]
        ref = row.get("ref_rank")
        lift = 0.0 if ref is None else max(-1.0, min(1.0, (ref - local) / 10))
        demand = 0.55 * max(0.0, 1 - (local - 1) / 15) + 0.45 * (lift + 1) / 2
        relative = _supply_ratio(row) / baseline
        supply = supply_count(row)
        undersupply = 0.8 / (1 + relative) + 0.2 * (1 - supply / (supply + 6))
        total = row["favorites_total"]
        leakage = None
        if row.get("favorites_kind") == "local" and total >= 3:
            # Shrink small samples toward "no information" (0.5).
            leakage = (row["favorites_far"] + 1) / (total + 2)
        if row["around_count"] < 2:
            evidence = "thin"
        elif row.get("storefront_share", 1.0) < 0.5:
            evidence = "atypical"
        else:
            evidence = "ok"
        raw = demand * undersupply * (0.55 + 0.45 * (0.5 if leakage is None else leakage))
        raw *= 1.0 if evidence == "ok" else 0.55
        row.update({
            "lift": round(lift, 2),
            "relative_supply": round(relative, 2),
            # What a block this dense would typically hold, consistent with relative_supply.
            "expected_nearby": round(max(0.0, (row["expected_raw"] + 1) * baseline - 1), 1),
            "leakage": None if leakage is None else round(leakage, 2),
            "evidence": evidence,
            "gap_score": min(99, round(raw * 175)),
        })
    return sorted(rows, key=lambda row: (row["evidence"] != "ok", -row["gap_score"]))


def osm_extra(row: dict) -> int:
    """How many places of the kind OpenStreetMap shows inside the walk that Qloo does not list there."""
    return len((row.get("osm") or {}).get("extra") or [])


def supply_count(row: dict) -> int:
    """Places of the kind inside the walk: Qloo's, plus those only OpenStreetMap shows."""
    return row["nearby_count"] + osm_extra(row)


def _supply_ratio(row: dict, qloo_only: bool = False) -> float:
    inside = row["nearby_count"] if qloo_only else supply_count(row)
    return (inside + 1) / (row["expected_raw"] + 1)


# Qloo popularity is a percentile; above this an artist or brand is a household name everywhere (Beyoncé, Chanel).
SUPERSTAR = 0.998


def distinctive(local: list[dict], baseline: list[dict], limit: int = 8) -> list[dict]:
    """Entities that rank for the neighborhood but not for the wider metro baseline."""
    baseline_ids = {item_id(e) for e in baseline}
    return [e for e in local if item_id(e) not in baseline_ids and is_safe_name(e.get("name"))][:limit]


def distinctive_by_rank(
    local: list[dict], references: list[list[dict]], limit: int = 8, min_lift: float = 5, max_local_rank: int = 20,
) -> list[dict]:
    """Entities that rank much higher here than in same-size reference areas (median rank, absent = list end + 1)."""
    references = [ref for ref in references if ref]
    if not references:
        return []
    rank_maps = [({item_id(e): i for i, e in enumerate(ref, 1)}, len(ref) + 1) for ref in references]
    scored = []
    for rank, entity in enumerate(local[:max_local_rank], 1):
        eid = item_id(entity)
        if not eid or not is_safe_name(entity.get("name")):
            continue
        # A global star counts as local taste only when no comparison area lists it at all; anywhere else, being ranked
        # a few places higher here is rank noise among the same household names.
        if (entity.get("popularity") or 0) >= SUPERSTAR and any(eid in ranks for ranks, _ in rank_maps):
            continue
        ref_rank = median([ranks.get(eid, missing) for ranks, missing in rank_maps])
        if ref_rank - rank >= min_lift:
            scored.append((-(ref_rank - rank), rank, entity))
    return [entity for _, _, entity in sorted(scored, key=lambda item: (item[0], item[1]))][:limit]


def design_dna(places: Iterable[dict], per_family: int = 6) -> dict:
    """Most common design-relevant tags across a set of places, and what their reviews mention besides complaints."""
    places = list(places)
    dna: dict[str, list[str]] = {}
    for family, prefix in DESIGN_FAMILIES.items():
        counts = Counter(
            t["name"]
            for place in places
            for t in place.get("tags") or []
            if (t.get("type") or "").startswith(prefix) and t.get("name")
        )
        dna[family] = [name for name, _ in counts.most_common(per_family)]
    topics = topic_groups(places)
    liked = sorted(topics["menu"] + topics["experience"], key=lambda g: (-g["mentions"], -g["places"]))
    dna["keywords"] = [g["label"] for g in liked[:10]]
    return dna


def entity_card(entity: dict) -> dict:
    props = entity.get("properties") or {}
    card = {
        "id": item_id(entity),
        "name": entity.get("name"),
        "image": (props.get("image") or {}).get("url"),
        "popularity": round(entity.get("popularity") or 0, 3),
    }
    kind = brand_kind(entity)
    if kind:
        card["kind"] = kind
    # Films and shows have release years and artists start years; podcast dates are the latest episode, so none.
    for key, field in (("year", "release_year"), ("since", "start_year")):
        if isinstance(props.get(field), int):
            card[key] = props[field]
    return card


def era(year: int | None, this_year: int, new_within: int = 10) -> str | None:
    """'classic' when it started or came out 20+ years ago, 'new' within `new_within` years; in between is neither."""
    if not year:
        return None
    if this_year - year >= 20:
        return "classic"
    if this_year - year <= new_within:
        return "new"
    return None


def brand_kind(entity: dict) -> str | None:
    """Qloo's brand type in short form: 'Product Brand' -> 'product'."""
    for tag in entity.get("tags") or []:
        if tag.get("type") == "urn:tag:brand_type:qloo" and tag.get("name"):
            return re.sub(r"\s*brand$", "", tag["name"].strip(), flags=re.IGNORECASE).lower() or None
    return None
