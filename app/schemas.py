"""Typed shapes of the JSON API, so responses are validated and documented at /docs.

The survey itself streams server-sent events (GET /api/run); their payloads are documented in the README.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Health(BaseModel):
    ok: bool
    qloo: bool = Field(description="A Qloo key is configured (cached responses work without one)")
    llm: bool = Field(description="The agent's language model is configured")
    model: str | None
    models: list[str] = Field(description="The model and its fallbacks, in order")
    resting: dict[str, float] = Field(description="Models resting after rate limits, with seconds left")
    image: bool
    image_model: str | None


class Preset(BaseModel):
    id: str
    label: str
    lat: float
    lon: float
    blurb: str


class Catchment(BaseModel):
    minutes: int
    source: str = Field(description="'isochrone' for a street-network walk, 'circle' when routing is unavailable")
    ring: list[list[float]] = Field(description="The walk's outline as [lat, lon] points")
    area_km2: float
    radius_m: int = Field(description="Radius of a circle with the same area")


class HeatCell(BaseModel):
    lat: float
    lon: float
    geohash: str | None
    affinity: float


class Heatmap(BaseModel):
    cells: list[HeatCell]


class GeocodeHit(BaseModel):
    label: str | None
    lat: float
    lon: float


class PlaceHit(BaseModel):
    id: str
    name: str | None
    address: str | None
    genres: list[str]
    rating: float | None
    lat: float
    lon: float
    distance_m: int


class Render(BaseModel):
    image: str | None = Field(description="A data URL, or null when renders are off")
    model: str | None
    queued: bool = False
    detail: str | None = None


class Shot(BaseModel):
    kind: str
    label: str
    aspect: str
    prompt: str


class OsmPlace(BaseModel):
    """A place of the gap's kind that OpenStreetMap shows inside the walk and Qloo does not list there."""

    name: str
    lat: float
    lon: float
    url: str = Field(description="Its OpenStreetMap page, such as https://www.openstreetmap.org/node/123")
    tag: str | None = Field(None, description="What OpenStreetMap says it is ('shop=bakery')")
    distance_m: int | None = Field(None, description="Straight-line distance from the site")


class OsmCheck(BaseModel):
    """The gap's OpenStreetMap cross-check. Data © OpenStreetMap contributors, under the Open Database License (ODbL)."""

    checked: bool = Field(description="False when OpenStreetMap did not answer or no tag reliably marks this kind of place")
    count: int = Field(description="Places of this kind OpenStreetMap shows inside the walk, Qloo's included")
    extra: list[OsmPlace] = Field(description="The ones Qloo does not list there, nearest first; they count as supply")
    reason: str | None = Field(None, description="Why it was not checked: 'unavailable', 'unmapped' or 'off'")
    note: str | None = Field(None, description="The reason, or why the places are not compared one by one, in words")
    as_of: str | None = Field(None, description="When the OpenStreetMap data the Overpass instance served was updated")
    credit: str | None = Field(None, description="'© OpenStreetMap contributors', to show wherever its places do")


class GapRow(BaseModel):
    """One category of the gap table, as the `gaps` event streams it (also `explored`, and the `row` of a verdict or an
    improvement). Only the main fields are listed; rows carry more evidence."""

    model_config = ConfigDict(extra="allow")

    genre_id: str
    genre: str
    demand_rank: int
    ref_rank: float | None
    nearby_count: int = Field(description="Places of this kind Qloo lists inside the walk")
    nearby_capped: bool = Field(description="Qloo has more inside the walk than it returns")
    expected_nearby: float | None = Field(None, description="What a block this dense usually holds")
    relative_supply: float = Field(description="Supply inside the walk (Qloo's and OpenStreetMap's extras) against density")
    gap_score: int
    evidence: str = Field(description="'ok', 'thin' or 'atypical'")
    reading: str | None = Field(None, description="The row in two or three words: 'Clear gap', 'People here travel for it'")
    why: list[str] = Field(default_factory=list, description="The row in plain sentences, OpenStreetMap's extras included")
    osm: OsmCheck | None = Field(None, description="The OpenStreetMap cross-check; null in surveys saved before it existed")


class LoveItem(BaseModel):
    """One of the two things a wildcard concept combines, and where the evidence that people here love it comes from."""

    item: str = Field(description="What people here love: a kind of place, in plain words ('coffee shops')")
    genre: str = Field(description="Its category in the gap table")
    source: str = Field(description="The Qloo evidence in words: the trips people here make, or how they rank it")


class Concept(BaseModel):
    """A business concept as the `concepts` event streams it (GET /api/run): the ranked concepts, then at most one
    wildcard. The event also carries `mode`, `model`, `caution` and `notes`, the list of what the owner's rules repaired
    or dropped, in plain words."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(description="An original business name, never the category plus the neighborhood")
    genre: str = Field(description="The gap-table category it is built on; for a wildcard, the first of the two it combines")
    genre_id: str | None = None
    gap_score: int | None = Field(None, description="The category's gap score; null for the wildcard, which is never ranked")
    one_liner: str | None = None
    for_whom: str | None = None
    price_level: int | None = Field(None, description="Qloo's 1-4; always 1 ($) when the owner's notes ask for budget prices")
    price_basis: str | None = Field(
        None, description="What the places people here love and the places inside the walk charge, and where a budget "
                          "concept sits against the block ('below the block's usual $$')",
    )
    price_anchors: list[dict] = Field(default_factory=list)
    why_here: list[str] = Field(default_factory=list)
    beat_competitors: str | None = None
    signature: list[str] = Field(default_factory=list, description="What people would come for, within the owner's rules")
    inspired_by: list[str] = Field(default_factory=list)
    risk: str | None = None
    owner_rules: list[str] = Field(
        default_factory=list,
        description="How it meets each rule the owner gave, one line each: the unit ('Fits 45 m² (484 ft²): a counter and "
                    "about 20–24 seats at most.'), the kitchen ('No hood needed: …'), the price ('Budget: $, below the "
                    "block's usual $$.'), the diet and families",
    )
    wildcard: bool = Field(False, description="True for the extra concept after the ranked ones: two loves combined, untested")
    combines: list[LoveItem] | None = Field(None, description="For the wildcard: the two things people here love it combines")
    caution: str | None = Field(None, description="For the wildcard: why it is untested")


class MoodTile(BaseModel):
    """A name on the mood board: an artist, film, show or brand people here over-index on, with Qloo's image of it."""

    name: str
    kind: str = Field(description="'artist', 'film', 'show' or 'brand'")
    image: str = Field(description="Qloo's image (images.qloo.com), credited 'Images: Qloo'")
    year: int | None = Field(None, description="A film's or show's release year")
    since: int | None = Field(None, description="The year an artist started")
    via: str | None = Field(
        None, description="Set only when the area's own names were too few to fill the board: 'fans' for what this "
                          "category's fans also love, 'loved' for what people here rank highest, not more than around",
    )


class MoodSwatch(BaseModel):
    hex: str = Field(description="'#RRGGBB'")
    name: str


class MoodEra(BaseModel):
    """What the years of the names people here over-index on add up to (artists by the year they started, films and
    shows by release)."""

    model_config = ConfigDict(populate_by_name=True)

    label: str | None = Field(description="The decades most of them come from ('1970s–80s'); null when too few have a "
                                          "year (under 5) or no span holds half of them")
    from_: int | None = Field(alias="from", description="The span's first year; null without an era")
    to: int | None = Field(description="The span's last year, this year at most; null without an era")
    classic_share: float | None = Field(description="Share of the names with a year that are 20 or more years old")
    dated: int = Field(description="Names with a year")
    classic: int = Field(description="Of which 20 or more years old")


class MoodDirection(BaseModel):
    """The design the renders follow: the era's row of a rules table, or the design DNA of the places people here love
    when there is no era."""

    name: str = Field(description="'Seventies warmth', or the style the design DNA points to ('Industrial')")
    palette: list[MoodSwatch] = Field(description="Four or five colors")
    materials: list[str]
    lighting: str
    type: str = Field(description="The lettering of the sign and the menus")
    music: str | None = Field(None, description="The era of records to play; null without an era")
    source: str = Field(description="'era'; 'dna' without an era; 'default' when the design DNA has no tags either")
    cues: list[str] = Field(default_factory=list, description="The design DNA tags a 'dna' direction follows")


class Mood(BaseModel):
    """The mood board: the faces, posters and brands people here over-index on, the era they point to and the design
    direction the renders follow. Never names in the renders, and the names are for the mood, not for decor or ads."""

    tiles: list[MoodTile] = Field(description="Six to nine, the kinds taking turns; fewer when Qloo has fewer images")
    era: MoodEra
    direction: MoodDirection
    statement: str = Field(description="One or two sentences on how the room should feel, from the board alone")
    statement_by: str = Field(description="'agent' when the design model wrote it and it kept to the board, else 'rules'")
    basis: str = Field(description="How the era was read, in words, or why there is none")
    source: str = Field(description="Where the tiles come from")
    credit: str = Field(description="'Images: Qloo'")


class DesignSheet(BaseModel):
    """A concept's design sheet. The model writes the creative fields (loosely typed, since a model can return any
    shape and that must not fail the request); everything factual comes from the evidence and is typed."""

    model_config = ConfigDict(extra="allow")

    name: Any = None
    tagline: Any = None
    interior: Any = None
    offer: Any = None
    music: dict
    partners: list[dict]
    price_level: int | None = Field(None, description="Price level the evidence supports, within the owner's range")
    price_basis: str | None = Field(None, description="What the places locals love and the places inside the walk charge")
    price_anchors: list[dict] = Field(
        default_factory=list, description="Real places at this price level, with their menu page or website to check prices"
    )
    hours: str | None = Field(description="Typical hours of the places locals love of this type")
    hours_basis: str | None
    capacity: str | None = Field(description="Most guests the unit holds, from building-code load factors")
    capacity_basis: str | None
    unit: dict | None
    experience: dict | None = Field(description="Soundtrack, screen and talks from the neighborhood's signature taste")
    mood: Mood | None = Field(None, description="The mood board; null in sheets made before it existed")
    launch: dict | None = Field(
        None, description="Who to reach, where, when and what can be said, with platform settings and the proof of each claim"
    )
    dna: dict
    mode: str = Field(description="'agent' when a language model wrote it, 'rules' otherwise")
    model: str | None
    shots: list[Shot]
    renders: dict
