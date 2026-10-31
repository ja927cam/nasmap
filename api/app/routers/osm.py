"""OSM OAuth sign-in and preview/confirm changeset publishing."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..auth import CurrentUser, create_session
from ..config import settings
from ..database import get_db
from ..models import Feature, Layer, OAuthState, OsmPublication, User
from ..permissions import get_layer_or_404, require_write
from ..rate_limit import upload_rate_limit
from ..services import osm as osm_service
from ..services import overpass
from .auth import set_refresh_cookie

router = APIRouter(prefix="/osm", tags=["osm"])
logger = logging.getLogger("nasmap.osm")
OSM_STATE_COOKIE = "nasmap_osm_state"


class AuthorizeIn(BaseModel):
    redirect_to: str | None = Field(default=None, max_length=500)


class NearbyIn(BaseModel):
    feature_id: UUID
    radius_m: int = Field(default=50, ge=5, le=200)


class PreviewIn(BaseModel):
    feature_id: UUID
    comment: str = Field(min_length=3, max_length=255)
    source: str = Field(default="Strata", max_length=255)
    tags: dict[str, str] | None = None
    changeset_tags: dict[str, str] = Field(default_factory=dict)
    osm_id: int | None = Field(default=None, gt=0)
    osm_type: Literal["node"] | None = None
    force_create: bool = False


class PublishIn(PreviewIn):
    confirm: bool = False
    dry_run: bool = False


async def _load_feature(
    db: AsyncSession, feature_id: UUID, user: User
) -> tuple[Feature, Layer, dict, tuple[float, float]]:
    feature = await db.get(Feature, feature_id)
    if not feature or feature.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Feature not found")
    layer = await get_layer_or_404(db, feature.layer_id)
    await require_write(db, layer, user)
    geometry_json = await db.scalar(select(func.ST_AsGeoJSON(feature.geometry)))
    if not geometry_json:
        raise HTTPException(status_code=422, detail="Feature has no geometry")
    geometry = json.loads(geometry_json)
    lat, lon = osm_service.parse_lat_lon(geometry)
    return feature, layer, geometry, (lat, lon)


async def _prepare(
    feature: Feature, payload: PreviewIn, geometry: dict[str, Any]
) -> tuple[dict[str, str], str, str, int | None, int | None, dict[str, str], float, float]:
    props = feature.properties or {}
    osm_id: int | None = None
    osm_version: int | None = None
    existing_tags: dict[str, str] = {}
    node: dict[str, Any] | None = None
    if payload.osm_type not in (None, "node"):
        raise HTTPException(status_code=422, detail="Only OSM nodes are supported")
    if not payload.force_create:
        if payload.osm_id:
            osm_id = payload.osm_id
        elif props.get("osm_id"):
            try:
                osm_id = int(props["osm_id"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="Stored osm_id is invalid") from None
    if osm_id:
        node = await osm_service.fetch_node(osm_id)
        if not node:
            raise HTTPException(status_code=404, detail="OSM node no longer exists")
        lat = float(node["lat"])
        lon = float(node["lon"])
        osm_version = int(node.get("version") or 1)
        existing_tags = osm_service.clean_tags(node.get("tags") or {})
    else:
        lat, lon = osm_service.parse_lat_lon(geometry)
    local_tags = osm_service.clean_tags(payload.tags if payload.tags is not None else props)
    tags = osm_service.merge_tags(existing_tags, local_tags)
    if not tags:
        raise HTTPException(status_code=422, detail="At least one OSM tag is required")
    changeset_xml = osm_service.changeset_xml(
        payload.comment, payload.source, payload.changeset_tags
    )
    diff_xml = osm_service.osm_change_xml(
        lat=lat, lon=lon, tags=tags, osm_id=osm_id, osm_version=osm_version
    )
    return tags, changeset_xml, diff_xml, osm_id, osm_version, existing_tags, lat, lon


@router.get("/status")
async def osm_status(user: CurrentUser):
    return {
        "enabled": osm_service.oauth_enabled(),
        "connected": bool(user.osm_access_token_enc),
        "username": user.osm_username,
        "osm_user_id": user.osm_user_id,
        "api_base_url": settings.osm_api_base_url,
        "scopes": settings.osm_scope_list,
    }


@router.post("/authorize")
async def authorize(
    payload: AuthorizeIn,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not osm_service.oauth_enabled():
        raise HTTPException(status_code=400, detail="OSM OAuth is not configured")
    state = osm_service.new_state()
    db.add(
        OAuthState(
            state=state,
            user_id=user.id,
            provider="osm",
            redirect_to=payload.redirect_to,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    await db.commit()
    return {"authorization_url": osm_service.authorization_url(state), "state": state}


@router.get("/login")
async def login(redirect_to: str = "/"):
    """Start OSM OAuth sign-in for an already-linked or auto-created account."""
    if not osm_service.oauth_enabled():
        raise HTTPException(status_code=400, detail="OSM OAuth is not configured")
    target = (
        redirect_to if redirect_to.startswith("/") and not redirect_to.startswith("//") else "/"
    )
    state = osm_service.login_state(target)
    response = RedirectResponse(osm_service.login_authorization_url(state))
    response.set_cookie(
        OSM_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/v1/osm",
    )
    return response


async def _osm_login_callback(db: AsyncSession, request: Request, code: str, state: str):
    payload = osm_service.decode_login_state(state)
    if not payload:
        return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/login?osm=error")
    try:
        tokens = await osm_service.exchange_code(code)
        identity = await osm_service.fetch_identity(tokens["access_token"])
        osm_id = int(identity["id"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("OSM sign-in failed: %s", exc)
        return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/login?osm=error")

    user = await db.scalar(select(User).where(User.osm_user_id == osm_id))
    if not user:
        if not settings.osm_signin_auto_create or not settings.registration_enabled:
            return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/login?osm=no_account")
        email = f"osm-{osm_id}@users.noreply.nasmap"
        if await db.scalar(select(User).where(User.email == email)):
            return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/login?osm=error")
        user = User(
            email=email,
            display_name=identity.get("display_name") or f"OSM user {osm_id}",
            role="viewer",
            is_active=True,
        )
        db.add(user)
        await db.flush()
    if not user.is_active:
        return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/login?osm=disabled")
    user.osm_user_id = osm_id
    user.osm_username = identity.get("display_name")
    osm_service.store_tokens(user, tokens)
    refresh, _ = await create_session(db, user, request)
    audit(db, user, "osm.login", "user", user.id, request=request)
    await db.commit()
    redirect_to = payload.get("redirect_to") or "/"
    if (
        not isinstance(redirect_to, str)
        or not redirect_to.startswith("/")
        or redirect_to.startswith("//")
    ):
        redirect_to = "/"
    response = RedirectResponse(f"{settings.frontend_url.rstrip('/')}{redirect_to}")
    set_refresh_cookie(response, refresh)
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if state and osm_service.decode_login_state(state):
        cookie_state = request.cookies.get(OSM_STATE_COOKIE)
        if not cookie_state or cookie_state != state:
            return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/login?osm=error")
        response = (
            RedirectResponse(f"{settings.frontend_url.rstrip('/')}/login?osm=error")
            if error or not code
            else await _osm_login_callback(db, request, code, state)
        )
        response.delete_cookie(OSM_STATE_COOKIE, path="/api/v1/osm")
        return response
    return await _link_callback(code=code, state=state, error=error, db=db)


async def _link_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    target = f"{settings.frontend_url.rstrip('/')}/settings"
    if not state:
        return RedirectResponse(f"{target}?osm=error")
    stored = await db.get(OAuthState, state)
    if not stored or stored.expires_at < datetime.now(UTC):
        return RedirectResponse(f"{target}?osm=error")
    user = await db.get(User, stored.user_id)
    await db.delete(stored)
    await db.commit()
    if error or not code or not user:
        return RedirectResponse(f"{target}?osm=error")
    try:
        tokens = await osm_service.exchange_code(code)
        identity = await osm_service.fetch_identity(tokens["access_token"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("OSM OAuth callback failed: %s", exc)
        return RedirectResponse(f"{target}?osm=error")
    user.osm_user_id = int(identity.get("id")) if identity.get("id") else None
    user.osm_username = identity.get("display_name")
    osm_service.store_tokens(user, tokens)
    await db.commit()
    return RedirectResponse(f"{target}?osm=connected")


@router.post("/disconnect")
async def disconnect(
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user.osm_access_token_enc = None
    user.osm_refresh_token_enc = None
    user.osm_token_expires_at = None
    user.osm_username = None
    audit(db, user, "osm.disconnect", "user", user.id, request=request)
    await db.commit()
    return {"ok": True}


@router.post("/nearby", dependencies=[Depends(upload_rate_limit)])
async def nearby(
    payload: NearbyIn,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _, _, _, (lat, lon) = await _load_feature(db, payload.feature_id, user)
    try:
        nodes = await overpass.fetch_nearby_nodes(lat, lon, payload.radius_m)
    except overpass.OverpassError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "feature_id": str(payload.feature_id),
        "radius_m": payload.radius_m,
        "nodes": nodes,
    }


@router.post("/preview")
async def preview(
    payload: PreviewIn,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    feature, layer, geometry, _ = await _load_feature(db, payload.feature_id, user)
    tags, changeset_xml, diff_xml, osm_id, osm_version, existing_tags, lat, lon = await _prepare(
        feature, payload, geometry
    )
    return {
        "feature_id": str(feature.id),
        "layer_id": str(layer.id),
        "action": "modify" if osm_id else "create",
        "osm_type": "node",
        "osm_id": osm_id,
        "osm_version": osm_version,
        "lat": lat,
        "lon": lon,
        "tags": tags,
        "existing_tags": existing_tags,
        "comment": payload.comment,
        "source": payload.source,
        "changeset_xml": changeset_xml,
        "diff_xml": diff_xml,
        "warning": (
            "This will create a new OpenStreetMap node. Review tags carefully; "
            "uploads are permanent public edits."
            if not osm_id
            else (
                f"This will update existing OpenStreetMap node {osm_id}. Existing "
                "OSM tags are kept, the node is not moved, and uploads are permanent."
            )
        ),
    }


@router.post("/publish")
async def publish(
    payload: PublishIn,
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    feature, layer, geometry, _ = await _load_feature(db, payload.feature_id, user)
    tags, changeset_xml, diff_xml, osm_id, osm_version, _, lat, lon = await _prepare(
        feature, payload, geometry
    )
    publication = OsmPublication(
        user_id=user.id,
        feature_id=feature.id,
        layer_id=layer.id,
        status="preview",
        comment=payload.comment,
        diff_xml=diff_xml,
    )
    db.add(publication)

    if payload.dry_run:
        publication.status = "dry_run"
        publication.finished_at = datetime.now(UTC)
        audit(
            db,
            user,
            "osm.dry_run",
            "feature",
            feature.id,
            {"comment": payload.comment, "osm_id": osm_id},
            request,
        )
        await db.commit()
        return {
            "dry_run": True,
            "action": "modify" if osm_id else "create",
            "changeset_xml": changeset_xml,
            "diff_xml": diff_xml,
            "tags": tags,
            "osm_id": osm_id,
            "message": "Dry run only - nothing was sent to OpenStreetMap.",
        }

    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required to publish")
    if not osm_service.oauth_enabled():
        raise HTTPException(status_code=400, detail="OSM OAuth is not configured")

    access_token = await osm_service.valid_access_token(db, user)
    changeset_id: int | None = None
    try:
        if osm_id and (not osm_version or osm_version < 1):
            current = await osm_service.fetch_node_version(access_token, osm_id)
            if not current:
                raise HTTPException(status_code=404, detail="OSM node no longer exists")
            osm_version = int(current.get("version", 1))
            diff_xml = osm_service.osm_change_xml(
                lat=lat, lon=lon, tags=tags, osm_id=osm_id, osm_version=osm_version
            )
            publication.diff_xml = diff_xml

        changeset_id = await osm_service.create_changeset(access_token, changeset_xml)
        diff_xml = osm_service.osm_change_xml(
            lat=lat,
            lon=lon,
            tags=tags,
            osm_id=osm_id,
            osm_version=osm_version,
            changeset_id=changeset_id,
        )
        publication.diff_xml = diff_xml
        result = await osm_service.upload_diff(access_token, changeset_id, diff_xml)
        await osm_service.close_changeset(access_token, changeset_id)
        publication.changeset_id = changeset_id
        publication.status = "published"
        publication.response = result
        publication.finished_at = datetime.now(UTC)
        new_nodes = result.get("nodes") or []
        node = new_nodes[0] if new_nodes else {}
        resolved_id = int(node.get("new_id") or node.get("old_id") or osm_id or 0)
        resolved_version = int(node.get("new_version") or osm_version or 0)
        if resolved_id:
            feature.properties = {
                **(feature.properties or {}),
                "osm_type": "node",
                "osm_id": resolved_id,
                **({"osm_version": resolved_version} if resolved_version else {}),
                "osm_changeset": changeset_id,
            }
        publication.osm_type = "node"
        publication.osm_id = resolved_id or osm_id
        feature.updated_by = user.id
        audit(
            db,
            user,
            "osm.publish",
            "feature",
            feature.id,
            {"changeset_id": changeset_id, "osm_id": publication.osm_id},
            request,
        )
        await db.commit()
        return {
            "published": True,
            "changeset_id": changeset_id,
            "changeset_url": f"{settings.osm_api_base_url}/changeset/{changeset_id}",
            "osm_id": publication.osm_id,
            "result": result,
        }
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        publication.status = "failed"
        publication.error = str(exc)[:2000]
        publication.finished_at = datetime.now(UTC)
        if changeset_id:
            try:
                await osm_service.close_changeset(access_token, changeset_id)
            except Exception:  # noqa: BLE001
                pass
        audit(db, user, "osm.publish_failed", "feature", feature.id, {"error": str(exc)}, request)
        await db.commit()
        raise HTTPException(status_code=502, detail=f"OpenStreetMap upload failed: {exc}") from exc
