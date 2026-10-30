"""Tessera / GeoTessera coverage, import and GIS export endpoints."""

from __future__ import annotations

import asyncio
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from ..audit import audit
from ..auth import CurrentUser, EditorUser
from ..config import settings
from ..database import get_db
from ..models import ImportJob, TesseraDataset
from ..services import tessera as tessera_service
from ..workers.queue import enqueue_import
from .imports import get_job_for_user, serialize_job

router = APIRouter(prefix="/tessera", tags=["tessera"])


class CoverageIn(BaseModel):
    bbox: list[float] = Field(min_length=4, max_length=4)
    year: int = Field(ge=2015, le=2100)
    variant: str | None = None

    @field_validator("bbox")
    @classmethod
    def valid_bbox(cls, value: list[float]) -> list[float]:
        min_lon, min_lat, max_lon, max_lat = value
        if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
            raise ValueError("bbox must be min_lon,min_lat,max_lon,max_lat")
        return value


class TesseraImportIn(CoverageIn):
    name: str = Field(default="", max_length=200)
    bands: list[int] | None = Field(
        default_factory=lambda: [1, 2, 3],
        max_length=128,
        description="1-based channel list. Use null to export all 128 channels.",
    )
    visibility: Literal["private", "organisation", "public"] = "private"
    licence: str = Field(default="Tessera dataset terms", max_length=500)
    attribution: str = Field(default="Tessera / GeoTessera", max_length=1000)

    @field_validator("bands")
    @classmethod
    def valid_bands(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if not value:
            return None
        if any(band < 1 or band > 128 for band in value):
            raise ValueError("bands must be between 1 and 128")
        return value


def _errors(exc: Exception) -> HTTPException:
    if isinstance(exc, tessera_service.TesseraUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, (ValueError, KeyError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=502, detail=f"Tessera registry error: {exc}")


@router.get("/meta")
async def meta(user: CurrentUser):
    if not settings.tessera_enabled:
        return {"enabled": False, "years": [], "variants": [], "version": settings.tessera_version}
    try:
        years = await asyncio.to_thread(tessera_service.available_years)
        variants = await asyncio.to_thread(tessera_service.available_variants)
    except Exception as exc:  # noqa: BLE001
        raise _errors(exc) from exc
    return {
        "enabled": True,
        "version": settings.tessera_version,
        "variants": variants,
        "years": years,
        "max_tiles": settings.tessera_max_tiles,
        "band_count": 128,
        "resolution": "10 m",
        "licence": "Tessera dataset terms - https://geotessera.readthedocs.io",
        "attribution": "Tessera / GeoTessera",
    }


@router.post("/coverage")
async def coverage(payload: CoverageIn, user: CurrentUser):
    if not settings.tessera_enabled:
        raise HTTPException(status_code=503, detail="Tessera support is disabled")
    try:
        return await asyncio.to_thread(
            tessera_service.coverage,
            tuple(payload.bbox),
            payload.year,
            payload.variant,
        )
    except Exception as exc:  # noqa: BLE001
        raise _errors(exc) from exc


@router.post("/import", status_code=202)
async def import_tessera(
    payload: TesseraImportIn,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not settings.tessera_enabled:
        raise HTTPException(status_code=503, detail="Tessera support is disabled")
    try:
        info = await asyncio.to_thread(
            tessera_service.coverage,
            tuple(payload.bbox),
            payload.year,
            payload.variant,
        )
    except Exception as exc:  # noqa: BLE001
        raise _errors(exc) from exc
    if not info["tile_count"]:
        raise HTTPException(status_code=422, detail="No Tessera coverage for this area and year")
    if not info["coverage_within_limit"]:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Area contains {info['tile_count']} tiles; limit is {settings.tessera_max_tiles}. "
                "Narrow the bounding box or raise TESSERA_MAX_TILES."
            ),
        )

    name = payload.name.strip() or f"Tessera {payload.year} {info['variant']}"
    job = ImportJob(
        user_id=user.id,
        job_type="tessera",
        status="queued",
        options={
            "bbox": payload.bbox,
            "year": payload.year,
            "variant": info["variant"],
            "name": name,
            "bands": payload.bands,
            "visibility": payload.visibility,
            "licence": payload.licence,
            "attribution": payload.attribution,
        },
    )
    db.add(job)
    await db.flush()
    audit(
        db,
        user,
        "tessera.import",
        "import_job",
        job.id,
        {"bbox": payload.bbox, "year": payload.year, "variant": info["variant"]},
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
    data = serialize_job(job)
    data["coverage"] = {
        "tile_count": info["tile_count"],
        "variant": info["variant"],
        "max_tiles": settings.tessera_max_tiles,
    }
    return data


@router.get("/jobs/{job_id}")
async def tessera_job(
    job_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    job = await get_job_for_user(db, job_id, user)
    if job.job_type != "tessera":
        raise HTTPException(status_code=404, detail="Tessera job not found")
    return serialize_job(job)


@router.get("/datasets")
async def datasets(user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    conditions = [] if user.role == "admin" else [TesseraDataset.created_by == user.id]
    rows = (
        await db.scalars(
            select(TesseraDataset).where(*conditions).order_by(TesseraDataset.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(dataset.id),
            "layer_id": str(dataset.layer_id),
            "year": dataset.year,
            "variant": dataset.variant,
            "tile_ids": dataset.tile_ids,
            "band_count": dataset.band_count,
            "resolution": dataset.resolution,
            "crs": dataset.crs,
            "licence": dataset.licence,
            "attribution": dataset.attribution,
            "created_at": dataset.created_at,
        }
        for dataset in rows
    ]


@router.get("/datasets/{dataset_id}/download")
async def download_dataset(
    dataset_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    dataset = await db.get(TesseraDataset, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Tessera dataset not found")
    if dataset.created_by != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    if not dataset.cache_path:
        raise HTTPException(status_code=404, detail="No cached export is available")
    root = Path(dataset.cache_path)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Cached export has been removed")
    with tempfile.NamedTemporaryFile(
        prefix="nasmap-tessera-", suffix=".zip", delete=False
    ) as handle:
        archive_name = handle.name
    with zipfile.ZipFile(archive_name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*.tif*"):
            zf.write(path, arcname=str(path.relative_to(root)))
    return FileResponse(
        archive_name,
        media_type="application/zip",
        filename="tessera-geotiffs.zip",
        background=BackgroundTask(os.unlink, archive_name),
    )
