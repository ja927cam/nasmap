"""Shared photo-to-feature/attachment creation for browser and server imports."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Attachment, Feature, Layer
from .photos import PhotoMetadata, photo_title


async def create_photo_layer(
    db: AsyncSession,
    user_id,
    name: str,
    visibility: str,
) -> Layer:
    layer = Layer(
        owner_id=user_id,
        name=name,
        description="Imported from geotagged photo EXIF data.",
        visibility=visibility,
        geometry_type="point",
        source_type="upload",
        style={"color": "#0ea5e9", "circleRadius": 7},
        metadata_={"photo_import": True},
        attribution="Photo EXIF metadata",
        licence="",
    )
    db.add(layer)
    await db.flush()
    return layer


class PhotoIngestCancelled(RuntimeError):
    pass


async def attach_photo_metadata(
    db: AsyncSession,
    user_id,
    layer: Layer,
    incoming: list[PhotoMetadata],
    skipped: list[dict[str, str]],
    *,
    match_existing: bool,
    existing_layer: bool,
    match_radius_m: int,
    progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    created_features = 0
    attached_photos = 0
    duplicate_paths = []
    attachments: list[Attachment] = []

    for index, metadata in enumerate(incoming):
        if is_cancelled and is_cancelled():
            raise PhotoIngestCancelled("Photo ingest cancelled by user")
        existing = await db.scalar(
            select(Attachment.id).where(
                Attachment.layer_id == layer.id,
                Attachment.checksum == metadata.checksum,
            )
        )
        if existing:
            duplicate_paths.append(metadata.storage_path)
            skipped.append({"filename": metadata.filename, "reason": "Already imported (checksum)"})
            continue

        matched_feature: Feature | None = None
        if match_existing and existing_layer:
            point = func.ST_SetSRID(func.ST_MakePoint(metadata.lon, metadata.lat), 4326)
            distance = func.ST_DistanceSphere(Feature.geometry, point)
            matched_feature = await db.scalar(
                select(Feature)
                .where(
                    Feature.layer_id == layer.id,
                    Feature.deleted_at.is_(None),
                    distance <= match_radius_m,
                )
                .order_by(distance)
                .limit(1)
            )

        feature = matched_feature
        if feature is None:
            properties = {
                "name": photo_title(metadata),
                "photo_filename": metadata.filename,
                "photo_timestamp": metadata.timestamp,
                "photo_camera": metadata.camera,
                "photo_altitude": metadata.altitude,
                "photo_width": metadata.width,
                "photo_height": metadata.height,
                "photo_source": "EXIF",
            }
            valid_from = None
            if metadata.timestamp:
                try:
                    valid_from = datetime.fromisoformat(metadata.timestamp)
                except ValueError:
                    valid_from = None
            feature = Feature(
                layer_id=layer.id,
                properties={key: value for key, value in properties.items() if value is not None},
                geometry=WKTElement(f"POINT({metadata.lon} {metadata.lat})", srid=4326),
                created_by=user_id,
                updated_by=user_id,
                valid_from=valid_from,
            )
            db.add(feature)
            await db.flush()
            created_features += 1
        else:
            attached_photos += 1

        attachment = Attachment(
            layer_id=layer.id,
            feature_id=feature.id,
            filename=metadata.filename,
            content_type=metadata.content_type,
            size_bytes=metadata.size_bytes,
            storage_path=str(metadata.storage_path),
            checksum=metadata.checksum,
            created_by=user_id,
        )
        db.add(attachment)
        await db.flush()
        attachments.append(attachment)
        if progress and (index % 25 == 0 or index + 1 == len(incoming)):
            progress(index + 1, len(incoming))

    layer.metadata_ = {
        **(layer.metadata_ or {}),
        "photo_import": True,
        "photo_count": int((layer.metadata_ or {}).get("photo_count", 0)) + len(attachments),
    }
    return {
        "created_features": created_features,
        "attached_photos": attached_photos,
        "attachments": attachments,
        "duplicate_paths": duplicate_paths,
    }
