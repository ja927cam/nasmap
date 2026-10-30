"""Administrative endpoints for users, audit and system overview."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..auth import AdminUser
from ..database import get_db
from ..models import AuditLog, ImportJob, User
from ..schemas import UserOut

router = APIRouter(prefix="/admin", tags=["admin"])


class UserUpdate(BaseModel):
    role: Literal["admin", "editor", "viewer"] | None = None
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=120)


@router.get("/users")
async def list_users(
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = Query(default=None, max_length=200),
    role: Literal["admin", "editor", "viewer"] | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    conditions = []
    if q:
        conditions.append(or_(User.email.ilike(f"%{q}%"), User.display_name.ilike(f"%{q}%")))
    if role:
        conditions.append(User.role == role)
    where = conditions[0] if conditions else True
    for condition in conditions[1:]:
        where = where & condition
    total = int(await db.scalar(select(func.count()).select_from(User).where(where)) or 0)
    users = (
        await db.scalars(
            select(User).where(where).order_by(User.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return {
        "items": [UserOut.model_validate(user).model_dump() for user in users],
        "meta": {"total": total, "limit": limit, "offset": offset, "returned": len(users)},
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    payload: UserUpdate,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    if user.id == admin.id and payload.role not in {None, "admin"}:
        raise HTTPException(status_code=400, detail="You cannot remove your own admin role")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(user, key, value)
    audit(db, admin, "admin.user_update", "user", user.id, {"fields": list(changes)}, request)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/audit")
async def audit_log(
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    action: str | None = Query(default=None, max_length=100),
    entity_type: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    conditions = []
    if action:
        conditions.append(AuditLog.action == action)
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    where = conditions[0] if conditions else True
    for condition in conditions[1:]:
        where = where & condition
    rows = (
        await db.scalars(
            select(AuditLog)
            .where(where)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        {
            "id": row.id,
            "user_id": str(row.user_id) if row.user_id else None,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "details": row.details,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/overview")
async def overview(admin: AdminUser, db: Annotated[AsyncSession, Depends(get_db)]):
    counts = {}
    for table, key in (
        ("app.users", "users"),
        ("app.layers", "layers"),
        ("app.features", "features"),
        ("imports.import_jobs", "import_jobs"),
        ("imports.external_sources", "external_sources"),
    ):
        from sqlalchemy import text

        counts[key] = int(await db.scalar(text(f"SELECT count(*) FROM {table}")) or 0)
    active_jobs = int(
        await db.scalar(
            select(func.count())
            .select_from(ImportJob)
            .where(ImportJob.status.in_(["queued", "running"]))
        )
        or 0
    )
    recent = (
        await db.scalars(select(ImportJob).order_by(ImportJob.created_at.desc()).limit(10))
    ).all()
    return {
        "counts": counts,
        "active_jobs": active_jobs,
        "recent_jobs": [
            {
                "id": str(job.id),
                "type": job.job_type,
                "status": job.status,
                "progress": job.progress,
                "created_at": job.created_at,
            }
            for job in recent
        ],
        "server_time": datetime.now(UTC),
    }
