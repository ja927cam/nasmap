"""Layer CRUD, permissions and exports."""

from __future__ import annotations

import math
import shutil
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from ..audit import audit
from ..auth import CurrentUser, EditorUser
from ..database import get_db
from ..models import Layer, LayerPermission, User
from ..permissions import (
    get_layer_or_404,
    permission_role,
    require_owner,
    require_read,
    require_write,
    visible_layers_filter,
)
from ..schemas import UserOut
from ..services.geodata import export_layer_file

router = APIRouter(prefix="/layers", tags=["layers"])

Visibility = Literal["private", "organisation", "public"]
PROTECTED_METADATA_KEYS = {
    "raster_path",
    "raster_url",
    "wms",
    "xyz",
    "provider",
    "total_bounds",
    "source_url",
    "raster",
    "tessera",
    "source_path",
}
GeometryType = Literal["point", "line", "polygon", "geometry", "raster", "table"]
SourceType = Literal["upload", "url", "tessera", "osm", "api", "manual"]


class LayerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    visibility: Visibility = "private"
    geometry_type: GeometryType = "geometry"
    source_type: SourceType = "manual"
    style: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    attribution: str = Field(default="", max_length=1000)
    licence: str = Field(default="", max_length=500)


class LayerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    visibility: Visibility | None = None
    geometry_type: GeometryType | None = None
    style: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    attribution: str | None = Field(default=None, max_length=1000)
    licence: str | None = Field(default=None, max_length=500)


class PermissionIn(BaseModel):
    email: str
    role: Literal["editor", "viewer"]


def _safe_user_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """User metadata is descriptive only; source/raster pointers are server-owned."""
    return {
        str(key): value
        for key, value in (metadata or {}).items()
        if key not in PROTECTED_METADATA_KEYS
    }


def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    clean = {
        key: value
        for key, value in (metadata or {}).items()
        if key not in {"raster_path", "source_path"}
    }
    if isinstance(clean.get("tessera"), dict):
        clean["tessera"] = {
            key: value for key, value in clean["tessera"].items() if key not in {"tile_files"}
        }
    return clean


def serialize_layer(layer: Layer, role: str | None = None) -> dict[str, Any]:
    return {
        "id": str(layer.id),
        "owner_id": str(layer.owner_id),
        "name": layer.name,
        "description": layer.description,
        "visibility": layer.visibility,
        "geometry_type": layer.geometry_type,
        "source_type": layer.source_type,
        "style": layer.style or {},
        "metadata": _public_metadata(layer.metadata_),
        "attribution": layer.attribution,
        "licence": layer.licence,
        "feature_count": layer.feature_count,
        "access_role": role,
        "deleted_at": layer.deleted_at,
        "created_at": layer.created_at,
        "updated_at": layer.updated_at,
    }


async def _roles_for_layers(db: AsyncSession, user: User, layers: list[Layer]) -> dict[UUID, str]:
    roles: dict[UUID, str] = {}
    ids = [layer.id for layer in layers]
    if not ids:
        return roles
    rows = (
        await db.execute(
            select(LayerPermission.layer_id, LayerPermission.role).where(
                LayerPermission.user_id == user.id, LayerPermission.layer_id.in_(ids)
            )
        )
    ).all()
    grants = {row[0]: row[1] for row in rows}
    for layer in layers:
        if user.role in {"admin"} or layer.owner_id == user.id:
            roles[layer.id] = "owner"
        elif layer.id in grants:
            roles[layer.id] = grants[layer.id]
        elif layer.visibility in {"public", "organisation"}:
            roles[layer.id] = "viewer"
    return roles


@router.get("")
async def list_layers(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = Query(default=None, max_length=200),
    visibility: Visibility | None = None,
    geometry_type: GeometryType | None = None,
    source_type: SourceType | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort: Literal["updated", "created", "name"] = "updated",
):
    conditions = [await visible_layers_filter(user)]
    if q:
        pattern = f"%{q}%"
        conditions.append(or_(Layer.name.ilike(pattern), Layer.description.ilike(pattern)))
    if visibility:
        conditions.append(Layer.visibility == visibility)
    if geometry_type:
        conditions.append(Layer.geometry_type == geometry_type)
    if source_type:
        conditions.append(Layer.source_type == source_type)

    where = conditions[0]
    for condition in conditions[1:]:
        where = where & condition

    total = int(await db.scalar(select(func.count()).select_from(Layer).where(where)) or 0)
    order = {
        "updated": Layer.updated_at.desc(),
        "created": Layer.created_at.desc(),
        "name": Layer.name.asc(),
    }[sort]
    layers = (
        await db.scalars(select(Layer).where(where).order_by(order).limit(limit).offset(offset))
    ).all()
    roles = await _roles_for_layers(db, user, list(layers))
    return {
        "items": [serialize_layer(layer, roles.get(layer.id)) for layer in layers],
        "meta": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "returned": len(layers),
        },
    }


@router.post("", status_code=201)
async def create_layer(
    payload: LayerCreate,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    layer = Layer(
        owner_id=user.id,
        name=payload.name.strip(),
        description=payload.description,
        visibility=payload.visibility,
        geometry_type=payload.geometry_type,
        source_type=payload.source_type,
        style=payload.style,
        metadata_=_safe_user_metadata(payload.metadata),
        attribution=payload.attribution,
        licence=payload.licence,
    )
    db.add(layer)
    await db.flush()
    audit(db, user, "layer.create", "layer", layer.id, {"name": layer.name}, request)
    await db.commit()
    await db.refresh(layer)
    return serialize_layer(layer, "owner")


@router.get("/{layer_id}")
async def get_layer(
    layer_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    layer = await get_layer_or_404(db, layer_id)
    role = await require_read(db, layer, user)
    owner = await db.get(User, layer.owner_id)
    data = serialize_layer(layer, role)
    data["owner"] = UserOut.model_validate(owner).model_dump() if owner else None
    return data


@router.patch("/{layer_id}")
async def update_layer(
    layer_id: str,
    payload: LayerUpdate,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    layer = await get_layer_or_404(db, layer_id)
    await require_write(db, layer, user)
    changes = payload.model_dump(exclude_unset=True)
    if "visibility" in changes and user.role != "admin" and layer.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can change visibility")
    if "metadata" in changes:
        layer.metadata_ = {
            **(layer.metadata_ or {}),
            **_safe_user_metadata(changes.pop("metadata")),
        }
    for key, value in changes.items():
        setattr(layer, key, value)
    audit(db, user, "layer.update", "layer", layer.id, {"fields": list(changes)}, request)
    await db.commit()
    await db.refresh(layer)
    role = await permission_role(db, layer, user)
    return serialize_layer(layer, role)


@router.delete("/{layer_id}")
async def delete_layer(
    layer_id: str,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    layer = await get_layer_or_404(db, layer_id)
    await require_owner(db, layer, user)
    layer.deleted_at = datetime.now(UTC)
    audit(db, user, "layer.delete", "layer", layer.id, {"name": layer.name}, request)
    await db.commit()
    return {"ok": True, "deleted_at": layer.deleted_at}


@router.get("/{layer_id}/stats")
async def layer_stats(
    layer_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from sqlalchemy import text

    layer = await get_layer_or_404(db, layer_id)
    await require_read(db, layer, user)
    row = (
        await db.execute(
            text(
                """
                SELECT count(*) AS count,
                       ST_Extent(geometry)::text AS extent,
                       count(*) FILTER (WHERE NOT ST_IsValid(geometry)) AS invalid
                  FROM app.features
                 WHERE layer_id = :layer_id AND deleted_at IS NULL
                """
            ),
            {"layer_id": layer.id},
        )
    ).one()
    return {
        "feature_count": int(row.count),
        "extent": row.extent,
        "invalid_geometries": int(row.invalid or 0),
    }


@router.get("/{layer_id}/permissions")
async def list_permissions(
    layer_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    layer = await get_layer_or_404(db, layer_id)
    await require_owner(db, layer, user)
    rows = (
        await db.execute(
            select(LayerPermission, User)
            .join(User, User.id == LayerPermission.user_id)
            .where(LayerPermission.layer_id == layer.id)
            .order_by(User.email)
        )
    ).all()
    return [
        {
            "id": str(perm.id),
            "role": perm.role,
            "user": UserOut.model_validate(member).model_dump(),
            "created_at": perm.created_at,
        }
        for perm, member in rows
    ]


@router.post("/{layer_id}/permissions", status_code=201)
async def add_permission(
    layer_id: str,
    payload: PermissionIn,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    layer = await get_layer_or_404(db, layer_id)
    await require_owner(db, layer, user)
    target = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == layer.owner_id:
        raise HTTPException(status_code=400, detail="The owner already has full access")
    existing = await db.scalar(
        select(LayerPermission).where(
            LayerPermission.layer_id == layer.id, LayerPermission.user_id == target.id
        )
    )
    if existing:
        existing.role = payload.role
    else:
        existing = LayerPermission(
            layer_id=layer.id,
            user_id=target.id,
            role=payload.role,
            created_by=user.id,
        )
        db.add(existing)
    audit(
        db,
        user,
        "layer.permission_grant",
        "layer",
        layer.id,
        {"user_id": str(target.id), "role": payload.role},
        request,
    )
    await db.commit()
    return {"ok": True}


@router.delete("/{layer_id}/permissions/{permission_id}")
async def remove_permission(
    layer_id: str,
    permission_id: str,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    layer = await get_layer_or_404(db, layer_id)
    await require_owner(db, layer, user)
    perm = await db.get(LayerPermission, permission_id)
    if not perm or perm.layer_id != layer.id:
        raise HTTPException(status_code=404, detail="Permission not found")
    await db.delete(perm)
    audit(db, user, "layer.permission_revoke", "layer", layer.id, {}, request)
    await db.commit()
    return {"ok": True}


@router.get("/{layer_id}/export")
async def export_layer(
    layer_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    format: Literal["geojson", "gpkg", "kml", "csv"] = "geojson",
):
    layer = await get_layer_or_404(db, layer_id)
    await require_read(db, layer, user)
    if layer.geometry_type in {"raster", "table"}:
        raise HTTPException(
            status_code=400, detail="Raster and table layers cannot be exported as vectors"
        )
    path, media_type, filename = await export_layer_file(db, layer, format)
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        background=BackgroundTask(shutil.rmtree, path.parent, True),
    )


@router.post("/{layer_id}/duplicate", status_code=201)
async def duplicate_layer(
    layer_id: str,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from sqlalchemy import text

    source = await get_layer_or_404(db, layer_id)
    await require_read(db, source, user)
    layer = Layer(
        owner_id=user.id,
        name=f"{source.name} (copy)",
        description=source.description,
        visibility="private",
        geometry_type=source.geometry_type,
        source_type=source.source_type,
        style=source.style,
        metadata_=source.metadata_,
        attribution=source.attribution,
        licence=source.licence,
    )
    db.add(layer)
    await db.flush()
    if source.geometry_type not in {"raster", "table"}:
        await db.execute(
            text(
                """
                INSERT INTO app.features(layer_id, properties, geometry, created_by, updated_by)
                SELECT :new_id, properties, geometry, :user_id, :user_id
                  FROM app.features WHERE layer_id = :source_id AND deleted_at IS NULL
                """
            ),
            {"new_id": layer.id, "source_id": source.id, "user_id": user.id},
        )
    audit(db, user, "layer.duplicate", "layer", layer.id, {"source": str(source.id)}, request)
    await db.commit()
    await db.refresh(layer)
    return serialize_layer(layer, "owner")


def bbox_area_km2(bbox: tuple[float, float, float, float]) -> float:
    """Approximate bbox area for UI hints."""
    lon1, lat1, lon2, lat2 = bbox
    width = abs(lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    height = abs(lat2 - lat1) * 110.57
    return abs(width * height)
