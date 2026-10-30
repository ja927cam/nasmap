"""Server/NAS folder browsing and bulk ingestion endpoints."""

from __future__ import annotations

import logging
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
from ..services import ingest
from ..workers.queue import enqueue_import
from .imports import serialize_job

router = APIRouter(prefix="/ingest", tags=["ingest"])
logger = logging.getLogger("nasmap.ingest")


class ScanIn(BaseModel):
    path: str = Field(default="", max_length=2000)
    recursive: bool = True
    kind: Literal["auto", "photos", "geodata"] = "auto"
    limit: int = Field(default=500, ge=1, le=5000)


class IngestIn(BaseModel):
    path: str = Field(default="", max_length=2000)
    mode: Literal["photos", "geodata"]
    recursive: bool = True
    name: str = Field(default="", max_length=200)
    layer_id: str | None = None
    visibility: Literal["private", "organisation", "public"] = "private"
    match_existing: bool = False
    match_radius_m: int = Field(default=60, ge=1, le=5000)
    licence: str = Field(default="", max_length=500)
    attribution: str = Field(default="", max_length=1000)


def _path_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ingest.IngestUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ingest.UnsafeIngestPath):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, OSError):
        return HTTPException(status_code=422, detail=f"Could not read folder: {exc}")
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/roots")
async def ingest_roots(user: EditorUser):
    try:
        ingest.ensure_available()
    except ingest.IngestUnavailable as exc:
        return {
            "enabled": False,
            "roots": ingest.root_info(),
            "message": str(exc),
            "max_scan_files": settings.ingest_max_scan_files,
            "max_files_per_job": settings.ingest_max_files_per_job,
        }
    return {
        "enabled": True,
        "roots": ingest.root_info(),
        "max_scan_files": settings.ingest_max_scan_files,
        "max_files_per_job": settings.ingest_max_files_per_job,
    }


@router.post("/scan")
async def scan_folder(payload: ScanIn, user: EditorUser):
    try:
        path = ingest.resolve_path(payload.path)
        kinds = None
        if payload.kind == "photos":
            kinds = {ingest.PHOTO_KIND}
        elif payload.kind == "geodata":
            kinds = {ingest.VECTOR_KIND, ingest.RASTER_KIND}
        files, truncated, errors = ingest.scan(
            path,
            kinds=kinds,
            recursive=payload.recursive,
            limit=min(payload.limit, settings.ingest_max_scan_files),
        )
    except Exception as exc:  # noqa: BLE001
        raise _path_error(exc) from exc
    counts = {"photo": 0, "vector": 0, "raster": 0}
    for item in files:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return {
        "path": str(path),
        "recursive": payload.recursive,
        "kind": payload.kind,
        "counts": counts,
        "total": len(files),
        "truncated": truncated,
        "errors": errors[:20],
        "files": [item.as_dict() for item in files[:200]],
    }


@router.post("", status_code=202)
async def start_ingest(
    payload: IngestIn,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        path = ingest.resolve_path(payload.path)
    except Exception as exc:  # noqa: BLE001
        raise _path_error(exc) from exc

    layer = None
    if payload.mode == "photos" and payload.layer_id:
        layer = await get_layer_or_404(db, payload.layer_id)
        await require_write(db, layer, user)
        if layer.geometry_type not in {"point", "geometry"}:
            raise HTTPException(
                status_code=422,
                detail="Photos can only be added to point or mixed-geometry layers",
            )
    if payload.mode == "geodata" and payload.layer_id:
        raise HTTPException(
            status_code=422,
            detail="Geodata folder imports create one layer per file; layer_id is not supported",
        )

    job = ImportJob(
        user_id=user.id,
        layer_id=layer.id if layer else None,
        job_type="ingest",
        status="queued",
        source_path=str(path),
        options={
            "mode": payload.mode,
            "path": str(path),
            "relative_path": "",
            "recursive": payload.recursive,
            "name": payload.name,
            "layer_id": str(layer.id) if layer else None,
            "visibility": payload.visibility,
            "match_existing": payload.match_existing,
            "match_radius_m": payload.match_radius_m,
            "licence": payload.licence,
            "attribution": payload.attribution,
        },
    )
    db.add(job)
    await db.flush()
    audit(
        db,
        user,
        "ingest.start",
        "import_job",
        job.id,
        {"mode": payload.mode, "path": str(path), "recursive": payload.recursive},
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


@router.get("/browse")
async def browse(user: EditorUser, path: str = ""):
    """Very small directory listing for the folder picker."""
    try:
        directory = ingest.resolve_path(path)
        entries = list(directory.iterdir())
    except Exception as exc:  # noqa: BLE001
        raise _path_error(exc) from exc
    directories = sorted(
        [
            {"name": item.name, "path": str(item)}
            for item in entries
            if item.is_dir()
            and not item.name.startswith(".")
            and item.name.lower() not in ingest.IGNORED_DIRECTORIES
        ],
        key=lambda item: item["name"].lower(),
    )
    files = sorted(
        [
            {"name": item.name, "path": str(item), "size": item.stat().st_size}
            for item in entries
            if item.is_file() and ingest.classify(item) is not None
        ],
        key=lambda item: item["name"].lower(),
    )[:200]
    return {"path": str(directory), "directories": directories, "files": files}
