"""The map's lookups: the area people can reach from a point (GET /api/catchment), where a kind of place is loved
(GET /api/heatmap), the owner's own place on Qloo (GET /api/places) and addresses both ways through Nominatim
(GET /api/geocode, GET /api/reverse). Each is rate limited per client."""
from __future__ import annotations

from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from .. import engine, schemas, scoring
from ..catchment import make_reach
from ..geocode import Abandoned
from ..qloo import QlooError
from ..ratelimit import client_ip

router = APIRouter(prefix="/api")


@router.get("/catchment", response_model=schemas.Catchment)
async def catchment(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    minutes: int = Query(10),
    travel: Literal["walk", "drive", "distance"] = Query("walk"),
    km: float | None = Query(None),
) -> dict:
    try:
        reach = make_reach(travel, minutes, km)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not request.app.state.map_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many map requests. Try again later.")
    walk = await request.app.state.services.walker.area(lat, lon, reach)
    return walk.public()


@router.get("/heatmap", response_model=schemas.Heatmap)
async def heatmap(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    tag: str = Query(..., min_length=10, max_length=120, pattern=r"^urn:tag:[a-z0-9_:]+$"),
) -> dict:
    if not request.app.state.map_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many map requests. Try again later.")
    try:
        return {"cells": await engine.genre_heatmap(request.app.state.services.qloo, lat, lon, tag)}
    except QlooError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/places", response_model=list[schemas.PlaceHit])
async def places(
    request: Request,
    q: str = Query(..., min_length=2, max_length=80),
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> list[dict]:
    """The owner's place: Qloo places matching a name within about 3 km, nearest first."""
    if not request.app.state.map_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many searches. Try again later.")
    try:
        found = await engine.search_places(request.app.state.services.qloo, q, lat, lon)
    except QlooError as exc:
        raise HTTPException(502, str(exc)) from exc
    cards, seen = [], set()
    for entity in found:
        card = scoring.place_card(entity, (lat, lon))
        key = (card["name"], card["address"])
        if card["lat"] is None or key in seen:
            continue
        seen.add(key)
        cards.append({k: card[k] for k in ("id", "name", "address", "genres", "rating", "lat", "lon", "distance_m")})
    return sorted(cards, key=lambda c: c["distance_m"])


@router.get("/geocode", response_model=list[schemas.GeocodeHit])
async def geocode(request: Request, q: str = Query(..., min_length=3, max_length=160)) -> list[dict]:
    try:
        return await request.app.state.services.geocoder.search(q)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Address search is unavailable right now.") from exc


@router.get("/reverse", response_model=schemas.ReverseHit, responses={404: {"description": "No address at this point"}})
async def reverse(
    request: Request, lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
) -> dict:
    """The address of a pin dropped on the map. Lookups share Nominatim's one request a second with address search, so
    one whose browser has gone (the pin moved on) gives up its turn."""
    if not request.app.state.map_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many map requests. Try again later.")

    async def wanted() -> bool:
        return not await request.is_disconnected()

    try:
        found = await request.app.state.services.geocoder.reverse(lat, lon, wanted=wanted)
    except Abandoned as exc:
        raise HTTPException(408, "The lookup was called off.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Address lookup is unavailable right now.") from exc
    if found is None:
        raise HTTPException(404, "No address at this point.")
    return found
