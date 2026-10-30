"""Multipart upload endpoint for vector and raster files."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..auth import EditorUser
from ..config import settings
from ..database import get_db
from ..models import ImportJob
from ..permissions import get_layer_or_404, require_write
from ..rate_limit import upload_rate_limit
from ..services.geodata import detect_kind, is_raster
from ..workers.queue import enqueue_import
from .imports import serialize_job

router = APIRouter(prefix="/uploads", tags=["uploads"])
logger = logging.getLogger("nasmap.uploads")

SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(name: str) -> str:
    base = Path(name).name.strip()
    base = SAFE_NAME.sub("_", base)
    if not base or base in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return base[:180]


async def save_upload(upload: UploadFile, destination: Path) -> tuple[int, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    hasher = hashlib.sha256()
    with destination.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                handle.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {settings.max_upload_mb} MB upload limit",
                )
            hasher.update(chunk)
            handle.write(chunk)
    return size, hasher.hexdigest()


@router.post("", status_code=202, dependencies=[Depends(upload_rate_limit)])
async def upload_file(
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    layer_id: str | None = Form(default=None),
    visibility: Literal["private", "organisation", "public"] = Form(default="private"),
    attribution: str = Form(default=""),
    licence: str = Form(default=""),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File has no filename")
    filename = sanitize_filename(file.filename)
    try:
        kind = detect_kind(filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    target_layer = None
    raster_file = is_raster(filename)
    if layer_id:
        target_layer = await get_layer_or_404(db, layer_id)
        await require_write(db, target_layer, user)
        if target_layer.geometry_type == "raster":
            raise HTTPException(
                status_code=422,
                detail="Raster layers cannot be appended to; create a new raster layer instead",
            )
        if raster_file:
            raise HTTPException(status_code=422, detail="Cannot append a raster to a vector layer")

    directory = settings.upload_dir / str(user.id) / uuid.uuid4().hex
    destination = directory / filename
    size, checksum = await save_upload(file, destination)
    if size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    job = ImportJob(
        user_id=user.id,
        layer_id=target_layer.id if target_layer else None,
        job_type="raster" if raster_file else "upload",
        source_path=str(destination),
        options={
            "name": (name or Path(filename).stem).strip()[:200],
            "kind": kind,
            "layer_id": str(target_layer.id) if target_layer else None,
            "visibility": visibility,
            "attribution": attribution,
            "licence": licence,
            "filename": filename,
            "size": size,
            "checksum": checksum,
        },
    )
    db.add(job)
    await db.flush()
    audit(
        db,
        user,
        "upload.create",
        "import_job",
        job.id,
        {"filename": filename, "size": size, "checksum": checksum},
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
