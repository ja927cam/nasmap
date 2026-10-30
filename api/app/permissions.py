"""Layer-level permission checks.

Access is additive: admins see everything, owners control their layers, public
layers are readable by any authenticated user, and explicit grants add read or
write access.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Layer, LayerPermission, User


async def get_layer_or_404(db: AsyncSession, layer_id: str, include_deleted: bool = False) -> Layer:
    layer = await db.get(Layer, layer_id)
    if not layer or (layer.deleted_at is not None and not include_deleted):
        raise HTTPException(status_code=404, detail="Layer not found")
    return layer


async def permission_role(db: AsyncSession, layer: Layer, user: User) -> str | None:
    if user.role == "admin":
        return "owner"
    if layer.owner_id == user.id:
        return "owner"
    row = await db.scalar(
        select(LayerPermission.role).where(
            LayerPermission.layer_id == layer.id, LayerPermission.user_id == user.id
        )
    )
    if row:
        return row
    if layer.visibility == "public":
        return "viewer"
    # "organisation" is treated as an internal, authenticated-only visibility.
    # There is no multi-tenant organisation table in this single-instance app.
    if layer.visibility == "organisation":
        return "viewer"
    return None


def can_read(role: str | None, user: User) -> bool:
    return role in {"owner", "editor", "viewer"} and user.role in {"admin", "editor", "viewer"}


def can_write(role: str | None, user: User) -> bool:
    if user.role not in {"admin", "editor"}:
        return False
    return role in {"owner", "editor"}


async def require_read(db: AsyncSession, layer: Layer, user: User) -> str:
    role = await permission_role(db, layer, user)
    if not can_read(role, user):
        raise HTTPException(status_code=403, detail="You do not have access to this layer")
    return role or "viewer"


async def require_write(db: AsyncSession, layer: Layer, user: User) -> str:
    role = await permission_role(db, layer, user)
    if not can_write(role, user):
        raise HTTPException(status_code=403, detail="You do not have write access to this layer")
    return role or "editor"


async def require_owner(db: AsyncSession, layer: Layer, user: User) -> str:
    role = await permission_role(db, layer, user)
    if role != "owner" or user.role not in {"admin", "editor"}:
        raise HTTPException(status_code=403, detail="Only the layer owner can perform this action")
    return role


async def visible_layers_filter(user: User):
    """SQLAlchemy condition limiting a Layer query to rows the user may read."""
    if user.role == "admin":
        return Layer.deleted_at.is_(None)
    return and_(
        Layer.deleted_at.is_(None),
        or_(
            Layer.owner_id == user.id,
            Layer.visibility.in_(["public", "organisation"]),
            Layer.id.in_(
                select(LayerPermission.layer_id).where(LayerPermission.user_id == user.id)
            ),
        ),
    )
