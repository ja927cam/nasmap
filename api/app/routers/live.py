"""Live data layers: RainViewer radar, Open-Meteo points and USGS earthquakes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from geoalchemy2.elements import WKTElement
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..auth import EditorUser
from ..config import settings
from ..database import get_db
from ..models import Feature, Layer
from ..permissions import get_layer_or_404, require_write
from ..rate_limit import upload_rate_limit
from ..services import live
from .layers import serialize_layer

router = APIRouter(prefix="/live", tags=["live"])
logger = logging.getLogger("nasmap.live")


class RadarIn(BaseModel):
    name: str = Field(default="", max_length=200)
    visibility: Literal["private", "organisation", "public"] = "private"


class WeatherGridIn(BaseModel):
    bbox: list[float] = Field(min_length=4, max_length=4)
    name: str = Field(default="", max_length=200)
    visibility: Literal["private", "organisation", "public"] = "private"
    layer_id: str | None = None
    grid: int = Field(default=3, ge=2, le=6)


class EarthquakeIn(BaseModel):
    min_magnitude: float = Field(default=2.5, ge=-2, le=10)
    name: str = Field(default="", max_length=200)
    visibility: Literal["private", "organisation", "public"] = "private"
    layer_id: str | None = None


async def _replace_features(db: AsyncSession, layer: Layer, records: list[dict], user_id) -> int:
    await db.execute(delete(Feature).where(Feature.layer_id == layer.id))
    objects = [
        Feature(
            layer_id=layer.id,
            properties=record["properties"],
            geometry=WKTElement(record["geometry"], srid=4326),
            created_by=user_id,
            updated_by=user_id,
        )
        for record in records
        if record.get("geometry")
    ]
    db.add_all(objects)
    await db.flush()
    return len(objects)


def _new_layer(
    user,
    name: str,
    visibility: str,
    style: dict,
    metadata: dict,
    attribution: str,
    licence: str,
    geometry_type: str = "point",
) -> Layer:
    return Layer(
        owner_id=user.id,
        name=name,
        description="Live data layer.",
        visibility=visibility,
        geometry_type=geometry_type,
        source_type="api",
        style=style,
        metadata_=metadata,
        attribution=attribution,
        licence=licence,
    )


@router.get("/sources")
async def live_sources(user: EditorUser):
    return {
        "sources": [
            {
                "id": "rainviewer",
                "label": "Weather radar",
                "kind": "raster",
                "enabled": settings.rainviewer_enabled,
                "attribution": "RainViewer",
            },
            {
                "id": "open-meteo",
                "label": "Weather points",
                "kind": "vector",
                "enabled": True,
                "attribution": "Open-Meteo (CC BY 4.0)",
            },
            {
                "id": "usgs-earthquakes",
                "label": "Earthquakes",
                "kind": "vector",
                "enabled": True,
                "attribution": "USGS Earthquake Hazards Program",
            },
        ]
    }


@router.post("/weather/radar", status_code=201, dependencies=[Depends(upload_rate_limit)])
async def add_radar(
    payload: RadarIn,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not settings.rainviewer_enabled:
        raise HTTPException(status_code=503, detail="RainViewer is disabled")
    name = payload.name.strip() or "Weather radar"
    layer = _new_layer(
        user,
        name,
        payload.visibility,
        {"opacity": 0.75},
        {
            "provider": "rainviewer",
            "rainviewer": {"color": 4, "options": "1_1"},
            "xyz": {
                "tile_size": 256,
                "minzoom": 0,
                "maxzoom": live.RAINVIEWER_MAX_ZOOM,
            },
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "RainViewer",
        "RainViewer public API terms",
        "raster",
    )
    db.add(layer)
    await db.flush()
    audit(db, user, "live.radar", "layer", layer.id, request=request)
    await db.commit()
    await db.refresh(layer)
    return serialize_layer(layer, "owner")


@router.post("/weather/grid", dependencies=[Depends(upload_rate_limit)])
async def weather_grid(
    payload: WeatherGridIn,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    west, south, east, north = payload.bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise HTTPException(status_code=422, detail="bbox must be west,south,east,north")
    try:
        records = await live.fetch_weather_grid((west, south, east, north), payload.grid)
    except live.LiveDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    layer = None
    if payload.layer_id:
        layer = await get_layer_or_404(db, payload.layer_id)
        await require_write(db, layer, user)
        if layer.geometry_type not in {"point", "geometry"}:
            raise HTTPException(status_code=422, detail="Weather can only update a point layer")
    if layer is None:
        name = payload.name.strip() or f"Weather {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"
        layer = _new_layer(
            user,
            name,
            payload.visibility,
            {"color": "#0284c7", "circleRadius": 6},
            {
                "provider": "open-meteo",
                "bbox": payload.bbox,
                "grid": payload.grid,
            },
            "Open-Meteo",
            "CC BY 4.0 (Open-Meteo)",
        )
        db.add(layer)
        await db.flush()
    count = await _replace_features(db, layer, records, user.id)
    layer.metadata_ = {
        **(layer.metadata_ or {}),
        "provider": "open-meteo",
        "bbox": payload.bbox,
        "grid": payload.grid,
        "generated_at": datetime.now(UTC).isoformat(),
        "feature_count": count,
    }
    audit(db, user, "live.weather", "layer", layer.id, {"feature_count": count}, request)
    await db.commit()
    await db.refresh(layer)
    return serialize_layer(layer, "owner")


@router.post("/earthquakes", dependencies=[Depends(upload_rate_limit)])
async def earthquakes(
    payload: EarthquakeIn,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        records = await live.fetch_earthquakes(payload.min_magnitude)
    except live.LiveDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not records:
        raise HTTPException(status_code=404, detail="No earthquakes matched the filters")

    layer = None
    if payload.layer_id:
        layer = await get_layer_or_404(db, payload.layer_id)
        await require_write(db, layer, user)
        if layer.geometry_type not in {"point", "geometry"}:
            raise HTTPException(status_code=422, detail="Earthquakes can only update a point layer")
    if layer is None:
        name = payload.name.strip() or f"Earthquakes M{payload.min_magnitude:g}+ (24h)"
        layer = _new_layer(
            user,
            name,
            payload.visibility,
            {"color": "#dc2626", "circleRadius": 6},
            {
                "provider": "usgs-earthquakes",
                "min_magnitude": payload.min_magnitude,
                "feed_url": settings.usgs_earthquakes_url,
            },
            "USGS Earthquake Hazards Program",
            "Public domain (USGS)",
        )
        db.add(layer)
        await db.flush()
    count = await _replace_features(db, layer, records, user.id)
    layer.metadata_ = {
        **(layer.metadata_ or {}),
        "provider": "usgs-earthquakes",
        "min_magnitude": payload.min_magnitude,
        "generated_at": datetime.now(UTC).isoformat(),
        "feature_count": count,
    }
    audit(db, user, "live.earthquakes", "layer", layer.id, {"feature_count": count}, request)
    await db.commit()
    await db.refresh(layer)
    return serialize_layer(layer, "owner")
