"""Authentication, registration and account settings."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..auth import (
    CurrentUser,
    create_access_token,
    create_session,
    hash_password,
    hash_token,
    verify_password,
)
from ..config import settings
from ..database import get_db
from ..models import ApiKey, Session, User
from ..rate_limit import auth_rate_limit
from ..schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "nasmap_refresh"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=256)


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
        domain=settings.cookie_domain or None,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path="/api/v1/auth",
        domain=settings.cookie_domain or None,
    )


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in settings.cors_origin_list:
        raise HTTPException(status_code=403, detail="Origin not allowed")


@router.post("/register", response_model=TokenOut, dependencies=[Depends(auth_rate_limit)])
async def register(
    payload: RegisterIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Serialize first-user bootstrap so two simultaneous registrations cannot
    # both become administrator.
    await db.execute(text("SELECT pg_advisory_xact_lock(7272702)"))
    user_count = int(await db.scalar(select(func.count()).select_from(User)) or 0)
    if not settings.registration_enabled and user_count > 0:
        raise HTTPException(status_code=403, detail="Registration is disabled")
    if await db.scalar(select(User.id).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    is_first = user_count == 0
    role = "admin" if is_first and settings.first_user_is_admin else "viewer"
    user = User(
        email=str(payload.email).lower(),
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip() or str(payload.email).split("@")[0],
        role=role,
        last_login_at=datetime.now(UTC),
    )
    db.add(user)
    await db.flush()

    refresh, _ = await create_session(db, user, request)
    access, expires_in = create_access_token(user)
    audit(db, user, "user.register", "user", user.id, {"role": role}, request)
    await db.commit()
    set_refresh_cookie(response, refresh)
    return TokenOut(access_token=access, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut, dependencies=[Depends(auth_rate_limit)])
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    user.last_login_at = datetime.now(UTC)
    refresh, _ = await create_session(db, user, request)
    access, expires_in = create_access_token(user)
    audit(db, user, "user.login", "user", user.id, request=request)
    await db.commit()
    set_refresh_cookie(response, refresh)
    return TokenOut(access_token=access, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    check_origin(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="No refresh token")
    session = await db.scalar(
        select(Session).where(
            Session.token_hash == hash_token(raw),
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC),
        )
    )
    if not session:
        clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Refresh token is invalid or expired")
    user = await db.get(User, session.user_id)
    if not user or not user.is_active:
        clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Account is unavailable")

    session.revoked_at = datetime.now(UTC)
    new_raw, _ = await create_session(db, user, request)
    access, expires_in = create_access_token(user)
    await db.commit()
    set_refresh_cookie(response, new_raw)
    return TokenOut(access_token=access, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    check_origin(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        session = await db.scalar(select(Session).where(Session.token_hash == hash_token(raw)))
        if session:
            session.revoked_at = datetime.now(UTC)
            await db.commit()
    clear_refresh_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: ProfileIn,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if payload.new_password:
        if user.password_hash and not verify_password(
            payload.current_password or "", user.password_hash
        ):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        user.password_hash = hash_password(payload.new_password)
    audit(db, user, "user.update", "user", user.id, request=request)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/api-keys")
async def list_api_keys(user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    rows = (
        await db.scalars(
            select(ApiKey)
            .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
            .order_by(ApiKey.created_at.desc())
        )
    ).all()
    return [
        ApiKeyOut(
            id=str(r.id),
            name=r.name,
            key_prefix=r.key_prefix,
            scopes=list(r.scopes),
            expires_at=r.expires_at,
            last_used_at=r.last_used_at,
            created_at=r.created_at,
        ).model_dump()
        for r in rows
    ]


@router.post("/api-keys")
async def create_api_key(
    payload: ApiKeyIn,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    raw = "nsk_" + secrets.token_urlsafe(32)
    key = ApiKey(
        user_id=user.id,
        name=payload.name,
        key_prefix=raw[:12],
        key_hash=hash_token(raw),
        scopes=["read", "write"] if user.role in {"admin", "editor"} else ["read"],
        expires_at=(
            datetime.now(UTC) + timedelta(days=payload.expires_in_days)
            if payload.expires_in_days
            else None
        ),
    )
    db.add(key)
    audit(db, user, "api_key.create", "api_key", key.id, {"name": payload.name}, request)
    await db.commit()
    return {
        "id": str(key.id),
        "name": key.name,
        "key": raw,
        "key_prefix": key.key_prefix,
        "scopes": key.scopes,
        "expires_at": key.expires_at,
    }


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    key = await db.get(ApiKey, key_id)
    if not key or key.user_id != user.id:
        raise HTTPException(status_code=404, detail="API key not found")
    key.revoked_at = datetime.now(UTC)
    audit(db, user, "api_key.revoke", "api_key", key.id, request=request)
    await db.commit()
    return {"ok": True}
