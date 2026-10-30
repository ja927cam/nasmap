"""Geotagged photo import and attachment serving."""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..auth import CurrentUser, EditorUser
from ..config import settings
from ..database import get_db
from ..models import Attachment, Feature, Layer
from ..permissions import get_layer_or_404, require_read, require_write
from ..rate_limit import upload_rate_limit
from ..services import photo_ingest, photos

router = APIRouter(tags=["photos"])
logger = logging.getLogger("nasmap.photos")

SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(name: str) -> str:
    base = Path(name).name.strip()
    base = SAFE_NAME.sub("_", base)
    if not base or base in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return base[:180]


async def save_photo(upload: UploadFile, destination: Path) -> tuple[int, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_photo_mb * 1024 * 1024
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
                    detail=f"Photo exceeds the {settings.max_photo_mb} MB photo limit",
                )
            hasher.update(chunk)
            handle.write(chunk)
    return size, hasher.hexdigest()


def serialize_attachment(attachment: Attachment) -> dict:
    return {
        "id": str(attachment.id),
        "feature_id": str(attachment.feature_id) if attachment.feature_id else None,
        "layer_id": str(attachment.layer_id) if attachment.layer_id else None,
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        "created_at": attachment.created_at,
        "content_url": f"/api/v1/attachments/{attachment.id}/content",
        "thumb_url": f"/api/v1/attachments/{attachment.id}/content?thumb=true",
    }


def _safe_storage_path(value: str) -> Path:
    allowed = [settings.upload_dir.resolve()]
    allowed.extend(root.resolve() for root in settings.ingest_root_list if root.exists())
    path = Path(value).resolve()
    if not any(root == path or root in path.parents for root in allowed):
        raise HTTPException(status_code=404, detail="Attachment file not found")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment file not found")
    return path


async def _attachment_layer(db: AsyncSession, attachment: Attachment) -> Layer:
    if attachment.feature_id:
        feature = await db.get(Feature, attachment.feature_id)
        if feature:
            return await get_layer_or_404(db, feature.layer_id)
    if attachment.layer_id:
        return await get_layer_or_404(db, attachment.layer_id)
    raise HTTPException(status_code=404, detail="Attachment layer not found")


@router.post("/photos/import", dependencies=[Depends(upload_rate_limit)])
async def import_photos(
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    files: list[UploadFile] = File(...),
    layer_id: str | None = Form(default=None),
    name: str | None = Form(default=None),
    visibility: Literal["private", "organisation", "public"] = Form(default="private"),
    match_existing: bool = Form(default=False),
    match_radius_m: int = Form(default=60, ge=1, le=5000),
):
    if not files:
        raise HTTPException(status_code=422, detail="Select at least one photo")
    if len(files) > 100:
        raise HTTPException(status_code=422, detail="Import at most 100 photos at a time")

    target_layer: Layer | None = None
    existing_layer = False
    if layer_id:
        target_layer = await get_layer_or_404(db, layer_id)
        await require_write(db, target_layer, user)
        if target_layer.geometry_type not in {"point", "geometry"}:
            raise HTTPException(
                status_code=422,
                detail="Photos can only be added to point or mixed-geometry layers",
            )
        existing_layer = True

    import_dir = settings.upload_dir / "photos" / str(user.id) / uuid.uuid4().hex
    import_dir.mkdir(parents=True, exist_ok=True)
    incoming: list[photos.PhotoMetadata] = []
    skipped: list[dict[str, str]] = []

    try:
        for upload in files:
            if not upload.filename:
                skipped.append({"filename": "unnamed", "reason": "Missing filename"})
                continue
            filename = sanitize_filename(upload.filename)
            if not photos.is_photo(filename):
                skipped.append(
                    {
                        "filename": filename,
                        "reason": "Unsupported image type (JPEG, TIFF, PNG, WebP or RAF)",
                    }
                )
                continue
            destination = import_dir / uuid.uuid4().hex / filename
            try:
                await save_photo(upload, destination)
                metadata = photos.inspect_photo(destination)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                destination.unlink(missing_ok=True)
                skipped.append({"filename": filename, "reason": f"Could not read photo: {exc}"})
                continue
            if metadata.lat is None or metadata.lon is None:
                destination.unlink(missing_ok=True)
                skipped.append(
                    {
                        "filename": filename,
                        "reason": (
                            "No GPS EXIF tag found. Enable location when taking the "
                            "photo or convert it with geotagging metadata."
                        ),
                    }
                )
                continue
            incoming.append(metadata)

        if not incoming:
            shutil.rmtree(import_dir, ignore_errors=True)
            return {
                "layer_id": str(target_layer.id) if target_layer else None,
                "created_features": 0,
                "attached_photos": 0,
                "skipped": skipped,
                "message": "No geotagged photos were found.",
            }

        if target_layer is None:
            layer_name = (
                name or ""
            ).strip() or f"Photos {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"
            target_layer = await photo_ingest.create_photo_layer(
                db, user.id, layer_name, visibility
            )

        summary = await photo_ingest.attach_photo_metadata(
            db,
            user.id,
            target_layer,
            incoming,
            skipped,
            match_existing=match_existing,
            existing_layer=existing_layer,
            match_radius_m=match_radius_m,
        )
        created_features = summary["created_features"]
        attached_photos = summary["attached_photos"]
        attachments = summary["attachments"]
        for duplicate in summary["duplicate_paths"]:
            duplicate.unlink(missing_ok=True)

        audit(
            db,
            user,
            "photos.import",
            "layer",
            target_layer.id,
            {
                "created_features": created_features,
                "attached_photos": attached_photos,
                "attachments": len(attachments),
                "skipped": len(skipped),
            },
            request,
        )
        await db.commit()
        await db.refresh(target_layer)
        return {
            "layer_id": str(target_layer.id),
            "layer_name": target_layer.name,
            "created_features": created_features,
            "attached_photos": attached_photos,
            "skipped": skipped,
            "attachments": [serialize_attachment(item) for item in attachments],
        }
    except Exception:
        await db.rollback()
        shutil.rmtree(import_dir, ignore_errors=True)
        raise


@router.get("/features/{feature_id}/attachments")
async def feature_attachments(
    feature_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    feature = await db.get(Feature, feature_id)
    if not feature or feature.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Feature not found")
    layer = await get_layer_or_404(db, feature.layer_id)
    await require_read(db, layer, user)
    rows = (
        await db.scalars(
            select(Attachment)
            .where(Attachment.feature_id == feature.id)
            .order_by(Attachment.created_at)
        )
    ).all()
    return [serialize_attachment(item) for item in rows]


@router.get("/layers/{layer_id}/attachments")
async def layer_attachments(
    layer_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    layer = await get_layer_or_404(db, layer_id)
    await require_read(db, layer, user)
    rows = (
        await db.scalars(
            select(Attachment)
            .where(Attachment.layer_id == layer.id)
            .order_by(Attachment.created_at)
        )
    ).all()
    return [serialize_attachment(item) for item in rows]


@router.post("/features/{feature_id}/attachments")
async def add_feature_attachments(
    feature_id: str,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    files: list[UploadFile] = File(...),
):
    feature = await db.get(Feature, feature_id)
    if not feature or feature.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Feature not found")
    layer = await get_layer_or_404(db, feature.layer_id)
    await require_write(db, layer, user)
    if not files:
        raise HTTPException(status_code=422, detail="Select at least one image")
    if len(files) > 50:
        raise HTTPException(status_code=422, detail="Add at most 50 photos at a time")

    import_dir = settings.upload_dir / "attachments" / str(user.id) / uuid.uuid4().hex
    import_dir.mkdir(parents=True, exist_ok=True)
    created: list[Attachment] = []
    skipped: list[dict[str, str]] = []
    try:
        for upload in files:
            if not upload.filename:
                skipped.append({"filename": "unnamed", "reason": "Missing filename"})
                continue
            filename = sanitize_filename(upload.filename)
            if not photos.is_photo(filename):
                skipped.append(
                    {
                        "filename": filename,
                        "reason": "Unsupported image type (JPEG, TIFF, PNG, WebP or RAF)",
                    }
                )
                continue
            destination = import_dir / uuid.uuid4().hex / filename
            try:
                await save_photo(upload, destination)
                metadata = photos.inspect_photo(destination)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                destination.unlink(missing_ok=True)
                skipped.append({"filename": filename, "reason": f"Could not read image: {exc}"})
                continue
            duplicate = await db.scalar(
                select(Attachment.id).where(
                    Attachment.feature_id == feature.id,
                    Attachment.checksum == metadata.checksum,
                )
            )
            if duplicate:
                destination.unlink(missing_ok=True)
                skipped.append({"filename": filename, "reason": "Already attached (checksum)"})
                continue
            attachment = Attachment(
                layer_id=layer.id,
                feature_id=feature.id,
                filename=metadata.filename,
                content_type=metadata.content_type,
                size_bytes=metadata.size_bytes,
                storage_path=str(metadata.storage_path),
                checksum=metadata.checksum,
                created_by=user.id,
            )
            db.add(attachment)
            await db.flush()
            created.append(attachment)

        audit(
            db,
            user,
            "attachments.add",
            "feature",
            feature.id,
            {"created": len(created), "skipped": len(skipped)},
            request,
        )
        await db.commit()
        return {
            "attachments": [serialize_attachment(item) for item in created],
            "skipped": skipped,
        }
    except Exception:
        await db.rollback()
        shutil.rmtree(import_dir, ignore_errors=True)
        raise


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: str,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    attachment = await db.get(Attachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")
    layer = await _attachment_layer(db, attachment)
    await require_write(db, layer, user)
    path = Path(attachment.storage_path).resolve()
    upload_root = settings.upload_dir.resolve()
    if path == upload_root or upload_root in path.parents:
        path.unlink(missing_ok=True)
    for cached in (
        settings.upload_dir / "thumbs" / f"{attachment.id}.jpg",
        settings.upload_dir / "previews" / f"{attachment.id}.jpg",
    ):
        cached.unlink(missing_ok=True)
    audit(db, user, "attachments.delete", "attachment", attachment.id, request=request)
    await db.delete(attachment)
    await db.commit()
    return {"ok": True}


@router.get("/attachments/{attachment_id}/content")
async def attachment_content(
    attachment_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    thumb: bool = False,
):
    attachment = await db.get(Attachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")
    layer = await _attachment_layer(db, attachment)
    await require_read(db, layer, user)
    path = _safe_storage_path(attachment.storage_path)
    if thumb:
        if not attachment.content_type.startswith("image/"):
            raise HTTPException(status_code=415, detail="Thumbnail is only available for images")
        thumb_path = settings.upload_dir / "thumbs" / f"{attachment.id}.jpg"
        if not thumb_path.exists():
            try:
                photos.make_thumbnail(path, thumb_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("thumbnail generation failed: %s", exc)
                raise HTTPException(status_code=500, detail="Could not generate thumbnail") from exc
        return FileResponse(thumb_path, media_type="image/jpeg")
    if attachment.content_type == photos.RAF_CONTENT_TYPE:
        preview_path = settings.upload_dir / "previews" / f"{attachment.id}.jpg"
        if not preview_path.exists():
            try:
                photos.make_preview(path, preview_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("RAF preview generation failed: %s", exc)
                raise HTTPException(
                    status_code=500, detail="Could not generate RAF preview"
                ) from exc
        return FileResponse(
            preview_path,
            media_type="image/jpeg",
            filename=f"{Path(attachment.filename).stem}.jpg",
        )
    return FileResponse(path, media_type=attachment.content_type, filename=attachment.filename)
