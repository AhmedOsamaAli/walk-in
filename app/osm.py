"""OpenStreetMap cross-check: the named places OpenStreetMap shows inside the walk, so that a kind of place missing from
Qloo's place list is never called missing when it is there.

Once per survey, one Overpass query reads the named shops, amenities, leisure, tourism and craft places (nodes and ways)
inside the walk polygon. Each gap row then counts the places of its kind OpenStreetMap shows inside the walk and adds,
as supply, those that no Qloo place inside the walk matches: a similar name within about 80 m, whatever Qloo's category
for it (Qloo may list a bakery as a Mexican restaurant). Kinds of place that no OpenStreetMap tag pins down ('New
American', 'Bar + Grill') are not checked: a guess would be worse than no cross-check.

The public Overpass instances are run by volunteers (wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances).
Requests identify the app, answers are cached on disk for a week, an instance that fails rests before it is asked again,
and the main FOSSGIS instance, which asks apps to use alternatives, is asked last. When none answers, the survey goes on
and its rows say they were not cross-checked.

Data © OpenStreetMap contributors, available under the Open Database License (www.openstreetmap.org/copyright).
"""
from __future__ import annotations

import asyncio
import contextvars
import difflib
import hashlib
import json
import logging
import math
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import scoring
from .catchment import Catchment
from .geo import distance_m

log = logging.getLogger("walkin")

# Public instances with worldwide data, in the order they are asked. The French community instance answered when the
# others did not (October 2026), with data some weeks old: each answer carries its date, and the survey shows it.
# private.coffee and VK Maps welcome any project; the FOSSGIS instance is overloaded and asks apps to use alternatives
# where possible, so it comes last. An instance that fails rests (is asked last) for REST_S.
ENDPOINTS = (
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)
USER_AGENT = "Walk-in/0.3 (+https://github.com/AhmedOsamaAli/walk-in)"
CREDIT = "© OpenStreetMap contributors"
LICENSE = "ODbL"
COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
LABEL = "Cross-checking the map with OpenStreetMap"

TIMEOUT_S = 12.0  # one request
BUDGET_S = 30.0  # every instance asked, together: the survey waits no longer than this (two dead ones leave time for a third)
CONNECT_S = 5.0
REST_S = 600.0  # an instance that failed is asked last for this long
SERVER_TIMEOUT_S = 10  # what the query asks the server for, so it gives up before the client does
SERVER_MAXSIZE = 64 * 1024 * 1024  # small requests are scheduled first on a busy server
MAX_AGE_S = 7 * 24 * 3600
MAX_POINTS = 100
MATCH_M = 80
_M_PER_DEG = 111_320.0

POI_KEYS = ("amenity", "shop", "leisure", "tourism", "craft")
NAME_KEYS = ("name", "name:en", "int_name", "alt_name", "official_name", "short_name", "brand")

NOTES = {
    "off": "The OpenStreetMap cross-check is off.",
    "unavailable": "Not cross-checked: OpenStreetMap did not answer in time.",
    "unmapped": "Not cross-checked: no OpenStreetMap tag reliably marks this kind of place.",
    "too_big": "Not cross-checked: the area is too large for OpenStreetMap's free servers.",
}


class OsmError(RuntimeError):
    pass


# ---------- Kinds of place ----------
#
# A Qloo genre maps to the OpenStreetMap tags that make a place that kind of place, one alternative per string. In an
# alternative, every condition must hold: 'key=a|b' needs one of the values, 'key=*' any value and '-' among the values
# lets the key be absent. Values are read one by one from lists such as cuisine=coffee_shop;donut. Each alternative is
# sufficient on its own: when tags cannot say a place is of the kind (a bar is not necessarily a cocktail bar), the kind
# needs the specific tag or is left unmapped, and its rows say they were not checked.

_COFFEE = "coffee_shop|coffee|espresso"
_CAFE_LIKE = "bar|pub|nightclub|restaurant|cafe"
_JAPANESE = "japanese|sushi|ramen|izakaya|udon|soba|yakitori|tonkatsu|teppanyaki|okonomiyaki|donburi"
_CHINESE = "chinese|cantonese|sichuan|szechuan|dim_sum|hunan|shanghainese"
_ASIAN = (f"asian|{_CHINESE}|{_JAPANESE}|korean|thai|vietnamese|pho|malaysian|indonesian|filipino|taiwanese|singaporean|"
          "burmese|cambodian|laotian")
_MIDDLE_EAST = ("middle_eastern|lebanese|syrian|arab|arabic|persian|iranian|israeli|palestinian|jordanian|iraqi|yemeni|"
                "falafel|shawarma")
_LATIN = ("latin_american|peruvian|colombian|venezuelan|argentinian|argentine|brazilian|cuban|salvadoran|honduran|"
          "guatemalan|nicaraguan|puerto_rican|dominican|ecuadorian|chilean|bolivian|uruguayan|costa_rican|panamanian")
# Genres named after one cuisine that OpenStreetMap writes the same way ('Thai' is cuisine=thai).
_PLAIN_CUISINES = (
    "greek lebanese turkish thai korean ethiopian eritrean moroccan peruvian brazilian colombian venezuelan cuban "
    "filipino indonesian malaysian nepalese pakistani afghan polish russian ukrainian georgian portuguese irish hawaiian "
    "syrian israeli jamaican taiwanese singaporean burmese cambodian laotian salvadoran"
)

_KIND_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Bakeries and sweets
    ("bakery bakeshop bakehouse", ("shop=bakery|pastry", "cuisine=bakery")),
    ("pastryshop patisserie", ("shop=pastry",)),
    ("cakeshop", ("shop=bakery|pastry cuisine=cake",)),
    ("donutshop doughnutshop", ("cuisine=donut|doughnut|donuts",)),
    ("bagelshop", ("cuisine=bagel|bagels",)),
    ("icecreamshop icecreamparlor icecreamparlour gelatoshop frozenyogurtshop",
     ("amenity=ice_cream", "shop=ice_cream", "cuisine=ice_cream|gelato|frozen_yogurt")),
    ("dessertshop dessert", ("amenity=ice_cream", "shop=ice_cream|pastry",
                             "cuisine=dessert|desserts|ice_cream|gelato|frozen_yogurt|cake")),
    ("chocolateshop", ("shop=chocolate",)),
    ("candystore confectionery", ("shop=confectionery",)),
    # Coffee, tea and juice
    ("coffeeshop coffeehouse espressobar teaandcoffeeshop",
     ("amenity=cafe cuisine=-", f"amenity=cafe cuisine={_COFFEE}", f"cuisine={_COFFEE}")),
    ("cafe", ("amenity=cafe",)),
    ("teahouse tearoom", ("amenity=cafe cuisine=tea",)),
    ("bubbleteashop bubbletea", ("cuisine=bubble_tea",)),
    ("juiceshop juicebar smoothieshop", ("amenity=juice_bar", "cuisine=juice|smoothie|smoothies")),
    # Quick food
    ("sandwichshop sandwich", ("cuisine=sandwich|sandwiches",)),
    ("deli delicatessen", ("shop=deli", "cuisine=deli|delicatessen")),
    ("pizza pizzeria", ("cuisine=pizza|italian_pizza",)),
    ("hamburger burger", ("cuisine=burger|burgers|hamburger",)),
    ("fastfood", ("amenity=fast_food",)),
    ("hotdog hotdogstand", ("cuisine=hot_dog",)),
    ("chicken friedchicken", ("cuisine=chicken|fried_chicken",)),
    ("chickenwings wings", ("cuisine=wings|chicken_wings",)),
    ("saladshop salad", ("cuisine=salad",)),
    ("pokebar poke", ("cuisine=poke",)),
    ("creperie", ("cuisine=crepe|crepes|creperie",)),
    ("foodcourt foodhall", ("amenity=food_court",)),
    # Restaurants by what they serve
    ("diner", ("cuisine=diner",)),
    ("steakhouse steak", ("cuisine=steak_house|steak|steakhouse",)),
    ("barbecue bbq", ("cuisine=barbecue|bbq",)),
    ("breakfast", ("cuisine=breakfast|brunch",)),
    ("brunch", ("cuisine=brunch",)),
    ("seafood fishrestaurant", ("cuisine=seafood|fish|oyster|oysters|crab|lobster|crawfish",)),
    ("oysterbar rawbar", ("cuisine=oyster|oysters",)),
    ("mexican", ("cuisine=mexican|tex_mex|tacos|taco|burrito|burritos",)),
    ("texmex", ("cuisine=tex_mex",)),
    ("taco tacos taqueria", ("cuisine=tacos|taco",)),
    ("italian", ("cuisine=italian",)),
    ("japanese", (f"cuisine={_JAPANESE}",)),
    ("sushi", ("cuisine=sushi",)),
    ("ramen", ("cuisine=ramen",)),
    ("izakaya", ("cuisine=izakaya",)),
    ("chinese", (f"cuisine={_CHINESE}",)),
    ("asian", (f"cuisine={_ASIAN}",)),
    ("vietnamese", ("cuisine=vietnamese|pho|banh_mi",)),
    ("pho", ("cuisine=pho",)),
    ("noodleshop noodle noodles", ("cuisine=noodle|noodles|ramen|pho|udon|soba",)),
    ("indian", ("cuisine=indian|north_indian|south_indian|punjabi",)),
    ("mediterranean", ("cuisine=mediterranean|greek|lebanese",)),
    ("middleeastern", (f"cuisine={_MIDDLE_EAST}",)),
    ("persian iranian", ("cuisine=persian|iranian",)),
    ("spanish", ("cuisine=spanish|tapas|basque|catalan|paella",)),
    ("tapas tapasbar", ("cuisine=tapas",)),
    ("german", ("cuisine=german|bavarian|swabian",)),
    ("british", ("cuisine=british|english",)),
    ("french", ("cuisine=french",)),
    ("cajun", ("cuisine=cajun|creole",)),
    ("southern soulfood", ("cuisine=southern|soul_food|cajun|creole",)),
    ("latinamerican", (f"cuisine={_LATIN}",)),
    ("argentinian argentine", ("cuisine=argentinian|argentine",)),
    ("caribbean", ("cuisine=caribbean|jamaican|haitian|trinidadian|cuban|puerto_rican|dominican",)),
    ("srilankan", ("cuisine=sri_lankan",)),
    ("egyptian", ("cuisine=egyptian|koshary|koshari|kushari",)),
    ("koshari koshary", ("cuisine=koshary|koshari|kushari",)),
    ("shawarma", ("cuisine=shawarma",)),
    ("falafel", ("cuisine=falafel",)),
    ("kebab kebabshop", ("cuisine=kebab|doner|doner_kebab",)),
    ("hotpot", ("cuisine=hotpot|hot_pot",)),
    ("vegan", ("diet:vegan=only", "cuisine=vegan")),
    ("vegetarian", ("diet:vegetarian=only", "diet:vegan=only", "cuisine=vegetarian|vegan")),
    ("glutenfree", ("diet:gluten_free=only",)),
    ("bistro", ("cuisine=bistro",)),
    ("gastropub", ("cuisine=gastropub",)),
    ("finedining", ("cuisine=fine_dining",)),
    # Bars and nights out
    ("pub", ("amenity=pub",)),
    ("brewery microbrewery", ("craft=brewery", "microbrewery=yes")),
    ("brewpub", ("amenity=pub|bar|restaurant|biergarten microbrewery=yes", "amenity=pub|bar|restaurant craft=brewery")),
    ("beergarden biergarten", ("amenity=biergarten", "beer_garden=yes")),
    ("nightclub discoclub danceclub disco", ("amenity=nightclub",)),
    ("karaokebar karaoke", ("amenity=karaoke_box|karaoke", "karaoke=yes")),
    ("livemusicvenue livemusicbar musicvenue livemusicclub",
     ("amenity=music_venue", "live_music=yes amenity=bar|pub|nightclub|restaurant|cafe|biergarten|arts_centre")),
    ("winebar", ("bar=wine|wine_bar|winebar", f"amenity={_CAFE_LIKE} cuisine=wine|wine_bar")),
    ("cocktailbar", (f"amenity={_CAFE_LIKE} cocktails=yes|served", f"amenity={_CAFE_LIKE} drink:cocktail=yes|served",
                     "bar=cocktail|cocktails|cocktail_bar", f"amenity={_CAFE_LIKE} cuisine=cocktail|cocktails")),
    ("sportsbar", ("bar=sports|sportsbar|sports_bar",)),
    ("lounge", ("bar=lounge", "lounge=yes amenity=bar|pub|nightclub")),
    ("hookahbar hookahlounge shishabar shishalounge", ("amenity=hookah_lounge",)),
    ("comedyclub", ("amenity=theatre theatre:genre=comedy",)),
    # Leisure and personal care
    ("gym fitnesscenter fitnesscentre fitnessstudio healthclub",
     ("leisure=fitness_centre sport=-", "leisure=fitness_centre|sports_centre sport=fitness|weightlifting|crossfit|bodybuilding")),
    ("yogastudio yoga", ("sport=yoga",)),
    ("pilatesstudio pilates", ("sport=pilates",)),
    ("spa dayspa healthspa", ("shop=beauty beauty=spa", "amenity=spa", "leisure=spa")),
    ("massage", ("shop=massage",)),
    ("personalcare", ("shop=hairdresser|beauty|massage",)),
    ("barbershop barber", ("shop=hairdresser hairdresser=barber", "shop=barber")),
    ("hairsalon hairdresser", ("shop=hairdresser hairdresser=-|salon|unisex|women|female|ladies",)),
    ("nailsalon", ("shop=beauty beauty=nails", "shop=nails")),
    ("beautysalon", ("shop=beauty",)),
    ("tattooshop tattooparlor tattooparlour tattoostudio", ("shop=tattoo",)),
    ("eyebrowbar", ("shop=beauty beauty=eyebrow|eyebrows|brow|brows|threading",)),
    ("videoarcade arcade amusementarcade", ("leisure=amusement_arcade",)),
    ("bowlingalley", ("leisure=bowling_alley",)),
    ("escaperoom", ("leisure=escape_game",)),
    ("artcenter artscenter artcentre", ("amenity=arts_centre",)),
    ("artgallery", ("tourism=gallery", "shop=art")),
    # Shops
    ("giftshop giftstore", ("shop=gift|souvenir",)),
    ("souvenirstore souvenirshop", ("shop=souvenir",)),
    ("bookstore bookshop", ("shop=books",)),
    ("recordstore recordshop", ("shop=music",)),
    ("musicalinstrumentstore", ("shop=musical_instrument",)),
    ("clothingstore clothesstore", ("shop=clothes|boutique",)),
    ("womensclothingstore", ("shop=clothes clothes=women|female|ladies",)),
    ("mensclothingstore", ("shop=clothes clothes=men|male",)),
    ("lingeriestore", ("shop=clothes clothes=underwear|lingerie",)),
    ("boutique", ("shop=boutique",)),
    ("fashionaccessoriesstore", ("shop=fashion_accessories",)),
    ("thriftstore secondhandstore charityshop", ("shop=second_hand|charity",)),
    ("shoestore shoeshop", ("shop=shoes",)),
    ("jewelrystore jewellerystore", ("shop=jewelry",)),
    ("cosmeticsstore", ("shop=cosmetics",)),
    ("electronicsstore", ("shop=electronics",)),
    ("cellphonestore mobilephonestore", ("shop=mobile_phone",)),
    ("computerstore", ("shop=computer",)),
    ("toystore", ("shop=toys",)),
    ("sportinggoodsstore", ("shop=sports",)),
    ("outdoorsportsstore", ("shop=outdoor",)),
    ("generalstore", ("shop=general",)),
    ("butchershop butcher", ("shop=butcher",)),
    ("seafoodmarket fishmarket", ("shop=seafood",)),
    ("cheeseshop", ("shop=cheese",)),
    ("winestore wineshop", ("shop=wine",)),
    ("liquorstore", ("shop=alcohol",)),
    ("tobaccoshop", ("shop=tobacco",)),
    ("teastore", ("shop=tea",)),
    ("coffeestore", ("shop=coffee",)),
    ("florist", ("shop=florist",)),
    ("petstore petshop", ("shop=pet",)),
    ("bicycleshop bikeshop", ("shop=bicycle",)),
    ("furniturestore", ("shop=furniture",)),
    ("hardwarestore", ("shop=hardware|doityourself",)),
    ("optician", ("shop=optician",)),
    ("pharmacy drugstore", ("amenity=pharmacy", "shop=chemist")),
    ("conveniencestore", ("shop=convenience",)),
    ("grocerystore", ("shop=supermarket|greengrocer|grocery",)),
)


@dataclass(frozen=True)
class Condition:
    key: str
    values: frozenset[str] | None  # None: any value
    absent_ok: bool

    def holds(self, tags: Mapping[str, str]) -> bool:
        raw = tags.get(self.key)
        if raw is None or not str(raw).strip():
            return self.absent_ok
        return self.values is None or bool(tag_values(raw) & self.values)


@dataclass(frozen=True)
class Kind:
    """The OpenStreetMap side of one Qloo genre."""

    key: str
    rules: tuple[tuple[Condition, ...], ...]
    text: tuple[str, ...]  # the rules as written, for people

    def matches(self, tags: Mapping[str, str]) -> bool:
        return any(all(condition.holds(tags) for condition in rule) for rule in self.rules)


def tag_value(value: str) -> str:
    """One tag value in a comparable form: 'Coffee Shop', 'coffee_shop' and 'coffee-shop' meet."""
    return re.sub(r"[\s\-]+", "_", value.strip().lower())


def tag_values(raw: str) -> set[str]:
    return {tag_value(part) for part in str(raw).split(";") if part.strip()}


def _rule(text: str) -> tuple[Condition, ...]:
    conditions = []
    for part in text.split():
        key, _, raw = part.partition("=")
        options = raw.split("|")
        values = None if "*" in options else frozenset(tag_value(o) for o in options if o not in ("-", "*"))
        conditions.append(Condition(key, values, "-" in options))
    return tuple(conditions)


def _build_kinds() -> dict[str, Kind]:
    kinds: dict[str, Kind] = {}
    table = list(_KIND_TABLE) + [(word, (f"cuisine={word}",)) for word in _PLAIN_CUISINES.split()]
    for keys, rules in table:
        for key in keys.split():
            if key in kinds:
                raise ValueError(f"Kind {key} is mapped twice")
            kinds[key] = Kind(key, tuple(_rule(rule) for rule in rules), rules)
    return kinds


KINDS = _build_kinds()
# The keys the rules read, kept from each place along with its names.
RULE_KEYS = frozenset(condition.key for kind in KINDS.values() for rule in kind.rules for condition in rule)
KEEP_TAGS = frozenset(POI_KEYS) | frozenset(NAME_KEYS) | RULE_KEYS
GENRE_PREFIX = "urn:tag:genre:place:"


def kind_key(genre: str) -> str:
    """A genre name as a table key: 'Ice cream shop' -> 'icecreamshop', 'Bar & grill' and 'Bar + Grill' -> 'barandgrill',
    'Southern restaurant (US)' -> 'southern'."""
    text = scoring.topic_text(re.sub(r"\(.*?\)", " ", genre or "").replace("+", "&"))
    return "".join(word for word in text.split() if word not in ("restaurant", "restaurants"))


def kind_of(genre: str, genre_id: str | None = None) -> Kind | None:
    """The OpenStreetMap side of a Qloo genre, by its name or else by its tag id; None when no tag says it reliably."""
    found = KINDS.get(kind_key(genre))
    if found is None and genre_id and genre_id.startswith(GENRE_PREFIX):
        found = KINDS.get(genre_id.rsplit(":", 1)[-1].replace("_", ""))
    return found


# ---------- Names ----------

def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# Words that say what a place is rather than which one it is; two names that differ only in them name one place.
GENERIC_NAME_WORDS = _words("""
the and a an of at
bakery bakeries bakeshop bakehouse patisserie boulangerie cafe cafes caffe coffee coffeehouse coffeeshop espresso shop
shoppe store stores restaurant restaurants ristorante restaurante trattoria eatery kitchen grill grille bar bars pub
tavern lounge taproom diner deli delicatessen bistro brasserie pizzeria taqueria cantina co company inc llc ltd house
place spot studio salon gym boutique market
""")


@dataclass(frozen=True)
class Name:
    text: str  # plain words: accents, case and punctuation folded, 'the' and 'and' dropped ('&' reads as 'and')
    core: frozenset[str]  # the words that say which place it is

    @classmethod
    def of(cls, name: str) -> Name:
        text = " ".join(w for w in scoring.topic_text((name or "").replace("+", "&")).split() if w not in ("the", "and"))
        return cls(text, frozenset(w for w in text.split() if w not in GENERIC_NAME_WORDS))


def similar(a: Name, b: Name, strict: bool = False) -> bool:
    """Whether two names name one place. One name may add words to the other ("Joe's" and "Joe's Bakery & Coffee
    Shop") when what they share is specific; `strict` asks for the same words, for places with no location."""
    if not a.text or not b.text:
        return False
    if a.text == b.text or a.text.replace(" ", "") == b.text.replace(" ", ""):
        return True
    if a.core and a.core == b.core:
        return True
    if strict:
        return False
    if a.core and b.core:
        small, large = sorted((a.core, b.core), key=len)
        if small <= large and (len(small) >= 2 or max(len(word) for word in small) >= 4):
            return True
    return difflib.SequenceMatcher(None, a.text, b.text).ratio() >= 0.88


def same_name(a: str, b: str) -> bool:
    return similar(Name.of(a), Name.of(b))


def _latin(text: str) -> bool:
    return all(ord(ch) < 0x250 for ch in text if ch.isalpha())


def display_name(tags: Mapping[str, str]) -> str:
    """The name to show: the English one for a name written in another script (Arabic in Cairo), else the name."""
    name = tags["name"]
    english = tags.get("name:en")
    return english if english and not _latin(name) else name


def place_names(tags: Mapping[str, str]) -> list[str]:
    """Every name a place goes by, to match against Qloo's."""
    names: list[str] = []
    for key in NAME_KEYS:
        for value in str(tags.get(key) or "").split(";"):
            if value.strip() and value.strip() not in names:
                names.append(value.strip())
    return names


def place_url(place_id: str) -> str:
    return f"https://www.openstreetmap.org/{place_id}"


# ---------- The query ----------

def simplify(ring: list[tuple[float, float]], max_points: int = MAX_POINTS) -> list[tuple[float, float]]:
    """A (lon, lat) ring as at most `max_points` points without the closing one: Ramer-Douglas-Peucker in metres, its
    tolerance doubled until the ring fits."""
    points = list(ring[:-1]) if len(ring) > 1 and ring[0] == ring[-1] else list(ring)
    if len(points) <= max_points:
        return points
    lat0 = sum(lat for _, lat in points) / len(points)
    kx = _M_PER_DEG * math.cos(math.radians(lat0))
    xy = [(lon * kx, lat * _M_PER_DEG) for lon, lat in points]
    tolerance = 1.0
    while True:
        keep = _peucker(xy + [xy[0]], tolerance)[:-1]  # the closing point is the first one again
        if len(keep) <= max_points:
            return [points[i] for i in keep]
        tolerance *= 2


def _peucker(xy: list[tuple[float, float]], tolerance: float) -> list[int]:
    keep = {0, len(xy) - 1}
    stack = [(0, len(xy) - 1)]
    while stack:
        first, last = stack.pop()
        (x1, y1), (x2, y2) = xy[first], xy[last]
        length = math.hypot(x2 - x1, y2 - y1)
        best, index = 0.0, None
        for i in range(first + 1, last):
            x, y = xy[i]
            gap = (abs((x2 - x1) * (y1 - y) - (x1 - x) * (y2 - y1)) / length) if length else math.hypot(x - x1, y - y1)
            if gap > best:
                best, index = gap, i
        if index is not None and best > tolerance:
            keep.add(index)
            stack += [(first, index), (index, last)]
    return sorted(keep)


def overpass_query(ring: list[tuple[float, float]]) -> str:
    """One Overpass QL query for every named node and way with an amenity, shop, leisure, tourism or craft tag inside the
    (lon, lat) ring, one indexed key filter each. Overpass reads polygons as 'lat lon' pairs."""
    poly = " ".join(f"{lat:.5f} {lon:.5f}" for lon, lat in simplify(ring))
    each = "".join(f'nw["{key}"]["name"](poly:"{poly}");' for key in POI_KEYS)
    return f"[out:json][timeout:{SERVER_TIMEOUT_S}][maxsize:{SERVER_MAXSIZE}];({each});out center tags;"


def compact(elements: Iterable[dict]) -> list[dict]:
    """Overpass elements as the cache keeps them: named, located (a way at its center), with the tags the rules read."""
    out = []
    for element in elements:
        tags = element.get("tags") or {}
        center = element.get("center") or {}
        lat, lon = element.get("lat", center.get("lat")), element.get("lon", center.get("lon"))
        if not tags.get("name") or lat is None or lon is None or element.get("type") not in ("node", "way"):
            continue
        out.append({"type": element["type"], "id": element["id"], "lat": round(float(lat), 6), "lon": round(float(lon), 6),
                    "tags": {k: v for k, v in tags.items() if k in KEEP_TAGS}})
    return out


def places_inside(elements: Iterable[dict], contains: Callable[[float, float], bool]) -> list[dict]:
    """The places inside the walk; a place drawn twice (its node and its building) counts once."""
    places: list[dict] = []
    by_name: dict[str, list[tuple[float, float]]] = {}
    for element in elements:
        lat, lon, tags = element["lat"], element["lon"], element["tags"]
        if not contains(lat, lon):
            continue
        key = Name.of(tags["name"]).text
        if any(distance_m(lat, lon, *point) <= MATCH_M for point in by_name.get(key, [])):
            continue
        by_name.setdefault(key, []).append((lat, lon))
        places.append({
            "id": f"{element['type']}/{element['id']}", "name": display_name(tags), "names": place_names(tags),
            "lat": lat, "lon": lon, "tags": tags,
        })
    return places


# ---------- One survey's cross-check ----------

@dataclass
class Scan:
    """What OpenStreetMap shows inside one walk."""

    checked: bool
    places: list[dict] = field(default_factory=list)
    source: str | None = None  # the Overpass instance that answered
    as_of: str | None = None  # when OpenStreetMap's data was last updated on that instance
    note: str | None = None  # why the walk was not cross-checked
    reason: str = "unavailable"  # why not, for the gap rows: 'unavailable' (no answer in time) or 'too_big'


def unchecked(reason: str, note: str | None = None) -> dict:
    return {"checked": False, "count": 0, "extra": [], "reason": reason, "note": note or NOTES[reason]}


def main_tag(tags: Mapping[str, str]) -> str | None:
    """'shop=pastry': what OpenStreetMap says a place is."""
    return next((f"{key}={tags[key]}" for key in POI_KEYS if tags.get(key)), None)


@dataclass
class _Known:
    names: tuple[Name, ...]
    lat: float | None
    lon: float | None


def qloo_names(place: dict) -> list[str]:
    """The names a Qloo place goes by: its name and its also-known-as names, which Qloo writes 'Name, address'."""
    names = [place["name"]] if place.get("name") else []
    for aka in (place.get("properties") or {}).get("akas") or []:
        value = aka.get("value") if isinstance(aka, dict) else None
        if isinstance(value, str):
            alias = value.split(",")[0].strip().strip('"')
            if alias and alias not in names:
                names.append(alias)
    return names


class CrossCheck:
    """One survey's cross-check: what OpenStreetMap shows inside the walk, and every Qloo place known to be there.

    A place OpenStreetMap shows is already known when a Qloo place has a similar name within MATCH_M of it, whatever
    Qloo's category for it (Qloo may list a bakery as a Mexican restaurant); closed ones count too, since OpenStreetMap
    keeps places that have closed. Qloo's places come from the lists the survey read inside the walk, and from a name
    search on Qloo around each place only OpenStreetMap seems to show (engine.cross_check), so an extra is a place Qloo
    does not list there.
    """

    def __init__(self, scan: Scan | None, catchment: Catchment | None = None) -> None:
        self.scan = scan
        self._contains = catchment.contains if catchment else None
        self._site = (catchment.lat, catchment.lon) if catchment else None
        # The area in the notes: 'the walk' as always, or 'the 30-minute drive'.
        self._here = catchment.label if catchment and catchment.travel != "walk" else "walk"
        self._known: list[_Known] = []
        self._ids: set[str] = set()
        self._verdicts: dict[str, bool] = {}

    @property
    def checked(self) -> bool:
        return bool(self.scan and self.scan.checked)

    def learn(self, places: Iterable[dict], inside_only: bool = False, located_only: bool = False) -> None:
        """Qloo places known around the walk. Lists Qloo filtered to the walk are taken whole; from wider lists, such
        as the favorites, only the places located inside the walk (`inside_only`); name-search results only with a
        location (`located_only`), since a name alone could be a branch across town."""
        for place in places:
            names = qloo_names(place)
            location = scoring.place_location(place)
            pid = scoring.item_id(place) or f"{names[:1]}@{location}"
            if not names or pid in self._ids:
                continue
            if location is None and (inside_only or located_only):
                continue
            if inside_only and (self._contains is None or not self._contains(*location)):
                continue
            self._ids.add(pid)
            self._known.append(_Known(tuple(Name.of(name) for name in names), *(location or (None, None))))
            self._verdicts.clear()

    def learn_row(self, row: dict) -> None:
        self.learn(row.get("_nearby_entities") or [])
        self.learn(row.get("_closed_nearby") or [])
        self.learn(row.get("_favorite_entities") or [], inside_only=True)

    def places_of(self, genre: str, genre_id: str | None = None) -> list[dict] | None:
        """The places of a kind OpenStreetMap shows inside the walk; None when the walk or the kind is not checked."""
        kind = kind_of(genre, genre_id)
        if not self.checked or kind is None:
            return None
        return [place for place in self.scan.places if kind.matches(place["tags"])]

    def candidates(self, rows: Iterable[dict]) -> list[dict]:
        """The places of the rows' kinds that no Qloo place read so far matches, nearest the site first."""
        found: dict[str, dict] = {}
        for row in rows:
            if row.get("nearby_capped"):
                continue
            for place in self.places_of(row["genre"], row.get("genre_id")) or []:
                if not self.known(place):
                    found.setdefault(place["id"], place)
        return sorted(found.values(), key=self._distance)

    def apply(self, row: dict) -> dict:
        """Sets row['osm']: whether the row's kind was checked, how many places of it OpenStreetMap shows inside the
        walk, and the ones no Qloo place matches (its extras, nearest first)."""
        self.learn_row(row)
        row["osm"] = self.check(row["genre"], row.get("genre_id"), capped=bool(row.get("nearby_capped")))
        return row["osm"]

    def check(self, genre: str, genre_id: str | None = None, capped: bool = False) -> dict:
        if self.scan is None:
            return unchecked("off")
        if not self.scan.checked:
            return unchecked(self.scan.reason, self.scan.note)
        places = self.places_of(genre, genre_id)
        if places is None:
            return unchecked("unmapped")
        result = {"checked": True, "count": len(places), "extra": [], "as_of": self.scan.as_of, "credit": CREDIT}
        if capped:
            # Qloo has more of these inside the walk than it returns, so its list cannot tell which ones it lacks.
            return {**result, "note": f"Qloo lists more places of this kind inside the {self._here} than it returns, so the "
                                      f"{len(places)} OpenStreetMap shows are not compared one by one."}
        extra = [self._card(place) for place in sorted(places, key=self._distance) if not self.known(place)]
        return {**result, "extra": extra}

    def known(self, place: dict) -> bool:
        verdict = self._verdicts.get(place["id"])
        if verdict is None:
            verdict = self._verdicts[place["id"]] = self._matches(place)
        return verdict

    def _matches(self, place: dict) -> bool:
        names = [Name.of(name) for name in place.get("names") or [place["name"]]]
        lat, lon = place["lat"], place["lon"]
        near_lat = MATCH_M / _M_PER_DEG
        near_lon = near_lat / max(0.1, math.cos(math.radians(lat)))
        for known in self._known:
            if known.lat is None or known.lon is None:
                # Only lists filtered to the walk give places without a location: the same name is enough.
                if any(similar(name, other, strict=True) for name in names for other in known.names):
                    return True
                continue
            if abs(known.lat - lat) > near_lat or abs(known.lon - lon) > near_lon:
                continue
            if distance_m(lat, lon, known.lat, known.lon) <= MATCH_M and any(
                similar(name, other) for name in names for other in known.names
            ):
                return True
        return False

    def _distance(self, place: dict) -> float:
        return distance_m(*self._site, place["lat"], place["lon"]) if self._site else 0.0

    def _card(self, place: dict) -> dict:
        card = {"name": place["name"], "lat": place["lat"], "lon": place["lon"], "url": place_url(place["id"]),
                "tag": main_tag(place["tags"])}
        if self._site:
            card["distance_m"] = round(self._distance(place))
        return card


_current: contextvars.ContextVar[CrossCheck | None] = contextvars.ContextVar("osm_cross_check", default=None)


def track(check: CrossCheck | None) -> CrossCheck | None:
    """Makes `check` the cross-check of the survey the current task runs, for the categories it measures later (the
    agent's tests, the owner's business); a survey sets it before anything reads it, so surveys never share one."""
    _current.set(check)
    return check


def current() -> CrossCheck | None:
    return _current.get()


# ---------- The client ----------

def _saved(cache_file: Path) -> tuple[dict, float] | None:
    try:
        return json.loads(cache_file.read_text(encoding="utf-8")), cache_file.stat().st_mtime
    except (OSError, ValueError):
        return None


def _answer_of(response: httpx.Response) -> dict:
    if response.status_code != 200:
        raise OsmError(f"HTTP {response.status_code}")
    data = response.json()
    # A query that runs out of time or memory still answers 200, with what it found so far and a remark.
    remark = str(data.get("remark") or "")
    if "error" in remark.lower():
        raise OsmError(remark[:160])
    if not isinstance(data.get("elements"), list):
        raise OsmError("no elements in the answer")
    return data


def _describe(exc: BaseException) -> str:
    return str(exc) if isinstance(exc, OsmError) else type(exc).__name__


class OsmClient:
    """Asks public Overpass instances for the places inside a walk, with an on-disk cache keyed by the query."""

    def __init__(
        self,
        cache_dir: Path,
        endpoints: Iterable[str] = ENDPOINTS,
        timeout: float = TIMEOUT_S,
        budget: float = BUDGET_S,
        max_age_s: float = MAX_AGE_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._cache_dir = cache_dir
        self._endpoints = tuple(endpoints)
        self._timeout = timeout
        self._budget = budget
        self._max_age_s = max_age_s
        self._http = httpx.AsyncClient(headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, transport=transport)
        # The instances ask for no parallel scripts; two surveys may ask at once, more wait.
        self._gate = asyncio.Semaphore(2)
        self._inflight: dict[str, asyncio.Future] = {}
        self._failed: dict[str, float] = {}
        self.calls = 0
        self.cache_hits = 0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def scan(self, catchment: Catchment) -> Scan:
        """The named places OpenStreetMap shows inside the walk; never raises: when no instance answers in time, the
        scan says so and the survey goes on without the cross-check."""
        try:
            data = await self._answer(overpass_query(catchment.ring))
            return Scan(True, places_inside(data["elements"], catchment.contains), data.get("source"), data.get("as_of"))
        except OsmError as exc:
            log.warning("OpenStreetMap cross-check skipped: %s", exc)
        except Exception:  # an answer shaped unlike any seen so far must not stop the survey either
            log.warning("OpenStreetMap cross-check failed", exc_info=True)
        return Scan(False, note=NOTES["unavailable"])

    async def _answer(self, query: str) -> dict:
        key = hashlib.sha1(query.encode("utf-8")).hexdigest()
        cache_file = self._cache_dir / f"{key}.json"
        saved = _saved(cache_file)
        if saved and time.time() - saved[1] < self._max_age_s:
            self.cache_hits += 1
            return saved[0]
        if key in self._inflight:
            try:
                return await asyncio.shield(self._inflight[key])
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    raise
                raise OsmError("the survey that asked first was stopped") from None
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            try:
                data = await self._fetch(query)
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            except OsmError as exc:
                if not saved:
                    raise
                log.warning("OpenStreetMap did not answer (%s); using its answer from %s", exc, time.ctime(saved[1]))
                data = saved[0]
                self.cache_hits += 1
            future.set_result(data)
            return data
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as exc:
            future.set_exception(exc)
            future.exception()  # retrieved, so asyncio does not warn when nobody else waits for it
            raise
        finally:
            self._inflight.pop(key, None)

    def _resting(self, url: str) -> bool:
        return time.monotonic() - self._failed.get(url, -math.inf) < REST_S

    def _order(self) -> list[str]:
        """The instances to ask: those that answered last time first; when every one failed in the last REST_S seconds,
        only the one that failed longest ago, so an outage costs each survey one try."""
        fresh = [url for url in self._endpoints if not self._resting(url)]
        if fresh:
            return fresh + sorted((url for url in self._endpoints if url not in fresh), key=lambda url: self._failed[url])
        return sorted(self._endpoints, key=lambda url: self._failed[url])[:1]

    async def _fetch(self, query: str) -> dict:
        # The budget covers the wait for other surveys' queries too, so a survey never waits longer than it.
        deadline = time.monotonic() + self._budget
        try:
            async with asyncio.timeout(self._budget):
                await self._gate.acquire()
        except TimeoutError:
            raise OsmError("other surveys were asking OpenStreetMap") from None
        try:
            problems = []
            for url in self._order():
                remaining = deadline - time.monotonic()
                if remaining < 1:
                    break
                limit = min(self._timeout, remaining)
                host = urlsplit(url).hostname or url
                try:
                    async with asyncio.timeout(limit):
                        response = await self._http.post(
                            url, data={"data": query}, timeout=httpx.Timeout(limit, connect=min(CONNECT_S, limit)),
                        )
                    data = _answer_of(response)
                    elements = compact(data["elements"])
                except (httpx.HTTPError, TimeoutError, OsmError, ValueError, KeyError, TypeError, AttributeError) as exc:
                    self._failed[url] = time.monotonic()
                    problems.append(f"{host}: {_describe(exc)}")
                    continue
                self._failed.pop(url, None)
                self.calls += 1
                as_of = (data.get("osm3s") or {}).get("timestamp_osm_base")
                return {"source": host, "as_of": as_of, "elements": elements}
            raise OsmError("; ".join(problems) or "no time left to ask OpenStreetMap")
        finally:
            self._gate.release()

    # ---------- Other queries: the kit's street map (app.basemap) ----------

    async def ask(
        self, query: str, shape: Callable[[dict], dict], *, name: str, timeout: float = TIMEOUT_S,
        budget: float | None = None,
    ) -> dict:
        """Another Overpass query, asked the way the cross-check's is: the same instances in the same order, each resting
        after it fails, two queries at a time at most, and the answer kept on disk for a week, as '{name}-{hash}.json'.
        `shape` turns an Overpass answer into what is kept, raising OsmError when it holds nothing usable, so the next
        instance is asked. Raises OsmError when none answers in `budget` seconds and no older answer is on disk."""
        key = hashlib.sha1(query.encode("utf-8")).hexdigest()
        cache_file = self._cache_dir / f"{name}-{key}.json"
        saved = _saved(cache_file)
        if saved and time.time() - saved[1] < self._max_age_s:
            self.cache_hits += 1
            return saved[0]
        try:
            data = await self._fetch_shaped(query, shape, timeout, self._budget if budget is None else budget)
        except OsmError as exc:
            if not saved:
                raise
            log.warning("OpenStreetMap did not answer (%s); using its answer from %s", exc, time.ctime(saved[1]))
            self.cache_hits += 1
            return saved[0]
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    async def _fetch_shaped(self, query: str, shape: Callable[[dict], dict], timeout: float, budget: float) -> dict:
        deadline = time.monotonic() + budget
        try:
            async with asyncio.timeout(budget):
                await self._gate.acquire()
        except TimeoutError:
            raise OsmError("other queries were asking OpenStreetMap") from None
        try:
            problems = []
            for url in self._order():
                remaining = deadline - time.monotonic()
                if remaining < 1:
                    break
                limit = min(timeout, remaining)
                host = urlsplit(url).hostname or url
                try:
                    async with asyncio.timeout(limit):
                        response = await self._http.post(
                            url, data={"data": query}, timeout=httpx.Timeout(limit, connect=min(CONNECT_S, limit)),
                        )
                    data = _answer_of(response)
                    # Shaping a big area's answer is pure Python and can take seconds: off the event loop, so surveys
                    # keep streaming and health checks keep answering meanwhile.
                    kept = await asyncio.to_thread(shape, data)
                except (httpx.HTTPError, TimeoutError, OsmError, ValueError, KeyError, TypeError, AttributeError) as exc:
                    self._failed[url] = time.monotonic()
                    problems.append(f"{host}: {_describe(exc)}")
                    continue
                self._failed.pop(url, None)
                self.calls += 1
                return {"source": host, "as_of": (data.get("osm3s") or {}).get("timestamp_osm_base"), **kept}
            raise OsmError("; ".join(problems) or "no time left to ask OpenStreetMap")
        finally:
            self._gate.release()
