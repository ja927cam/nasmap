"""Password hashing, JWT tokens, API keys and FastAPI auth dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import SessionLocal, get_db
from .models import ApiKey, Session, User

logger = logging.getLogger("nasmap.auth")
password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user: User) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": "nasmap",
    }
    token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
    return token, settings.access_token_ttl_minutes * 60


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            issuer="nasmap",
            options={"require": ["sub", "exp", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid access token") from exc
    if payload.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    return payload


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet() -> Fernet:
    if settings.osm_token_encryption_key:
        raw = settings.osm_token_encryption_key.encode()
        try:
            return Fernet(raw)
        except ValueError:
            key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
            return Fernet(key)
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        logger.error("could not decrypt stored OAuth token; encryption key changed?")
        return None


def safe_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


async def create_session(
    db: AsyncSession,
    user: User,
    request: Request,
) -> tuple[str, Session]:
    token = new_refresh_token()
    session = Session(
        user_id=user.id,
        token_hash=hash_token(token),
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
        ip_address=request.client.host if request.client else None,
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
    )
    db.add(session)
    await db.flush()
    return token, session


async def _user_from_api_key(db: AsyncSession, raw_key: str) -> User | None:
    if not raw_key.startswith("nsk_"):
        return None
    prefix = raw_key[:12]
    digest = hash_token(raw_key)
    result = await db.execute(
        select(ApiKey, User)
        .join(User, User.id == ApiKey.user_id)
        .where(ApiKey.key_prefix == prefix, ApiKey.key_hash == digest, ApiKey.revoked_at.is_(None))
    )
    row = result.first()
    if not row:
        return None
    api_key, user = row
    if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
        return None
    if not user.is_active:
        return None
    api_key.last_used_at = datetime.now(UTC)
    return user


async def resolve_user(request: Request, db: AsyncSession) -> User | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        payload = decode_access_token(auth.split(" ", 1)[1].strip())
        try:
            user_id = payload["sub"]
        except KeyError:
            return None
        user = await db.get(User, user_id)
        return user if user and user.is_active else None

    api_key = request.headers.get("x-api-key")
    if api_key:
        return await _user_from_api_key(db, api_key.strip())
    return None


async def get_current_user(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> User:
    user = await resolve_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_optional_user(request: Request) -> User | None:
    async with SessionLocal() as db:
        return await resolve_user(request, db)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_editor(user: CurrentUser) -> User:
    if user.role not in {"admin", "editor"}:
        raise HTTPException(status_code=403, detail="Editor access required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
EditorUser = Annotated[User, Depends(require_editor)]
