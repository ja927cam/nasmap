"""Generic raster overlay providers: XYZ, TileJSON and WMS.

A layer is the overlay: provider configuration is stored in layer.metadata and
the tile endpoint proxies XYZ/TMS sources through the API so API keys stay
server-side and browsers do not need CORS access to third-party services.
"""

from __future__ import annotations

import json
import logging
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..auth import CurrentUser, EditorUser
from ..database import get_db
from ..models import Layer
from ..rate_limit import auth_rate_limit
from ..services import remote
from .layers import serialize_layer

router = APIRouter(prefix="/overlays", tags=["overlays"])
logger = logging.getLogger("nasmap.overlays")

PRESETS = [
    {
        "id": "opentopomap",
        "label": "OpenTopoMap",
        "provider": "xyz",
        "description": "Topographic map with contours and hillshade.",
        "attribution": "© OpenStreetMap contributors, SRTM | © OpenTopoMap (CC-BY-SA)",
        "licence": "CC BY-SA 3.0",
        "config": {
            "url_template": "https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
            "tile_size": 256,
            "minzoom": 0,
            "maxzoom": 17,
            "scheme": "xyz",
        },
    },
    {
        "id": "openseamap",
        "label": "OpenSeaMap",
        "provider": "xyz",
        "description": "Seamark and navigation overlay.",
        "attribution": "© OpenSeaMap contributors",
        "licence": "CC BY-SA 2.0",
        "config": {
            "url_template": "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png",
            "tile_size": 256,
            "minzoom": 0,
            "maxzoom": 18,
            "scheme": "xyz",
        },
    },
    {
        "id": "esri-world-imagery",
        "label": "Esri World Imagery",
        "provider": "xyz",
        "description": "Satellite and aerial imagery.",
        "attribution": "Tiles © Esri",
        "licence": "Esri terms of use",
        "config": {
            "url_template": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            "tile_size": 256,
            "minzoom": 0,
            "maxzoom": 19,
            "scheme": "xyz",
        },
    },
    {
        "id": "sentinel-2-cloudless",
        "label": "Sentinel-2 cloudless",
        "provider": "xyz",
        "description": "EOX Sentinel-2 cloudless 2023 mosaic.",
        "attribution": "Sentinel-2 cloudless by EOX (CC BY-NC-SA 4.0)",
        "licence": "CC BY-NC-SA 4.0",
        "config": {
            "url_template": "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg",
            "tile_size": 256,
            "minzoom": 0,
            "maxzoom": 18,
            "scheme": "xyz",
        },
    },
    {
        "id": "nasa-gibs",
        "label": "NASA GIBS true colour",
        "provider": "wms",
        "description": "NASA VIIRS daily true-colour imagery.",
        "attribution": "NASA Global Imagery Browse Services (GIBS)",
        "licence": "NASA imagery usage policy",
        "config": {
            "url": "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi",
            "layers": "VIIRS_SNPP_CorrectedReflectance_TrueColor",
            "version": "1.3.0",
            "format": "image/jpeg",
            "transparent": False,
        },
    },
]

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
        "description": "OGC Web Map Service layer, proxied through Strata.",
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


class WMSCapabilitiesIn(BaseModel):
    url: str = Field(min_length=8, max_length=4000)


class VectorTileOverlayIn(OverlayBase):
    tilejson_url: str = Field(min_length=8, max_length=4000)
    source_layer: str = Field(default="", max_length=200)
    color: str = Field(default="#7c3aed", max_length=20)
    minzoom: int = Field(default=0, ge=0, le=22)
    maxzoom: int = Field(default=14, ge=0, le=22)


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
        remote.validate_url_syntax(probe)
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
async def providers(user: CurrentUser):
    return {"providers": PROVIDERS, "presets": PRESETS}


@router.get("/presets")
async def presets(user: CurrentUser):
    return PRESETS


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


@router.post("/vectortile", status_code=201)
async def create_vectortile(
    payload: VectorTileOverlayIn,
    request: Request,
    user: EditorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        remote.validate_url(payload.tilejson_url)
    except remote.UnsafeURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        with tempfile.TemporaryDirectory(prefix="nasmap-vector-tilejson-") as tmp:
            fetched = await remote.fetch_remote_to_file(payload.tilejson_url, Path(tmp), max_mb=5)
            document = json.loads(fetched.path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not read TileJSON: {exc}") from exc
    tiles = document.get("tiles") or []
    if not tiles or not isinstance(tiles[0], str):
        raise HTTPException(status_code=422, detail="TileJSON does not contain a tile URL")
    template = _validate_template(str(httpx.URL(payload.tilejson_url).join(tiles[0])))
    source_layer = payload.source_layer
    if not source_layer:
        vector_layers = document.get("vector_layers") or []
        source_layer = str(vector_layers[0].get("id")) if vector_layers else ""
    if not source_layer:
        raise HTTPException(
            status_code=422,
            detail=(
                "Vector TileJSON needs a source layer; add one manually if the "
                "document does not list it"
            ),
        )
    bounds = document.get("bounds")
    if bounds and (not isinstance(bounds, list) or len(bounds) != 4):
        bounds = None
    metadata = {
        "provider": "vectortile",
        "source_url": payload.tilejson_url,
        "total_bounds": _bounds(bounds if bounds else payload.bounds),
        "vector_tiles": {
            "url": template,
            "source_layer": source_layer,
            "minzoom": int(document.get("minzoom") or payload.minzoom),
            "maxzoom": int(document.get("maxzoom") or payload.maxzoom),
            "tilejson_url": payload.tilejson_url,
        },
    }
    layer = Layer(
        owner_id=user.id,
        name=payload.name,
        description="Vector tile overlay.",
        visibility=payload.visibility,
        geometry_type="geometry",
        source_type="url",
        style={
            "color": payload.color,
            "fillColor": payload.color,
            "fillOpacity": 0.16,
            "lineWidth": 1.1,
            "circleRadius": 4,
        },
        metadata_=metadata,
        attribution=payload.attribution,
        licence=payload.licence,
    )
    return await _save(db, layer, request, user)


@router.post("/wms/capabilities", dependencies=[Depends(auth_rate_limit)])
async def wms_capabilities(
    payload: WMSCapabilitiesIn,
    user: CurrentUser,
):
    request_url = payload.url
    if "request=" not in request_url.lower():
        separator = "&" if "?" in request_url else "?"
        request_url = f"{request_url}{separator}service=WMS&request=GetCapabilities&version=1.3.0"
    try:
        remote.validate_url(request_url)
    except remote.UnsafeURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        with tempfile.TemporaryDirectory(prefix="nasmap-wms-") as tmp:
            fetched = await remote.fetch_remote_to_file(request_url, Path(tmp), max_mb=10)
            root = ET.fromstring(fetched.path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Could not read WMS capabilities: {exc}"
        ) from exc

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    version = root.attrib.get("version", "")
    layers = []
    for element in root.iter():
        if local(element.tag) != "Layer":
            continue
        name = ""
        title = ""
        for child in element:
            if local(child.tag) == "Name" and child.text:
                name = child.text.strip()
            elif local(child.tag) == "Title" and child.text:
                title = child.text.strip()
        if name:
            layers.append({"name": name, "title": title or name})
        if len(layers) >= 500:
            break
    if not layers:
        raise HTTPException(status_code=422, detail="No named layers found in WMS capabilities")
    return {"version": version, "layers": layers}


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
