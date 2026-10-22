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
    dna: dict
    mode: str = Field(description="'agent' when a language model wrote it, 'rules' otherwise")
    model: str | None
    shots: list[Shot]
    renders: dict
