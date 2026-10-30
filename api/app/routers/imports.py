"""Import job status, listing, cancellation and external source management."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..auth import CurrentUser, EditorUser
from ..database import get_db
from ..models import ExternalSource, ImportJob, Layer
from ..permissions import get_layer_or_404, require_write
from ..rate_limit import upload_rate_limit
from ..services import remote
from ..workers.queue import enqueue_import

router = APIRouter(prefix="/imports", tags=["imports"])

JobType = Literal["upload", "url", "tessera", "raster", "osm", "export", "ingest"]


def serialize_job(job: ImportJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "layer_id": str(job.layer_id) if job.layer_id else None,
        "source_url": job.source_url,
        "options": job.options or {},
        "result": job.result or {},
        "attempts": job.attempts,
        "cancel_requested": job.cancel_requested,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "updated_at": job.updated_at,
    }


async def get_job_for_user(db: AsyncSession, job_id: str, user) -> ImportJob:
    job = await db.get(ImportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    if job.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="You do not have access to this job")
    return job


class UrlImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=4000)
    name: str | None = Field(default=None, max_length=200)
    kind: Literal["auto", "geojson", "gpkg", "cog", "wms", "wfs", "arcgis", "stac", "url"] = "auto"
    layer_id: str | None = None
    licence: str = Field(default="", max_length=500)
    attribution: str = Field(default="", max_length=1000)
    visibility: Literal["private", "organisation", "public"] = "private"
    refresh_interval_seconds: int | None = Field(default=None, ge=300, le=365 * 86400)
    type_name: str | None = Field(default=None, max_length=500, description="WFS typeName")
    wms_layers: str | None = Field(default=None, max_length=1000)
    wms_version: str = Field(default="1.3.0", max_length=10)
    wms_format: str = Field(default="image/png", max_length=50)
    bounds: list[float] | None = Field(default=None, min_length=4, max_length=4)


class SourceUpdate(BaseModel):
    licence: str | None = Field(default=None, max_length=500)
    attribution: str | None = Field(default=None, max_length=1000)
    refresh_interval_seconds: int | None = Field(default=None, ge=300, le=365 * 86400)
    enabled: bool | None = None


@router.get("")
async def list_jobs(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None,
    job_type: JobType | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    conditions = []
    if user.role != "admin":
        conditions.append(ImportJob.user_id == user.id)
    if status:
        conditions.append(ImportJob.status == status)
    if job_type:
        conditions.append(ImportJob.job_type == job_type)
    where = conditions[0] if conditions else True
    for condition in conditions[1:]:
        where = where & condition
    total = int(await db.scalar(select(func.count()).select_from(ImportJob).where(where)) or 0)
    jobs = (
        await db.scalars(
            select(ImportJob)
            .where(where)
            .order_by(ImportJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return {
        "items": [serialize_job(job) for job in jobs],
        "meta": {"total": total, "limit": limit, "offset": offset, "returned": len(jobs)},
    }


@router.get("/sources")
async def list_sources(user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    conditions = [] if user.role == "admin" else [ExternalSource.user_id == user.id]
    rows = (
        await db.scalars(
            select(ExternalSource).where(*conditions).order_by(ExternalSource.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(source.id),
            "layer_id": str(source.layer_id) if source.layer_id else None,
            "kind": source.kind,
            "url": source.url,
            "licence": source.licence,
            "attribution": source.attribution,
            "checksum": source.checksum,
            "retrieved_at": source.retrieved_at,
            "last_import_at": source.last_import_at,
            "refresh_interval_seconds": source.refresh_interval_seconds,
            "next_refresh_at": source.next_refresh_at,
            "enabled": source.enabled,
            "metadata": source.metadata_,
        }
        for source in rows
    ]


@router.post("/url", status_code=202, dependencies=[Depends(upload_rate_limit)])
async def import_url(
    payload: UrlImportIn,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        remote.validate_url(payload.url)
    except remote.UnsafeURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    kind = payload.kind
    if kind == "auto":
        kind = remote.detect_remote_kind(payload.url)
    if kind == "wms" and not payload.url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Invalid WMS URL")

    layer = None
    if payload.layer_id:
        layer = await get_layer_or_404(db, payload.layer_id)
        await require_write(db, layer, user)
        if layer.geometry_type == "raster" and kind not in {"wms", "cog", "stac"}:
            raise HTTPException(status_code=422, detail="Cannot append vectors to a raster layer")

    source = ExternalSource(
        user_id=user.id,
        layer_id=layer.id if layer else None,
        kind=kind,
        url=payload.url,
        licence=payload.licence,
        attribution=payload.attribution,
        refresh_interval_seconds=payload.refresh_interval_seconds,
        next_refresh_at=(
            datetime.now(UTC) + timedelta(seconds=payload.refresh_interval_seconds)
            if payload.refresh_interval_seconds
            else None
        ),
        metadata_={"name": payload.name or ""},
    )
    db.add(source)
    await db.flush()

    job = ImportJob(
        user_id=user.id,
        layer_id=layer.id if layer else None,
        job_type="url",
        source_url=payload.url,
        options={
            "name": payload.name or "",
            "kind": kind,
            "source_id": str(source.id),
            "layer_id": str(layer.id) if layer else None,
            "licence": payload.licence,
            "attribution": payload.attribution,
            "visibility": payload.visibility,
            "type_name": payload.type_name,
            "wms_url": payload.url.split("?")[0],
            "wms_layers": payload.wms_layers or "",
            "wms_version": payload.wms_version,
            "wms_format": payload.wms_format,
            "bounds": payload.bounds,
        },
    )
    db.add(job)
    await db.flush()
    audit(
        db,
        user,
        "import.url.create",
        "import_job",
        job.id,
        {"url": payload.url, "kind": kind},
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


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    job = await get_job_for_user(db, job_id, user)
    data = serialize_job(job)
    if job.layer_id:
        layer = await db.get(Layer, job.layer_id)
        if layer:
            data["layer"] = {
                "id": str(layer.id),
                "name": layer.name,
                "geometry_type": layer.geometry_type,
            }
    return data


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    job = await get_job_for_user(db, job_id, user)
    if job.status in {"succeeded", "failed", "cancelled"}:
        return {"ok": True, "status": job.status}
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = datetime.now(UTC)
    audit(db, user, "import.cancel", "import_job", job.id, request=request)
    await db.commit()
    return {"ok": True, "status": job.status}


@router.post("/{job_id}/retry", status_code=202)
async def retry_job(
    job_id: str,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    job = await get_job_for_user(db, job_id, user)
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Only failed or cancelled jobs can be retried")
    job.status = "queued"
    job.progress = 0
    job.error = None
    job.message = "Retrying"
    job.cancel_requested = False
    job.finished_at = None
    audit(db, user, "import.retry", "import_job", job.id, request=request)
    await db.commit()
    try:
        enqueue_import(str(job.id))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="Import queue unavailable") from exc
    return serialize_job(job)


@router.patch("/sources/{source_id}")
async def update_source(
    source_id: str,
    payload: SourceUpdate,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    source = await db.get(ExternalSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    if payload.licence is not None:
        source.licence = payload.licence
    if payload.attribution is not None:
        source.attribution = payload.attribution
    if payload.enabled is not None:
        source.enabled = payload.enabled
    if payload.refresh_interval_seconds is not None:
        source.refresh_interval_seconds = payload.refresh_interval_seconds
        source.next_refresh_at = datetime.now(UTC) + timedelta(
            seconds=payload.refresh_interval_seconds
        )
    audit(db, user, "source.update", "external_source", source.id, request=request)
    await db.commit()
    return {"ok": True}


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: str,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    source = await db.get(ExternalSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    await db.delete(source)
    audit(db, user, "source.delete", "external_source", source.id, request=request)
    await db.commit()
    return {"ok": True}
