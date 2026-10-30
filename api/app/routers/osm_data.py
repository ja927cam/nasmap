"""Import current OpenStreetMap data as editable local layers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..auth import EditorUser
from ..config import settings
from ..database import get_db
from ..models import ImportJob
from ..permissions import get_layer_or_404, require_write
from ..rate_limit import upload_rate_limit
from ..services import overpass
from ..workers.queue import enqueue_import
from .imports import serialize_job

router = APIRouter(prefix="/osm", tags=["osm-data"])
logger = logging.getLogger("nasmap.osm.data")

OsmCategory = Literal[
    "buildings",
    "landuse",
    "roads",
    "waterways",
    "natural",
    "amenities",
    "leisure",
    "boundaries",
]


class OSMImportIn(BaseModel):
    bbox: list[float] = Field(
        min_length=4,
        max_length=4,
        description="west,south,east,north in EPSG:4326",
    )
    category: OsmCategory
    name: str = Field(default="", max_length=200)
    layer_id: str | None = None
    visibility: Literal["private", "organisation", "public"] = "private"


def _validate_bbox(value: list[float]) -> tuple[float, float, float, float]:
    west, south, east, north = value
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise HTTPException(status_code=422, detail="bbox must be west,south,east,north")
    area = (east - west) * (north - south)
    if area > settings.overpass_max_area_deg2:
        raise HTTPException(
            status_code=422,
            detail=(
                "Selected area is too large for an OSM import "
                f"({area:.3f} square degrees; limit {settings.overpass_max_area_deg2})."
            ),
        )
    return west, south, east, north


@router.get("/data/categories")
async def categories(user: EditorUser):
    return {
        "enabled": settings.overpass_enabled,
        "categories": [
            {"id": key, "label": key.replace("_", " ").title()} for key in overpass.CATEGORIES
        ],
        "max_area_deg2": settings.overpass_max_area_deg2,
        "overpass_url": settings.overpass_url,
    }


@router.post("/import", status_code=202, dependencies=[Depends(upload_rate_limit)])
async def import_osm(
    payload: OSMImportIn,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not settings.overpass_enabled:
        raise HTTPException(status_code=503, detail="OSM data import is disabled")
    bbox = _validate_bbox(payload.bbox)
    layer = None
    if payload.layer_id:
        layer = await get_layer_or_404(db, payload.layer_id)
        await require_write(db, layer, user)
        if layer.geometry_type not in {"point", "line", "polygon", "geometry"}:
            raise HTTPException(
                status_code=422,
                detail="OSM data can only be appended to a vector layer",
            )
    default_name = (
        f"OSM {payload.category.replace('_', ' ')} {datetime.now(UTC).strftime('%Y-%m-%d')}"
    )
    job = ImportJob(
        user_id=user.id,
        layer_id=layer.id if layer else None,
        job_type="osm",
        status="queued",
        source_url=settings.overpass_url,
        options={
            "bbox": list(bbox),
            "category": payload.category,
            "name": payload.name.strip() or default_name,
            "layer_id": str(layer.id) if layer else None,
            "visibility": payload.visibility,
            "overpass_query": overpass.build_query(bbox, payload.category),
        },
    )
    db.add(job)
    await db.flush()
    audit(
        db,
        user,
        "osm.import",
        "import_job",
        job.id,
        {
            "category": payload.category,
            "bbox": list(bbox),
            "layer_id": str(layer.id) if layer else None,
        },
        request,
    )
    await db.commit()
    try:
        enqueue_import(str(job.id))
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = "Could not enqueue job (is Redis running?)"
        await db.commit()
        raise HTTPException(status_code=503, detail="Import queue unavailable") from exc
    await db.refresh(job)
    return serialize_job(job)
