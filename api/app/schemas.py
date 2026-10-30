"""Shared Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    time: datetime
    services: dict[str, str]


class UserOut(ORMModel):
    id: UUID
    email: str
    display_name: str
    role: str
    is_active: bool
    osm_username: str | None = None
    created_at: datetime


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int
    returned: int


class Paginated(BaseModel):
    meta: PageMeta
    items: list[Any]


class BBoxQuery(BaseModel):
    bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="min_lon,min_lat,max_lon,max_lat"
    )
