"""Raster XYZ tiles, WMS proxying and raster downloads."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser
from ..config import settings
from ..database import get_db
from ..permissions import get_layer_or_404, require_read
from ..services import live, raster, remote

router = APIRouter(tags=["raster"])
logger = logging.getLogger("nasmap.tiles")


def raster_source(layer) -> str:
    metadata = layer.metadata_ or {}
    source = metadata.get("raster_path") or (metadata.get("raster") or {}).get("path")
    remote_url = metadata.get("raster_url")
    if source and Path(source).exists():
        return str(source)
    if remote_url:
        return str(remote_url)
    raise HTTPException(status_code=404, detail="Raster source is not available on disk")


async def _remote_overlay_tile(layer, z: int, x: int, y: int) -> tuple[bytes, str, str]:
    metadata = layer.metadata_ or {}
    xyz = dict(metadata.get("xyz") or {})
    template = xyz.get("url")
    cache_variant = ""
    rain = metadata.get("rainviewer")
    if rain:
        if not settings.rainviewer_enabled:
            raise HTTPException(status_code=503, detail="RainViewer is disabled")
        try:
            host, path = await live.rainviewer_frame()
        except live.LiveDataError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        template = live.rainviewer_template(
            host,
            path,
            int(rain.get("color") or 4),
            str(rain.get("options") or "1_1"),
        )
        cache_variant = hashlib.sha1(template.encode()).hexdigest()[:10]
    if not template:
        raise HTTPException(status_code=422, detail="Overlay has no XYZ tile URL")
    minzoom = int(xyz.get("minzoom") or 0)
    maxzoom = int(xyz.get("maxzoom") or 22)
    if z < minzoom or z > maxzoom:
        return raster.transparent_tile(), "image/png", "no-cache"

    fetch_y = (2**z) - 1 - y if xyz.get("scheme") == "tms" else y
    url = (
        str(template)
        .replace("{s}", "a")
        .replace("{z}", str(z))
        .replace("{x}", str(x))
        .replace("{y}", str(fetch_y))
    )
    try:
        remote.validate_url(url)
    except remote.UnsafeURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = f"{y}-{cache_variant}.png" if cache_variant else f"{y}.png"
    cache_path = settings.tiles_dir / "overlays" / str(layer.id) / str(z) / str(x) / filename
    ttl_seconds = max(1, settings.overlay_tile_cache_ttl_hours) * 3600
    try:
        if cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < ttl_seconds:
            return cache_path.read_bytes(), "image/png", "private, max-age=3600"
    except OSError:
        pass

    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=False,
            headers={"User-Agent": "Strata/1.0 (self-hosted raster overlay proxy)"},
        ) as client:
            upstream = await client.get(url)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Overlay tile upstream error: {exc}") from exc
    if upstream.status_code in {204, 404}:
        return raster.transparent_tile(), "image/png", "no-cache"
    if upstream.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Overlay tile server returned HTTP {upstream.status_code}",
        )
    content_type = upstream.headers.get("content-type", "image/png").split(";")[0]
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=502, detail="Overlay returned a non-image tile")
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_bytes(upstream.content)
        tmp.replace(cache_path)
    except OSError as exc:
        logger.warning("could not cache overlay tile: %s", exc)
    return upstream.content, content_type, "private, max-age=3600"


@router.get("/layers/{layer_id}/tiles/{z}/{x}/{y}.png")
async def raster_tile(
    layer_id: str,
    z: int,
    x: int,
    y: int,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    layer = await get_layer_or_404(db, layer_id)
    await require_read(db, layer, user)
    if layer.geometry_type != "raster":
        raise HTTPException(status_code=422, detail="Layer is not a raster layer")
    if not (0 <= z <= 22):
        raise HTTPException(status_code=422, detail="Invalid zoom level")
    max_tile = (2**z) - 1
    if not (0 <= x <= max_tile and 0 <= y <= max_tile):
        raise HTTPException(status_code=422, detail="Tile coordinates are out of range")
    if isinstance((layer.metadata_ or {}).get("xyz"), dict):
        content, media_type, cache_control = await _remote_overlay_tile(layer, z, x, y)
        return Response(
            content=content, media_type=media_type, headers={"Cache-Control": cache_control}
        )
    source = raster_source(layer)
    style = layer.style or {}
    bands = style.get("bands") if isinstance(style, dict) else None
    try:
        content = await asyncio.to_thread(raster.render_tile, source, z, x, y, bands)
    except Exception as exc:  # noqa: BLE001
        logger.exception("raster tile failed for layer %s", layer.id)
        raise HTTPException(status_code=502, detail=f"Could not render raster tile: {exc}") from exc
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/layers/{layer_id}/wms")
async def wms_proxy(
    layer_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    bbox: str = Query(..., description="minx,miny,maxx,maxy in EPSG:3857"),
    width: int = Query(default=256, ge=1, le=2048),
    height: int = Query(default=256, ge=1, le=2048),
    transparent: bool = True,
):
    layer = await get_layer_or_404(db, layer_id)
    await require_read(db, layer, user)
    metadata = layer.metadata_ or {}
    wms = metadata.get("wms") or {}
    url = wms.get("url")
    layers = wms.get("layers")
    if not url or not layers:
        raise HTTPException(status_code=422, detail="Layer has no WMS configuration")
    try:
        remote.validate_url(url)
        [float(v) for v in bbox.split(",")]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid WMS request: {exc}") from exc
    version = wms.get("version") or "1.3.0"
    params = {
        "service": "WMS",
        "request": "GetMap",
        "version": version,
        "layers": layers,
        "styles": wms.get("styles") or "",
        "format": wms.get("format") or "image/png",
        "transparent": str(transparent).lower(),
        "width": width,
        "height": height,
        "bbox": bbox,
    }
    if version.startswith("1.3"):
        params["crs"] = "EPSG:3857"
    else:
        params["srs"] = "EPSG:3857"
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            upstream = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"WMS upstream error: {exc}") from exc
    if upstream.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"WMS upstream returned HTTP {upstream.status_code}"
        )
    content_type = upstream.headers.get("content-type", "image/png").split(";")[0]
    if "xml" in content_type or "text" in content_type:
        raise HTTPException(status_code=502, detail="WMS server returned an error document")
    return Response(
        content=upstream.content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/layers/{layer_id}/download")
async def download_raster(
    layer_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    layer = await get_layer_or_404(db, layer_id)
    await require_read(db, layer, user)
    if layer.geometry_type != "raster":
        raise HTTPException(status_code=400, detail="Layer is not a raster layer")
    metadata = layer.metadata_ or {}
    path = metadata.get("raster_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Raster file is not available")
    filename = "".join(c if c.isalnum() or c in "-_" else "_" for c in layer.name) + ".tif"
    return FileResponse(path, media_type="image/tiff", filename=filename)


@router.get("/basemap/osm/{z}/{x}/{y}.png", include_in_schema=False)
async def remote_basemap_tile(z: int, x: int, y: int):
    """Cached, on-demand proxy for the configured remote OSM raster tiles.

    This endpoint is public because the basemap is not private data. It never
    prefetches: one upstream request per cache miss, with a bounded disk cache.
    """
    if not settings.osm_tile_proxy:
        raise HTTPException(status_code=404, detail="Remote tile proxy is disabled")
    if not (0 <= z <= 22):
        raise HTTPException(status_code=422, detail="Invalid zoom level")
    max_tile = (2**z) - 1
    if not (0 <= x <= max_tile and 0 <= y <= max_tile):
        raise HTTPException(status_code=422, detail="Tile coordinates are out of range")

    cache_path = settings.tiles_dir / "remote-osm" / str(z) / str(x) / f"{y}.png"
    ttl_seconds = max(1, settings.osm_tile_cache_ttl_days) * 86400
    try:
        if cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < ttl_seconds:
            return Response(
                content=cache_path.read_bytes(),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"},
            )
    except OSError:
        pass

    try:
        url = settings.osm_tile_url.format(z=z, x=x, y=y)
        remote.validate_url(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Invalid OSM tile URL: {exc}") from exc
    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=False,
            headers={
                "User-Agent": "Strata/1.0 (self-hosted OpenStreetMap basemap; on-demand cache)"
            },
        ) as client:
            upstream = await client.get(url)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OSM tile upstream error: {exc}") from exc
    if upstream.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="OpenStreetMap tile server is rate-limiting requests",
            headers={"Retry-After": "60"},
        )
    if upstream.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"OSM tile server returned HTTP {upstream.status_code}"
        )
    content_type = upstream.headers.get("content-type", "image/png").split(";")[0]
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=502, detail="OSM tile server returned a non-image response")
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_bytes(upstream.content)
        tmp.replace(cache_path)
    except OSError as exc:
        logger.warning("could not cache remote tile: %s", exc)
    return Response(
        content=upstream.content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
