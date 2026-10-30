"""Audit log helper."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditLog, User


def audit(
    db: AsyncSession,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        details=details or {},
        ip_address=(request.client.host if request and request.client else None),
    )
    db.add(entry)
    return entry
