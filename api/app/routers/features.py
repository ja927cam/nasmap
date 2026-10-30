"""Feature CRUD and spatial queries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from geoalchemy2.elements import WKTElement
from pydantic import BaseModel, Field
from shapely import wkt as shapely_wkt
from shapely.geometry import shape as shapely_shape
from shapely.validation import explain_validity
from sqlalchemy import Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..auth import CurrentUser
from ..database import get_db
from ..models import Feature, FeatureVersion, Layer
from ..permissions import get_layer_or_404, require_read, require_write

router = APIRouter(tags=["features"])

GEOMETRY_CLASSES = {
    "point": {"Point", "MultiPoint"},
    "line": {"LineString", "MultiLineString"},
    "polygon": {"Polygon", "MultiPolygon"},
}


class FeatureIn(BaseModel):
    properties: dict[str, Any] = Field(default_factory=dict)
    geometry: dict[str, Any] | str = Field(description="GeoJSON geometry object or WKT")
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class FeaturePatch(BaseModel):
    properties: dict[str, Any] | None = None
    replace_properties: bool = False
    geometry: dict[str, Any] | str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


def parse_geometry(value: dict[str, Any] | str):
    try:
        geom = shapely_wkt.loads(value) if isinstance(value, str) else shapely_shape(value)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid geometry: {exc}") from exc
    if geom.is_empty:
        raise HTTPException(status_code=422, detail="Geometry is empty")
    if not geom.is_valid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid geometry: {explain_validity(geom)}",
        )
    return geom


def check_layer_geometry(layer: Layer, geom) -> None:
    if layer.geometry_type in {"raster", "table"}:
        raise HTTPException(status_code=400, detail="This layer does not store vector features")
    allowed = GEOMETRY_CLASSES.get(layer.geometry_type)
    if allowed and geom.geom_type not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Layer expects {layer.geometry_type} geometry, got {geom.geom_type}",
        )


def to_geojson(row, include_version: bool = True) -> dict[str, Any]:
    feature: Feature = row[0]
    geometry = json.loads(row[1]) if row[1] else None
    result: dict[str, Any] = {
        "type": "Feature",
        "id": str(feature.id),
        "geometry": geometry,
        "properties": feature.properties or {},
    }
    if include_version:
        result["version"] = feature.version
        result["updated_at"] = feature.updated_at.isoformat() if feature.updated_at else None
        result["created_at"] = feature.created_at.isoformat() if feature.created_at else None
        result["valid_from"] = feature.valid_from.isoformat() if feature.valid_from else None
        result["valid_to"] = feature.valid_to.isoformat() if feature.valid_to else None
    return result


@router.get("/layers/{layer_id}/features")
async def list_features(
    layer_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    bbox: str | None = Query(default=None, description="min_lon,min_lat,max_lon,max_lat"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=2000, ge=1, le=20000),
    offset: int = Query(default=0, ge=0),
    include_geometry: bool = True,
):
    layer = await get_layer_or_404(db, layer_id)
    await require_read(db, layer, user)
    if layer.geometry_type in {"raster", "table"}:
        return {"type": "FeatureCollection", "features": [], "meta": {"total": 0}}

    conditions = [Feature.layer_id == layer.id, Feature.deleted_at.is_(None)]
    if bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = [float(v) for v in bbox.split(",")]
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="bbox must be min_lon,min_lat,max_lon,max_lat"
            ) from exc
        if not (-180 <= min_lon <= max_lon <= 180 and -90 <= min_lat <= max_lat <= 90):
            raise HTTPException(
                status_code=422, detail="bbox is outside valid longitude/latitude ranges"
            )
        envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
        conditions.append(func.ST_Intersects(Feature.geometry, envelope))
    if q:
        conditions.append(func.cast(Feature.properties, Text).ilike(f"%{q}%"))

    where = conditions[0]
    for condition in conditions[1:]:
        where = where & condition

    total = int(await db.scalar(select(func.count()).select_from(Feature).where(where)) or 0)
    selected_geometry = func.ST_AsGeoJSON(Feature.geometry) if include_geometry else None
    rows = (
        await db.execute(
            select(Feature, selected_geometry)
            .where(where)
            .order_by(Feature.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return {
        "type": "FeatureCollection",
        "features": [to_geojson(row) for row in rows],
        "meta": {"total": total, "limit": limit, "offset": offset, "returned": len(rows)},
    }


@router.post("/layers/{layer_id}/features", status_code=201)
async def create_feature(
    layer_id: str,
    payload: FeatureIn,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    layer = await get_layer_or_404(db, layer_id)
    await require_write(db, layer, user)
    geom = parse_geometry(payload.geometry)
    check_layer_geometry(layer, geom)
    feature = Feature(
        layer_id=layer.id,
        properties=payload.properties,
        geometry=WKTElement(geom.wkt, srid=4326),
        created_by=user.id,
        updated_by=user.id,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    db.add(feature)
    await db.flush()
    audit(db, user, "feature.create", "feature", feature.id, {"layer_id": str(layer.id)}, request)
    await db.commit()
    await db.refresh(feature)
    geometry = await db.scalar(select(func.ST_AsGeoJSON(feature.geometry)))
    return to_geojson((feature, geometry))


@router.get("/features/{feature_id}")
async def get_feature(
    feature_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    feature = await db.get(Feature, feature_id)
    if not feature or feature.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Feature not found")
    layer = await get_layer_or_404(db, feature.layer_id)
    await require_read(db, layer, user)
    geometry = await db.scalar(select(func.ST_AsGeoJSON(feature.geometry)))
    return to_geojson((feature, geometry))


@router.patch("/features/{feature_id}")
async def update_feature(
    feature_id: str,
    payload: FeaturePatch,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    feature = await db.get(Feature, feature_id)
    if not feature or feature.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Feature not found")
    layer = await get_layer_or_404(db, feature.layer_id)
    await require_write(db, layer, user)

    if payload.geometry is not None:
        geom = parse_geometry(payload.geometry)
        check_layer_geometry(layer, geom)
        feature.geometry = WKTElement(geom.wkt, srid=4326)
    if payload.properties is not None:
        if payload.replace_properties:
            feature.properties = payload.properties
        else:
            feature.properties = {**(feature.properties or {}), **payload.properties}
    if payload.valid_from is not None:
        feature.valid_from = payload.valid_from
    if payload.valid_to is not None:
        feature.valid_to = payload.valid_to
    feature.updated_by = user.id
    audit(db, user, "feature.update", "feature", feature.id, {"layer_id": str(layer.id)}, request)
    await db.commit()
    await db.refresh(feature)
    geometry = await db.scalar(select(func.ST_AsGeoJSON(feature.geometry)))
    return to_geojson((feature, geometry))


@router.delete("/features/{feature_id}")
async def delete_feature(
    feature_id: str,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    feature = await db.get(Feature, feature_id)
    if not feature or feature.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Feature not found")
    layer = await get_layer_or_404(db, feature.layer_id)
    await require_write(db, layer, user)
    feature.deleted_at = datetime.now(UTC)
    feature.updated_by = user.id
    audit(db, user, "feature.delete", "feature", feature.id, {"layer_id": str(layer.id)}, request)
    await db.commit()
    return {"ok": True}


@router.get("/features/{feature_id}/versions")
async def feature_versions(
    feature_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    feature = await db.get(Feature, feature_id)
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")
    layer = await get_layer_or_404(db, feature.layer_id)
    await require_read(db, layer, user)
    rows = (
        await db.execute(
            select(FeatureVersion, func.ST_AsGeoJSON(FeatureVersion.geometry))
            .where(FeatureVersion.feature_id == feature.id)
            .order_by(FeatureVersion.version.desc())
        )
    ).all()
    return [
        {
            "version": version.version,
            "change_type": version.change_type,
            "properties": version.properties,
            "geometry": json.loads(geom) if geom else None,
            "changed_by": str(version.changed_by) if version.changed_by else None,
            "created_at": version.created_at,
        }
        for version, geom in rows
    ]
