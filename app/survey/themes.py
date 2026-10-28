"""Themes a storefront can be built around: what people here watch, hear, follow and wear (Qloo's taste across films,
shows, podcasts, artists and brands), read for the themed wild card (concepts.themed_wildcard).

Only the area's distinctive taste counts: titles and brands people here rank much higher than same-size areas around
do (scoring.distinctive_by_rank). The popular lists are popular everywhere, so they say nothing about this area. Each
distinctive card carries its Qloo genres (engine.TASTE_GENRES), and a card counts for the theme its genres name most:
a pop star Qloo also tags 'Hip - Hop' once stays pop. Genres found on half the titles anywhere (drama, crime, comedy on
screen) name no theme. Faith, politics and news, sexuality, mental health, gambling and identity are never themes, and
a card tagged with them never counts, so a theme says what people here watch, hear and follow, never who they are.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass

from .. import engine, scoring
from ..demographics import BANDS
from ..qloo import QlooClient
from .audience import MAX_PLACES, MIN_PLACES, demographic_rows, read
from .constraints import Constraints
from .models import RunState

log = logging.getLogger("walkin")


@dataclass(frozen=True)
class Theme:
    key: str
    label: str  # in the plain words people share: 'reality TV'
    match: dict[str, re.Pattern]  # taste domain -> the genre names that count for the theme
    kinds: tuple[str, ...]  # the kinds of place it suits, best first (concepts.place_kind)
    activity: str  # what the place hosts, naming no title: 'reality-TV watch parties'
    program: tuple[tuple[str, str], ...]  # (domain, a line naming titles of that domain: 'Watch parties for {}')
    known_for: re.Pattern  # what a place already doing it is known for
    name_words: tuple[str, ...]  # for the name on the sign: 'Cliffhanger Wine Room'
    needs: str | None = None  # a domain the evidence must include: a 'TV & Film' podcast alone may be about films
    nightlife: bool = False  # only works as nightlife, so never for a family-friendly owner


def matching(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


SPORTS_ON_SCREEN = matching(r"\bsports?\b|wrestling|boxing|football|soccer|basketball|baseball")
MYSTERY_ON_SCREEN = matching(r"true crime|whodun+it|murder mystery|\bmystery\b|detective")
SCI_FI = matching(r"sci-? ?fi|science fiction|fantasy|superhero|space opera|dystopian|comic book")
FOOD_ON_SCREEN = matching(r"culinary|cooking|baking|\bfood\b|\bchef")
OUTDOORS_ON_SCREEN = matching(r"\bnature\b|wildlife|survival|mountaineering|climbing")
FAMILY_ON_SCREEN = matching(r"^family$|family (comedy|adventure|animation|film|friendly)|\bkids\b|children|preschool")
THEMES = (
    Theme(
        "reality_tv", "reality TV",
        {"tv": matching(r"\breality\b|dating show"), "podcasts": matching(r"^(tv & film|after shows|tv reviews)$")},
        ("bar", "cafe", "food"), "reality-TV watch parties",
        (("tv", "Watch parties for {}"), ("podcasts", "Recap nights on {}"), ("tv", "Finale nights for {}")),
        matching(r"reality (tv|shows?)"),
        ("Cliffhanger", "Plot Twist", "Season Finale", "Confessional"), needs="tv",
    ),
    Theme(
        "sports", "sports",
        {
            "brands": matching(r"sports organization|professional sports|leagues? & tournaments|soccer|\bfootball\b|"
                               r"basketball|baseball|hockey|\bnba\b|\bnfl\b|national (football|basketball|hockey) league|"
                               r"major league|rugby|cricket|sports (app|news|broadcasting)"),
            "tv": SPORTS_ON_SCREEN, "movies": SPORTS_ON_SCREEN,
            "podcasts": matching(r"^(sports|football|basketball|baseball|hockey|soccer|wrestling|golf|sports news)$"),
        },
        ("bar", "venue", "food", "cafe"), "game-day screenings",
        (("brands", "Game-day screenings for {} fans"), ("tv", "Watch parties for {}"),
         ("podcasts", "Live listening parties for {}"), ("movies", "Sports movie nights: {}")),
        matching(r"sports? ?(bar|pub|viewing|watching|screens?|spectating|broadcasts?|televisions?|focused|centric|themed)|"
                 r"watching (live )?sports|live sports|game day"),
        ("Halftime", "Home Team", "Overtime", "Kickoff"),
    ),
    Theme(
        "true_crime", "true crime and mysteries",
        {"tv": MYSTERY_ON_SCREEN, "movies": MYSTERY_ON_SCREEN, "podcasts": matching(r"^true crime$")},
        ("bar", "cafe", "venue"), "true-crime and mystery nights",
        (("podcasts", "A true-crime listening club: {}"), ("tv", "Whodunit screenings: {}"),
         ("movies", "Mystery movie nights: {}")),
        matching(r"murder myster|mystery (dinner|night)|escape room|true crime|whodun+it"),
        ("Red Herring", "Alibi", "Cold Case", "Second Look"),
    ),
    Theme(
        "comedy", "comedy",
        {
            "podcasts": matching(r"^(comedy|comedy interviews|stand ?-?up|improv)$"),
            "tv": matching(r"sketch|stand ?-?up|talk show|\bvariety\b|improv"),
            "movies": matching(r"stand ?-?up|sketch"),
            "artists": matching(r"comedy|stand-?up"),
        },
        ("venue", "bar", "cafe"), "stand-up comedy nights",
        (("podcasts", "Stand-up nights for fans of {}"), ("tv", "Sketch-comedy screenings: {}"),
         ("artists", "Comedy sets for fans of {}"), ("podcasts", "Live comedy panels for fans of {}")),
        matching(r"comedy|stand ?-?up|open mic|improv"),
        ("Punchline", "Callback", "Tight Five", "Heckler"),
    ),
    Theme(
        "hip_hop", "hip-hop",
        {"artists": matching(r"\brap\b|hip ?-? ?hop|\bdrill\b|\bgrime\b|boom bap|gangsta")},
        ("bar", "venue", "cafe", "retail"), "hip-hop listening nights",
        (("artists", "Album listening nights: {}"), ("artists", "DJ sets built on {}"),
         ("artists", "Open-mic cyphers for fans of {}")),
        matching(r"hip ?-?hop"),
        ("Cypher", "Breakbeat", "Mixtape", "Crate Dig"),
    ),
    Theme(
        "pop_karaoke", "pop and karaoke",
        {"artists": matching(r"\bpop\b|electropop"), "tv": matching(r"\bmusical\b|singing"),
         "movies": matching(r"\bmusical\b")},
        ("venue", "bar", "cafe"), "karaoke nights",
        (("artists", "Karaoke nights: {}"), ("movies", "Sing-along screenings: {}"),
         ("tv", "Sing-along watch parties: {}"), ("artists", "Pop listening parties: {}")),
        matching(r"karaoke|sing-?along"),
        ("Encore", "Chorus", "Mic Drop", "Duet"), needs="artists",
    ),
    Theme(
        "country", "country music",
        {"artists": matching(r"country|americana|bluegrass|honky ?tonk|red dirt|outlaw"),
         "tv": matching(r"\bwestern\b"), "movies": matching(r"\bwestern\b")},
        ("bar", "venue", "food"), "line-dancing nights",
        (("artists", "Line-dancing nights to {}"), ("artists", "Two-step lessons to {}"),
         ("tv", "Watch parties for {}"), ("movies", "Western movie nights: {}")),
        matching(r"line danc|country (music|western|bar|danc)|honky ?tonk|two-?step|dance hall"),
        ("Two Step", "Boot Scoot", "Jukebox", "Back Porch"), needs="artists",
    ),
    Theme(
        "latin", "Latin music and dance",
        {"artists": matching(r"\blatin\b|reggaeton|regional mexican|mariachi|banda|norte[ñn]o|cumbia|bachata|salsa|"
                             r"merengue|tejano|dembow")},
        ("bar", "venue", "food"), "Latin dance nights",
        (("artists", "Latin dance nights to {}"), ("artists", "Dance lessons to {}")),
        matching(r"salsa (danc|class|night)|reggaeton|bachata|latin (music|danc|night)|merengue|cumbia"),
        ("Ritmo", "Clave", "Sabor", "Conga"),
    ),
    Theme(
        "soul_rnb", "soul and R&B",
        {"artists": matching(r"\bsoul\b|r ?& ?b|rhythm (&|and) blues|\brnb\b|jazz|\bfunk\b|\bblues\b|motown")},
        ("bar", "cafe", "venue"), "soul and R&B listening nights",
        (("artists", "Listening nights: {}"), ("artists", "Slow-jam DJ sets of {}")),
        matching(r"soul (music|nights?|bar)|neo-?soul|\br ?& ?b\b|rhythm (and|&) blues|slow jams?"),
        ("Slow Jam", "Groove", "Velvet", "Late Set"),
    ),
    Theme(
        "indie_vinyl", "indie music and vinyl",
        {"artists": matching(r"\bindie\b|alternative rock|alt-?rock|\bfolk\b|singer.{0,3}songwriter|shoegaze|dream pop|"
                             r"post-punk|garage rock|lo-?fi|psychedelic|art pop")},
        ("cafe", "bar", "retail"), "vinyl listening sessions",
        (("artists", "Vinyl listening sessions: {}"), ("artists", "Acoustic nights for fans of {}")),
        matching(r"vinyl|record (store|shop|bar|lounge)|listening (room|bar|session)"),
        ("B-Side", "Deep Cut", "Needle Drop", "Side A"),
    ),
    Theme(
        "electronic", "electronic music",
        {"artists": matching(r"electronic|electronica|\bhouse\b|techno|\bedm\b|trance|dubstep|drum (and|&|n) bass|"
                             r"\bdisco\b|uk garage|synth")},
        ("bar", "venue"), "DJ nights",
        (("artists", "DJ nights built on {}"), ("artists", "Listening sessions: {}")),
        matching(r"\bdj\b|dance ?(club|floor|part(y|ies))|night ?club|electronic|techno|house music|rave"),
        ("Afterglow", "Low End", "Bassline", "Strobe"), nightlife=True,
    ),
    Theme(
        "kpop_anime", "K-pop and anime",
        {"artists": matching(r"k-? ?pop|j-? ?pop|j-? ?rock|city pop|\bidol\b|anime"),
         "tv": matching(r"\banime\b|manga|k-?drama|korean drama"), "movies": matching(r"\banime\b|manga")},
        ("cafe", "retail", "food"), "K-pop and anime nights",
        (("artists", "Dance-cover nights to {}"), ("tv", "Anime screenings: {}"), ("movies", "Anime movie nights: {}"),
         ("artists", "Listening parties: {}")),
        matching(r"anime|manga|k-?pop|cosplay"),
        ("Fan Club", "Lightstick", "Pixel", "Encore"),
    ),
    Theme(
        "scifi_fantasy", "sci-fi and fantasy",
        {"tv": SCI_FI, "movies": SCI_FI},
        ("cafe", "bar", "retail"), "board-game and fandom nights",
        (("tv", "Watch parties for {}"), ("movies", "Fandom movie nights: {}"),
         ("tv", "Board-game nights for fans of {}"), ("movies", "Board-game nights for fans of {}")),
        matching(r"board ?games?|game (cafe|café|night|library)|tabletop|comic (book )?(store|shop)|cosplay"),
        ("Side Quest", "Critical Hit", "Wormhole", "Starship"),
    ),
    Theme(
        "food_tv", "food TV",
        {"tv": FOOD_ON_SCREEN, "movies": FOOD_ON_SCREEN, "podcasts": matching(r"^food$")},
        ("food", "cafe"), "cook-along nights",
        (("tv", "Cook-along nights with {}"), ("podcasts", "Tasting nights inspired by {}"),
         ("movies", "Dinner-and-a-movie nights: {}")),
        matching(r"cooking (class|school|lesson)|cook-?along|culinary (class|school|studio)"),
        ("Test Kitchen", "Taste Test", "Second Helping", "Mise"),
    ),
    Theme(
        "fitness", "fitness and running",
        {"brands": matching(r"health & wellness|sports & fitness|athleisure|fitness|yoga|\bathletic\b|running|activewear"),
         "podcasts": matching(r"^(health & fitness|nutrition|fitness)$")},
        ("cafe", "wellness", "food"), "run-club mornings",
        (("brands", "Run-club mornings for the {} crowd"), ("podcasts", "Wellness talks inspired by {}"),
         ("brands", "Post-run stretch sessions for the {} crowd")),
        matching(r"run(ning)? (club|group)|group runs?"),
        ("Mile One", "First Mile", "Stride", "Pace"),
    ),
    Theme(
        "outdoors", "the outdoors",
        {"brands": matching(r"outdoor|camping|hiking|climbing|cycling|\bbikes?\b|\bski|\bsurf"),
         "tv": OUTDOORS_ON_SCREEN, "movies": OUTDOORS_ON_SCREEN, "podcasts": matching(r"^(places & travel|outdoors)$")},
        ("cafe", "bar", "retail"), "group hikes and trail runs",
        (("brands", "Group hikes and trail runs for the {} crowd"), ("tv", "Nature-film nights: {}"),
         ("movies", "Adventure-film nights: {}"), ("podcasts", "Trip-planning nights with {}"),
         ("brands", "Gear-swap mornings for the {} crowd")),
        matching(r"outdoor (gear|sports|equipment|outfitter)|climbing|hiking|trail run|camping|outfitter"),
        ("Trailhead", "Basecamp", "Switchback", "Summit"),
    ),
    Theme(
        "family", "family entertainment",
        {"tv": FAMILY_ON_SCREEN, "movies": FAMILY_ON_SCREEN, "podcasts": matching(r"kids & family|parenting")},
        ("cafe", "food", "retail"), "family movie mornings",
        (("movies", "Family movie mornings: {}"), ("tv", "Kids' screenings: {}"),
         ("podcasts", "Parents' meetups for fans of {}")),
        matching(r"play ?(area|ground|space|room|cafe)|kids'? (club|area|zone|corner|play)|children'?s (area|play)|"
                 r"family entertainment"),
        ("Storytime", "Treehouse", "Playdate", "Little Wonders"),
    ),
)
# Subjects no theme is built on, and no card tagged with them counts: faith, politics and news, sexuality, mental
# health, gambling, drugs and identity are no one's business to infer from what people watch.
SENSITIVE = matching(
    r"relig|spiritual|christian|gospel|worship|praise|church|faith|bible|\blds\b|islam|muslim|jewish|judaism|hindu|"
    r"buddhis|politic|government|\bnews\b|election|advocacy|activis|sexuality|\bsex\b|erotic|porn|mental health|"
    r"betting|gambl|casino|poker|cannabis|marijuana|lgbt|queer|\bgay\b|lesbian|transgender|\bdrag\b"
)
# A theme stands on several titles, not on one fan base: three cards from two domains (shows and their podcasts), or
# four from one.
MIN_CARDS, MIN_DOMAINS, MIN_IN_ONE_DOMAIN = 3, 2, 4
MAX_LINES = 3  # what a card shows of the program
# A program line names two titles while it stays this short, else one: Qloo's podcast names run long.
LINE_CHARS = 100
MAX_BUILT_ON = 6  # enough titles to show the theme is the area's, few enough to show them all
# The tags that say what a place is and does (its category, activities, amenities, offerings, decor, ambience and
# setting), as against who goes there.
PLACE_TAGS = (
    "urn:tag:genre:place", "urn:tag:category", "urn:tag:activity_type", "urn:tag:amenity", "urn:tag:offerings",
    "urn:tag:ambience", "urn:tag:decor", "urn:tag:setting",
)
GENDERS = {"women": "female", "men": "male"}
DRAWS_BASIS = "How fans of these titles lean by age and gender against everyone (Qloo): leans, not head counts."


def counts_for(card: dict, domain: str) -> list[Theme]:
    """The themes a card counts for: those its genres name most; none when they name none."""
    genres = [name for name in card.get("genres") or [] if isinstance(name, str)]
    hits = {theme.key: sum(1 for name in genres if domain in theme.match and theme.match[domain].search(name))
            for theme in THEMES}
    best = max(hits.values())
    return [theme for theme in THEMES if best and hits[theme.key] == best]


def sensitive(card: dict) -> bool:
    return any(SENSITIVE.search(text) for text in [card.get("name") or "", *(card.get("genres") or [])])


def qualifies(theme: Theme, evidence: list[tuple[str, dict]]) -> bool:
    per_domain = Counter(domain for domain, _ in evidence)
    if theme.needs and theme.needs not in per_domain:
        return False
    return (len(evidence) >= MIN_CARDS and len(per_domain) >= MIN_DOMAINS
            or max(per_domain.values(), default=0) >= MIN_IN_ONE_DOMAIN)


def found(taste: dict, rules: Constraints | None = None) -> list[tuple[Theme, list[tuple[str, dict]]]]:
    """The themes the area's distinctive taste qualifies, strongest first (more cards, then more domains; ties go to the
    theme listed first), each with its evidence as (domain, card) pairs, the most distinctive first within a domain.

    Cards saved before they carried genres name no theme, and a card never counts when it is tagged with a sensitive
    subject or its name breaks the owner's rules ('Bachelor Happy Hour' for an owner who serves no alcohol)."""
    evidence: dict[str, list[tuple[str, dict]]] = {theme.key: [] for theme in THEMES}
    for domain in engine.TASTE_DOMAINS:
        for card in taste.get(f"distinctive_{domain}") or []:
            if not card.get("id") or not card.get("name") or sensitive(card) or rules and rules.item_problem(card["name"]):
                continue
            for theme in counts_for(card, domain):
                evidence[theme.key].append((domain, card))
    qualified = [(theme, evidence[theme.key]) for theme in THEMES if qualifies(theme, evidence[theme.key])]
    return sorted(qualified, key=lambda pair: (-len(pair[1]), -len({domain for domain, _ in pair[1]})))


def known_inside(run: RunState, theme: Theme) -> str | None:
    """The place inside the area already known for the theme, by its name or by what Qloo's tags say it is and does
    ('Karaoke bar', 'Sports viewing', 'Dj booth'); None when no place Qloo lists there is."""
    rows = run.gaps + run.explored
    for place in [*run.block, *(place for row in rows for place in row.get("_nearby_entities") or [])]:
        tags = [tag.get("name") or "" for tag in place.get("tags") or [] if (tag.get("type") or "").startswith(PLACE_TAGS)]
        if any(theme.known_for.search(text) for text in [place.get("name") or "", *tags]):
            return place.get("name") or "A place"
    return None


def program(theme: Theme, evidence: list[tuple[str, dict]]) -> tuple[list[str], list[tuple[str, dict]]]:
    """What happens there: the theme's lines in order, each naming the next titles of its domain no line has named yet
    (a line whose domain has none left is skipped); and the (domain, card) pairs the lines name."""
    left = {domain: [card for kind, card in evidence if kind == domain] for domain in engine.TASTE_DOMAINS}
    lines: list[str] = []
    named: list[tuple[str, dict]] = []
    for domain, line in theme.program:
        if len(lines) == MAX_LINES or not left.get(domain):
            continue
        cards = left[domain][:2]
        text = line.format(scoring.natural_list([card["name"] for card in cards]))
        if len(text) > LINE_CHARS and len(cards) == 2:
            cards = cards[:1]
            text = line.format(cards[0]["name"])
        left[domain] = left[domain][len(cards):]
        lines.append(text)
        named += [(domain, card) for card in cards]
    return lines, named


def built_on(evidence: list[tuple[str, dict]], named: list[tuple[str, dict]]) -> list[dict]:
    """The titles and brands a theme stands on, those its program names first: three to six of them."""
    ordered = named + [pair for pair in evidence if pair not in named]
    return [
        {"domain": domain, "id": card["id"], "name": card["name"], **({"image": card["image"]} if card.get("image") else {})}
        for domain, card in ordered[:MAX_BUILT_ON]
    ]


async def draws(q: QlooClient, theme: dict) -> dict | None:
    """Who the fans of the titles a theme stands on lean toward: Qloo's audience data for those titles, read as the
    design sheet reads the places people here love (audience.read), as the age bands and the gender that lean clearly.
    None when nothing leans clearly, too few titles have data, or Qloo fails."""
    ids = [card["id"] for card in theme.get("built_on") or [] if card.get("id")][:MAX_PLACES]
    if len(ids) < MIN_PLACES:
        return None
    try:
        data = await q.insights({"filter.type": "urn:demographics", "signal.interests.entities": ",".join(ids)})
        leans = read(demographic_rows(data), [], theme["label"])
    except Exception:  # who it draws is a nicety: a failed or surprising answer goes without it, never the survey
        log.warning("Audience lookup for the themed wild card failed; it goes without who it draws", exc_info=True)
        return None
    if not leans or not (leans["ages"] or leans["gender"]):
        return None
    ages = [label for _, label, low, high in BANDS if leans["age_min"] <= low and high <= leans["age_max"]] \
        if leans["ages"] else []
    return {"ages": ages, "gender": GENDERS.get(leans["gender"]), "basis": DRAWS_BASIS}
