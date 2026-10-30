"""Generic raster overlay providers: XYZ, TileJSON and WMS.

A layer is the overlay: provider configuration is stored in layer.metadata and
the tile endpoint proxies XYZ/TMS sources through the API so API keys stay
server-side and browsers do not need CORS access to third-party services.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..auth import EditorUser
from ..database import get_db
from ..models import Layer
from ..services import remote
from .layers import serialize_layer

router = APIRouter(prefix="/overlays", tags=["overlays"])
logger = logging.getLogger("nasmap.overlays")

PROVIDERS = [
    {
        "id": "xyz",
        "label": "XYZ / TMS tiles",
        "description": "Raster tile URL template with {z}, {x} and {y}.",
        "kind": "raster",
    },
    {
        "id": "tilejson",
        "label": "TileJSON",
        "description": "Fetch a TileJSON document and use its raster tiles.",
        "kind": "raster",
    },
    {
        "id": "wms",
        "label": "WMS",
        "description": "OGC Web Map Service layer, proxied through NasMap.",
        "kind": "raster",
    },
    {
        "id": "cog",
        "label": "GeoTIFF / COG URL",
        "description": "Download a remote GeoTIFF/COG and create a raster layer.",
        "kind": "raster-job",
    },
    {
        "id": "tessera",
        "label": "Tessera embeddings",
        "description": "Download GeoTessera embeddings and add them as a COG layer.",
        "kind": "raster-job",
    },
]


class OverlayBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    visibility: Literal["private", "organisation", "public"] = "private"
    attribution: str = Field(default="", max_length=1000)
    licence: str = Field(default="", max_length=500)
    bounds: list[float] | None = Field(default=None, min_length=4, max_length=4)


class XYZOverlayIn(OverlayBase):
    url_template: str = Field(min_length=8, max_length=4000)
    tile_size: int = Field(default=256, ge=64, le=1024)
    minzoom: int = Field(default=0, ge=0, le=22)
    maxzoom: int = Field(default=20, ge=0, le=22)
    scheme: Literal["xyz", "tms"] = "xyz"


class TileJSONOverlayIn(OverlayBase):
    tilejson_url: str = Field(min_length=8, max_length=4000)


class WMSOverlayIn(OverlayBase):
    url: str = Field(min_length=8, max_length=4000)
    layers: str = Field(min_length=1, max_length=1000)
    styles: str = Field(default="", max_length=1000)
    version: str = Field(default="1.3.0", max_length=10)
    format: str = Field(default="image/png", max_length=50)
    transparent: bool = True


def _validate_template(template: str) -> str:
    if not all(token in template for token in ("{z}", "{x}", "{y}")):
        raise HTTPException(
            status_code=422,
            detail="Tile URL template must contain {z}, {x} and {y}",
        )
    probe = template.replace("{z}", "0").replace("{x}", "0").replace("{y}", "0")
    probe = probe.replace("{s}", "a")
    try:
        remote.validate_url(probe)
    except remote.UnsafeURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return template


def _bounds(value: list[float] | None) -> list[float]:
    if value is None:
        return [-180, -85, 180, 85]
    west, south, east, north = value
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise HTTPException(status_code=422, detail="bounds must be west,south,east,north")
    return value


def _new_overlay(
    user,
    name: str,
    visibility: str,
    attribution: str,
    licence: str,
    metadata: dict[str, Any],
) -> Layer:
    return Layer(
        owner_id=user.id,
        name=name,
        description="",
        visibility=visibility,
        geometry_type="raster",
        source_type="url",
        style={"opacity": 1},
        metadata_=metadata,
        attribution=attribution,
        licence=licence,
    )


async def _save(db: AsyncSession, layer: Layer, request: Request, user) -> dict:
    db.add(layer)
    await db.flush()
    audit(
        db,
        user,
        "overlay.create",
        "layer",
        layer.id,
        {"provider": (layer.metadata_ or {}).get("provider")},
        request,
    )
    await db.commit()
    await db.refresh(layer)
    return serialize_layer(layer, "owner")


@router.get("/providers")
async def providers(user: EditorUser):
    return {"providers": PROVIDERS}


@router.post("/xyz", status_code=201)
async def create_xyz(
    payload: XYZOverlayIn,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    template = _validate_template(payload.url_template)
    if payload.minzoom > payload.maxzoom:
        raise HTTPException(status_code=422, detail="minzoom cannot exceed maxzoom")
    layer = _new_overlay(
        user,
        payload.name,
        payload.visibility,
        payload.attribution,
        payload.licence,
        {
            "provider": "xyz",
            "total_bounds": _bounds(payload.bounds),
            "xyz": {
                "url": template,
                "tile_size": payload.tile_size,
                "minzoom": payload.minzoom,
                "maxzoom": payload.maxzoom,
                "scheme": payload.scheme,
            },
        },
    )
    return await _save(db, layer, request, user)


@router.post("/tilejson", status_code=201)
async def create_tilejson(
    payload: TileJSONOverlayIn,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        remote.validate_url(payload.tilejson_url)
    except remote.UnsafeURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        with tempfile.TemporaryDirectory(prefix="nasmap-tilejson-") as tmp:
            fetched = await remote.fetch_remote_to_file(payload.tilejson_url, Path(tmp), max_mb=5)
            document = json.loads(fetched.path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not read TileJSON: {exc}") from exc
    tiles = document.get("tiles") or []
    if not tiles or not isinstance(tiles[0], str):
        raise HTTPException(status_code=422, detail="TileJSON does not contain a raster tile URL")
    tile_url = str(httpx.URL(payload.tilejson_url).join(tiles[0]))
    template = _validate_template(tile_url)
    bounds = document.get("bounds")
    if bounds and (not isinstance(bounds, list) or len(bounds) != 4):
        bounds = None
    metadata = {
        "provider": "tilejson",
        "source_url": payload.tilejson_url,
        "total_bounds": _bounds(bounds if bounds else payload.bounds),
        "xyz": {
            "url": template,
            "tile_size": int(document.get("tileSize") or 256),
            "minzoom": int(document.get("minzoom") or 0),
            "maxzoom": int(document.get("maxzoom") or 20),
            "scheme": "tms" if document.get("scheme") == "tms" else "xyz",
            "tilejson_url": payload.tilejson_url,
        },
    }
    layer = _new_overlay(
        user,
        payload.name,
        payload.visibility,
        payload.attribution or str(document.get("attribution") or ""),
        payload.licence,
        metadata,
    )
    return await _save(db, layer, request, user)


@router.post("/wms", status_code=201)
async def create_wms(
    payload: WMSOverlayIn,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        remote.validate_url(payload.url)
    except remote.UnsafeURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    layer = _new_overlay(
        user,
        payload.name,
        payload.visibility,
        payload.attribution,
        payload.licence,
        {
            "provider": "wms",
            "total_bounds": _bounds(payload.bounds),
            "wms": {
                "url": payload.url,
                "layers": payload.layers,
                "styles": payload.styles,
                "version": payload.version,
                "format": payload.format,
                "transparent": payload.transparent,
            },
        },
    )
    return await _save(db, layer, request, user)
