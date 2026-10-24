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


class Preset(BaseModel):
    id: str
    label: str
    lat: float
    lon: float
    blurb: str


class Catchment(BaseModel):
    minutes: int
    source: str = Field(description="'street network' when traced over the streets, 'circle' when routing is unavailable")
    ring: list[list[float]] = Field(description="The area's outline as [lat, lon] points")
    area_km2: float
    radius_m: int = Field(description="Radius of a circle with the same area")
    travel: str = Field("walk", description="'walk', 'drive' or 'distance'")
    km: float | None = Field(None, description="The road distance, for travel 'distance'")
    label: str = Field("", description="The area in a sentence: '10-minute walk', '30-minute drive', '25 km drive'")
    short: str = Field("", description="'10-min walk', '30-min drive', '25 km drive'")


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
    why_here: list[str] = Field(default_factory=list)
    beat_competitors: str | None = None
    signature: list[str] = Field(default_factory=list, description="What people would come for, within the owner's rules")
    inspired_by: list[str] = Field(default_factory=list)
    risk: str | None = None
    owner_rules: list[str] = Field(
        default_factory=list,
        description="How it meets each rule the owner gave, one line each: the unit ('Fits 45 m² (484 ft²): a counter and "
                    "about 20–24 seats at most.'), the kitchen ('No hood needed: …'), the price band ('Budget prices: "
                    "nothing in it is called upscale or premium.'), the diet and families",
    )
    wildcard: bool = Field(False, description="True for the extra concept after the ranked ones: two loves combined, untested")
    combines: list[LoveItem] | None = Field(None, description="For the wildcard: the two things people here love it combines")
    caution: str | None = Field(None, description="For the wildcard: why it is untested")


class DesignSheet(BaseModel):
    """A concept's design sheet, from the evidence: the concept's own name, positioning and signature, what to sell,
    when to open, what the unit holds, the experience and launch plans, and how it meets each of the owner's rules.
    Sheets saved before the cuts may carry more fields (interior, mood, renders); they pass through untyped."""

    model_config = ConfigDict(extra="allow")

    # Loosely typed where a sheet saved before the change (written by a model) may have another shape.
    name: Any = None
    tagline: Any = Field(None, description="The concept's one-liner")
    offer: Any = Field(None, description="The concept's signature, then what the places people here love are known for")
    hours: str | None = Field(None, description="Typical hours of the places locals love of this type")
    hours_basis: str | None = None
    capacity: str | None = Field(None, description="Most guests the unit holds, from building-code load factors")
    capacity_basis: str | None = None
    unit: dict | None = None
    experience: dict | None = Field(None, description="Soundtrack, screen and talks from the neighborhood's signature taste")
    launch: dict | None = Field(
        None, description="Who to reach, where, when and what can be said, with platform settings and the proof of each claim"
    )
    audience: dict | None = Field(
        None, description="Who the places people here love of this kind draw (Qloo audience leans), and the ad setting it implies"
    )
    owner_rules: list[str] = Field(default_factory=list, description="How it meets each rule the owner gave")
    mode: str = Field("rules", description="'rules': every sheet is assembled from the evidence")
    model: str | None = None
