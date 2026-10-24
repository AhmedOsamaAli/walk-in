"""A concept's launch plan: who to reach, where, when, and what can truthfully be said, from the evidence.

Some ad platforms accept Qloo's vocabulary directly: Spotify targets fans of named artists and podcast listeners,
Nextdoor targets neighborhoods, Google's custom segments take websites. So the plan hands the owner settings to paste
rather than a picture: audiences come from what people near the site over-index on, every claim carries the numbers
that prove it today, and no claim names a competitor.
"""
from __future__ import annotations

from collections import Counter
from urllib.parse import urlsplit

from .. import engine, scoring
from ..geo import distance_m
from .evidence import (
    CROWD_SKIP,
    CROWD_TAG,
    TRAVEL,
    example_places,
    offer_items,
    osm_caution,
    osm_extra,
    plural,
    singular,
    storefront_favorites,
    tag_share,
)
from .models import RunState

TIME_TAG = "urn:tag:time_of_day_fit:qloo"
INTENT_TAG = "urn:tag:visit_intent:qloo"
SIGNATURE_KEYS = ("distinctive_artists", "distinctive_podcasts", "distinctive_brands", "distinctive_tv", "distinctive_movies")
# What the ads should lead with, by why people visit the places locals love of this kind (Qloo's visit-intent tags).
INTENT_ANGLE = {
    "Routine visit": "Lead with the habit: a weekday regular's offer or a loyalty card.",
    "Convenience stop": "Lead with speed and distance: how close it is and how quick.",
    "Destination": "Lead with the reason to come: the signature item, said first.",
    "Special occasion": "Lead with the occasion: bookings for birthdays, dates and celebrations.",
    "Impulse visit": "Lead with being seen: the window, the sign and walk-by offers.",
    "Day trip": "Lead with the outing: what to pair the visit with nearby.",
}
# Promises that answer what reviews of the places inside the walk complain about; a promise is a claim too.
PROMISES = {
    "Long waits and lines": "Book ahead, or be served fast at the counter",
    "Crowding": "Room to breathe, even on weekends",
    "Noise": "A room where you can hear each other",
    "Rude staff": "Hospitality first",
    "Slow service": "Fast, every time",
    "Hygiene": "Spotless, from the counter to the restrooms",
    "Small portions": "Portions worth the walk",
    "Uncomfortable seats": "Seats you will want to stay in",
}
NO_COMPETITORS = "Name no competitor in an ad: platforms reject other businesses' names in ad text, and comparisons need proof."
WALK_FIRST = ("Walk the block before launch: the 'only' and 'new' lines are true of the places Qloo knows today, and a "
              "place may have opened since.")
CHECK_FIRST = ("Check the area before launch: the 'only' and 'new' lines are true of the places Qloo knows today, and a "
               "place may have opened since.")
KEEP_PROMISES = "Make the promise only if the service will keep it: a promise in an ad is a claim you must be able to back."
NO_ENDORSEMENT = ("Artists, shows and brands are for targeting, not for the ad itself: using their names or images implies "
                  "an endorsement you do not have.")


def area_word(run: RunState) -> str:
    """The area as the plan's sentences name it: 'the walk' as always, or 'the 30-minute drive', 'the 25 km drive'."""
    return "walk" if run.site.travel == "walk" else run.site.area


def taste_area(run: RunState) -> str:
    """Where the audiences come from, for the plan's words: 'within 1.5 km', farther for a big area."""
    radius = engine.taste_m(run.catchment) if run.catchment else engine.TASTE_M
    return f"within {radius / 1000:g} km" if radius < 10_000 else f"within {round(radius / 1000)} km"


def distance_text(metres: int) -> str:
    return f"{metres} m" if metres < 1000 else f"{metres / 1000:.1f} km".replace(".0 km", " km")


def plan(
    run: RunState, concept: dict, row: dict | None, shared: set[str] = frozenset(), hours: str | None = None,
    people: dict | None = None,
) -> dict:
    """The launch plan for one concept; `shared` holds the signature names this category's fans also love, and
    `people` who the places people here love of this kind draw (audience.audience)."""
    audience = reach(run, row, shared)
    audience["people"] = people
    places = where(run, row)
    said = claims(run, concept, row)
    return {
        "audience": audience,
        "where": places,
        "when": when(row, hours),
        "claims": said,
        "channels": channels(run, audience, places),
        "cautions": cautions(said, audience, run.site.travel),
        "basis": f"Audiences are what people {taste_area(run)} over-index on compared with same-size areas around; the "
                 "crowd, times and reasons to visit are Qloo's tags on the places people here love of this kind"
                 + ("; the ages and gender are Qloo's audience leans for those places." if people else "."),
    }


def reach(run: RunState, row: dict | None, shared: set[str]) -> dict:
    taste = run.taste
    signature = {c.get("name") for key in SIGNATURE_KEYS for c in taste.get(key, []) if c.get("name")}
    both = shared & signature

    def names(key: str, limit: int) -> list[str]:
        cards = sorted(taste.get(key, []), key=lambda c: c.get("name") not in both)
        return [c["name"] for c in cards if c.get("name")][:limit]

    screen = [c["name"] for c in taste.get("distinctive_tv", [])[:3] + taste.get("distinctive_movies", [])[:2] if c.get("name")]
    return {
        "crowd": tag_share(example_places(row), CROWD_TAG, CROWD_SKIP)[:3] if row else [],
        "artists": names("distinctive_artists", 6),
        "podcasts": names("distinctive_podcasts", 4),
        "screen": screen,
        "brands": names("distinctive_brands", 6),
        "shared": sorted(both)[:6],
    }


def walk_reach_m(run: RunState) -> int | None:
    """How far the walk reaches at its farthest point: the radius that covers all of it."""
    catchment = run.catchment
    if not catchment or not catchment.ring:
        return None
    return round(max(distance_m(catchment.lat, catchment.lon, lat, lon) for lon, lat in catchment.ring))


def where(run: RunState, row: dict | None) -> dict:
    hoods = Counter(((p.get("properties") or {}).get("neighborhood") or "").strip() for p in run.block)
    hoods.pop("", None)
    _, cards = storefront_favorites(row) if row else ([], [])
    sites = [{"name": c["name"], "url": c["url"]} for c in cards if c.get("url") and c.get("name") and not c.get("within_walk")]
    return {
        "label": run.site.area,
        "minutes": run.site.minutes,
        "reach_m": walk_reach_m(run),
        "neighborhoods": [name for name, _ in hoods.most_common(4)],
        "sites_like": sites[:5],
    }


def when(row: dict | None, hours: str | None) -> dict:
    places = example_places(row) if row else []
    intents = tag_share(places, INTENT_TAG)[:2]
    return {
        "times": tag_share(places, TIME_TAG)[:3],
        "intents": [{**share, "angle": INTENT_ANGLE.get(share["label"])} for share in intents],
        "hours": hours,
    }


def claims(run: RunState, concept: dict, row: dict | None) -> list[dict]:
    """What the ads can say, each with the evidence that makes it true today."""
    if not row:
        return []
    genre, area, here = row["genre"], run.site.area, area_word(run)
    out = []
    osm = row.get("osm") or {}
    # OpenStreetMap must show none of the kind at all: a place it shows that Qloo lists elsewhere (as another kind, or
    # closed) is still a place of the kind on the street, so no 'only' can be said then.
    if not row.get("nearby_count") and not osm_extra(row) and not osm.get("count"):
        out.append({
            "kind": "only",
            "line": f"The only {singular(genre)} within a {area}",
            "proof": f"Qloo lists no {singular(genre)} inside the {here}" + (
                ", and OpenStreetMap shows none either." if osm.get("checked")
                else f"; OpenStreetMap could not confirm it, so {'walk the block' if here == 'walk' else 'check the area'} before saying it."),
        })
    signature = {str(item).lower() for item in concept.get("signature") or []}
    new_items = [i for i in offer_items(row, run.constraints, limit=8) if i["new_here"] and i["item"].lower() in signature]
    unknown = "what it is known for is" if len(osm_extra(row)) == 1 else "what they are known for is"
    for item in new_items[:2]:
        out.append({
            "kind": "new",
            "line": f"{item['item']}, which no {singular(genre)} within a {area} is known for",
            "proof": f"{item['places']} of the {plural(genre)} locals love {'is' if item['places'] == 1 else 'are'} "
                     f"known for it; none inside the {here} is." + _caution(osm_caution(row, "Reviews are Qloo's", unknown, area)),
        })
    km, far, total = row.get("median_far_km"), row.get("favorites_far", 0), row.get("favorites_total", 0)
    if row.get("favorites_kind") == "local" and (row.get("leakage") or 0) >= TRAVEL and far >= 3:
        out.append({
            "kind": "closer",
            "line": f"{scoring.genre_title(genre)} without {'crossing town' if run.site.travel == 'walk' else 'the long drive'}",
            "proof": f"{far} of the {total} {plural(genre)} people here love more than the city does are outside the "
                     f"{here}{f', a median {km} km away' if km else ''}.",
        })
    themes = Counter(theme for card in row.get("competitors") or [] for theme in card.get("complaints") or [])
    for theme, places in themes.most_common(2):
        promise = PROMISES.get(theme[:1].upper() + theme[1:])
        if promise:
            out.append({
                "kind": "promise",
                "line": promise,
                "proof": f"Reviews of {places} of the {plural(genre)} inside the {here} flag {theme}; keep this promise "
                         f"only if the service delivers it.",
            })
            break
    return out


def _caution(text: str | None) -> str:
    """A claim about the places Qloo lists inside the walk stands; when OpenStreetMap shows others, its proof says so."""
    return f" {text}" if text else ""


def domain(url: str) -> str:
    """'https://www.epicerieaustin.com/' as 'epicerieaustin.com', the form a custom segment takes."""
    return urlsplit(url).netloc.lower().removeprefix("www.") or url


def cautions(said: list[dict], audience: dict, travel: str = "walk") -> list[str]:
    """The checks this plan needs before it runs: only those its claims and audiences call for."""
    kinds = {claim["kind"] for claim in said}
    out = [NO_COMPETITORS]
    if kinds & {"only", "new"}:
        out.append(WALK_FIRST if travel == "walk" else CHECK_FIRST)
    if "promise" in kinds:
        out.append(KEEP_PROMISES)
    if any(audience[key] for key in ("artists", "podcasts", "screen", "brands")):
        out.append(NO_ENDORSEMENT)
    return out


def channels(run: RunState, audience: dict, places: dict) -> list[dict]:
    """Where to set the plan up, with the settings each platform takes, from what the plan found."""
    out = []
    here = area_word(run)
    people = audience.get("people") or {}
    ad = people.get("ad")  # 'Ages 30–44, women': who the places people here love of this kind draw
    artists, podcasts = audience["artists"][:4], audience["podcasts"][:2]
    if artists or podcasts:
        who = []
        if artists:
            who.append(f"fans of {scoring.natural_list(artists)}")
        if podcasts:
            who.append(f"listeners of {scoring.natural_list(podcasts)}")
        out.append({
            "channel": "Spotify Ads",
            "setting": f"Target {' and '.join(who)}, in your city." + (f" {ad}." if ad else ""),
            "why": f"Spotify can target fans of named artists and podcast listeners; these are names people "
                   f"{taste_area(run)} over-index on. It targets by city, not by street, so use it for awareness."
                   + (" The ages and gender are who the places people here love of this kind draw." if ad else ""),
        })
    if places["neighborhoods"]:
        out.append({
            "channel": "Nextdoor",
            "setting": f"Neighborhoods: {', '.join(places['neighborhoods'])}.",
            "why": f"Nextdoor targets by neighborhood; these are the neighborhoods of the places inside your {here}.",
        })
    if places["sites_like"]:
        sites = dict.fromkeys(domain(s["url"]) for s in places["sites_like"])
        out.append({
            "channel": "Google Ads custom segment",
            "setting": "People who browse websites like: " + ", ".join(sites) + ".",
            "why": f"Custom segments take websites; these belong to the places locals love outside your {here}, where "
                   "they go now.",
        })
    if places["reach_m"]:
        reach_text = distance_text(places["reach_m"])
        out.append({
            "channel": "Meta or Google local ads",
            "setting": f"A radius of {reach_text} around your door, or the smallest the platform allows."
                       + (f" {ad}." if ad else ""),
            "why": f"That covers the whole {run.site.area}, which reaches {reach_text} at its farthest point"
                   + ("; most platforms' smallest radius is larger, so expect some wider reach." if places["reach_m"] < 1600
                      else ".")
                   + (" The ages and gender are who the places people here love of this kind draw." if ad else ""),
        })
    return out
