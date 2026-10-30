"""OpenStreetMap OAuth 2.0 and controlled changeset publishing."""

from __future__ import annotations

import logging
import secrets
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from typing import Any
from xml.sax.saxutils import escape, quoteattr

import httpx
import jwt
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import decrypt_secret, encrypt_secret
from ..config import settings
from ..models import User

logger = logging.getLogger("nasmap.osm")

INTERNAL_PROPERTY_PREFIXES = ("_nasmap", "osm_")
INTERNAL_PROPERTIES = {"geometry_wkt", "created_by", "updated_at"}


class OSMError(RuntimeError):
    pass


def oauth_enabled() -> bool:
    return bool(
        settings.osm_oauth_enabled and settings.osm_client_id and settings.osm_client_secret
    )


def authorization_url(state: str) -> str:
    if not oauth_enabled():
        raise HTTPException(status_code=400, detail="OSM OAuth is not configured")
    from urllib.parse import urlencode

    query = urlencode(
        {
            "client_id": settings.osm_client_id,
            "redirect_uri": settings.osm_redirect_uri,
            "response_type": "code",
            "scope": " ".join(settings.osm_scope_list),
            "state": state,
        }
    )
    return f"{settings.osm_auth_url}?{query}"


def new_state() -> str:
    return secrets.token_urlsafe(32)


def login_state(redirect_to: str = "/") -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "typ": "osm_login",
            "nonce": secrets.token_urlsafe(16),
            "redirect_to": redirect_to,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
            "iss": "nasmap",
        },
        settings.secret_key,
        algorithm="HS256",
    )


def decode_login_state(state: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            state,
            settings.secret_key,
            algorithms=["HS256"],
            issuer="nasmap",
            options={"require": ["exp", "typ"]},
        )
    except jwt.InvalidTokenError:
        return None
    if payload.get("typ") != "osm_login":
        return None
    return payload


def login_authorization_url(state: str) -> str:
    if not oauth_enabled():
        raise HTTPException(status_code=400, detail="OSM OAuth is not configured")
    from urllib.parse import urlencode

    query = urlencode(
        {
            "client_id": settings.osm_client_id,
            "redirect_uri": settings.osm_redirect_uri,
            "response_type": "code",
            "scope": " ".join(settings.osm_scope_list),
            "state": state,
        }
    )
    return f"{settings.osm_auth_url}?{query}"


async def exchange_code(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            settings.osm_token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.osm_redirect_uri,
                "client_id": settings.osm_client_id,
                "client_secret": settings.osm_client_secret,
            },
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        raise OSMError(f"OSM token exchange failed: {response.status_code} {response.text[:300]}")
    return response.json()


async def refresh_token(refresh: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            settings.osm_token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": settings.osm_client_id,
                "client_secret": settings.osm_client_secret,
            },
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        raise OSMError("Could not refresh the OSM session; reconnect your OSM account")
    return response.json()


async def fetch_identity(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{settings.osm_api_base_url}/api/0.6/user/details.json",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
    if response.status_code >= 400:
        raise OSMError("Could not read the OSM profile")
    payload = response.json()
    return payload.get("user", payload)


def store_tokens(user: User, payload: dict[str, Any]) -> None:
    user.osm_access_token_enc = encrypt_secret(payload["access_token"])
    if payload.get("refresh_token"):
        user.osm_refresh_token_enc = encrypt_secret(payload["refresh_token"])
    expires_in = payload.get("expires_in")
    user.osm_token_expires_at = (
        datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
    )


async def valid_access_token(db: AsyncSession, user: User) -> str:
    access = decrypt_secret(user.osm_access_token_enc)
    refresh = decrypt_secret(user.osm_refresh_token_enc)
    if not access:
        raise HTTPException(status_code=400, detail="Connect your OpenStreetMap account first")
    if user.osm_token_expires_at and user.osm_token_expires_at <= datetime.now(UTC) + timedelta(
        seconds=30
    ):
        if not refresh:
            raise HTTPException(
                status_code=401, detail="OSM session expired; reconnect your account"
            )
        payload = await refresh_token(refresh)
        store_tokens(user, payload)
        await db.commit()
        access = payload["access_token"]
    return access


def clean_tags(properties: dict[str, Any]) -> dict[str, str]:
    tags: dict[str, str] = {}
    for key, value in (properties or {}).items():
        if key in INTERNAL_PROPERTIES or str(key).startswith(INTERNAL_PROPERTY_PREFIXES):
            continue
        if value is None or isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if text:
            tags[str(key)] = text
    return tags


def changeset_xml(comment: str, source: str, extra_tags: dict[str, str] | None = None) -> str:
    tags = {
        "created_by": "NasMap",
        "comment": comment,
        "source": source or "NasMap",
        **(extra_tags or {}),
    }
    tag_xml = "".join(
        f"<tag k={quoteattr(k)} v={quoteattr(str(v))}/>" for k, v in tags.items() if str(v).strip()
    )
    return f'<osm version="0.6" generator="NasMap"><changeset>{tag_xml}</changeset></osm>'


def osm_change_xml(
    *,
    lat: float,
    lon: float,
    tags: dict[str, str],
    osm_id: int | None,
    osm_version: int | None,
    changeset_id: int | None = None,
    action: str = "auto",
) -> str:
    tag_xml = "".join(
        f"<tag k={quoteattr(k)} v={quoteattr(str(v))}/>"
        for k, v in tags.items()
        if k and str(v).strip()
    )
    changeset_attr = f' changeset="{int(changeset_id)}"' if changeset_id else ""
    if osm_id:
        version_attr = f' version="{int(osm_version or 1)}"'
        node = (
            f'<node id="{int(osm_id)}"{version_attr}{changeset_attr} lat="{lat:.7f}" '
            f'lon="{lon:.7f}">{tag_xml}</node>'
        )
        return f'<osmChange version="0.6" generator="NasMap"><modify>{node}</modify></osmChange>'
    node = f'<node id="-1"{changeset_attr} lat="{lat:.7f}" lon="{lon:.7f}">{tag_xml}</node>'
    return f'<osmChange version="0.6" generator="NasMap"><create>{node}</create></osmChange>'


async def fetch_node_version(access_token: str, osm_id: int) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{settings.osm_api_base_url}/api/0.6/node/{osm_id}.json",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise OSMError(f"Could not fetch OSM node {osm_id}: HTTP {response.status_code}")
    elements = response.json().get("elements", [])
    return elements[0] if elements else None


async def create_changeset(access_token: str, xml: str) -> int:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.put(
            f"{settings.osm_api_base_url}/api/0.6/changeset/create",
            content=xml,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "text/xml",
            },
        )
    if response.status_code >= 400:
        raise OSMError(
            f"OSM changeset creation failed: {response.status_code} {response.text[:500]}"
        )
    try:
        return int(response.text.strip())
    except ValueError as exc:
        raise OSMError("OSM returned an unexpected changeset id") from exc


async def upload_diff(access_token: str, changeset_id: int, diff_xml: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.osm_api_base_url}/api/0.6/changeset/{changeset_id}/upload",
            content=diff_xml,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "text/xml",
            },
        )
    if response.status_code >= 400:
        raise OSMError(f"OSM upload failed: {response.status_code} {response.text[:1000]}")
    result: dict[str, Any] = {"raw": response.text}
    try:
        root = ET.fromstring(response.text)
        nodes = []
        for node in root.iter("node"):
            nodes.append(
                {
                    "old_id": node.get("old_id"),
                    "new_id": node.get("new_id"),
                    "new_version": node.get("new_version"),
                }
            )
        result["nodes"] = nodes
    except ET.ParseError:
        pass
    return result


async def close_changeset(access_token: str, changeset_id: int) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.put(
            f"{settings.osm_api_base_url}/api/0.6/changeset/{changeset_id}/close",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code >= 400:
        logger.warning("failed to close changeset %s: %s", changeset_id, response.status_code)


def parse_lat_lon(geometry: dict[str, Any]) -> tuple[float, float]:
    if not geometry or geometry.get("type") != "Point":
        raise HTTPException(
            status_code=422,
            detail="Only point features can be published to OSM in this release",
        )
    coordinates = geometry.get("coordinates") or []
    if len(coordinates) < 2:
        raise HTTPException(status_code=422, detail="Feature has no coordinates")
    lon, lat = float(coordinates[0]), float(coordinates[1])
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise HTTPException(status_code=422, detail="Coordinates are outside WGS84 ranges")
    return lat, lon


def escape_xml_text(value: str) -> str:
    return escape(value)
