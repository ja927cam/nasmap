"""Raster inspection, COG conversion and XYZ tile rendering."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.shutil import copy as rio_copy
from rasterio.warp import transform_bounds
from rio_tiler.errors import TileOutsideBounds
from rio_tiler.io import COGReader
from rio_tiler.models import ImageData

logger = logging.getLogger("nasmap.raster")
_TRANSPARENT_TILE = ImageData(np.zeros((4, 256, 256), dtype=np.uint8)).render(
    img_format="PNG", add_mask=False
)


def ensure_cog(source: Path, destination: Path) -> Path:
    """Convert a GeoTIFF to a Cloud Optimized GeoTIFF.

    GDAL's COG driver is preferred. Older GDAL builds fall back to a tiled,
    compressed GTiff with internal overviews, which is still range-readable.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        rio_copy(
            source,
            destination,
            driver="COG",
            compress="DEFLATE",
            BIGTIFF="IF_SAFER",
            OVERVIEW_RESAMPLING="AVERAGE",
        )
        logger.info("converted %s to COG via COG driver", source.name)
        return destination
    except Exception as exc:  # noqa: BLE001
        logger.warning("COG driver failed (%s); falling back to tiled GTiff", exc)
        with rasterio.open(source) as src:
            profile = src.profile.copy()
            profile.update(
                driver="GTiff",
                tiled=True,
                blockxsize=256,
                blockysize=256,
                compress="deflate",
                BIGTIFF="IF_SAFER",
            )
            with rasterio.open(destination, "w", **profile) as dst:
                dst.write(src.read())
            with rasterio.open(destination, "r+") as dst:
                factors = []
                width, height = dst.width, dst.height
                factor = 2
                while width // factor >= 256 and height // factor >= 256 and factor <= 16:
                    factors.append(factor)
                    factor *= 2
                if factors:
                    dst.build_overviews(factors, Resampling.average)
                    dst.update_tags(ns="rio_overview", resampling="average")
        return destination


def inspect_raster(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as src:
        bounds = src.bounds
        if src.crs and src.crs.to_string() != "EPSG:4326":
            left, bottom, right, top = transform_bounds(
                src.crs, "EPSG:4326", *bounds, densify_pts=21
            )
        else:
            left, bottom, right, top = bounds.left, bounds.bottom, bounds.right, bounds.top
        overviews = src.overviews(1) if src.count else []
        nodata = src.nodata
        try:
            if nodata is not None and not math.isfinite(float(nodata)):
                nodata = None
        except (TypeError, ValueError):
            nodata = None
        resolution = [abs(src.transform.a), abs(src.transform.e)]
        if not all(math.isfinite(value) for value in resolution):
            resolution = [None, None]
        bounds_wgs84 = [
            float(value) if math.isfinite(float(value)) else None
            for value in (left, bottom, right, top)
        ]
        return {
            "crs": src.crs.to_string() if src.crs else None,
            "bounds_wgs84": bounds_wgs84,
            "width": src.width,
            "height": src.height,
            "band_count": src.count,
            "dtype": src.dtypes[0] if src.dtypes else None,
            "nodata": nodata,
            "resolution": resolution,
            "overviews": overviews,
            "driver": src.driver,
            "is_cog": src.driver == "GTiff" and bool(overviews),
        }


def _indexes(band_count: int, requested: list[int] | None) -> list[int] | None:
    if band_count <= 3:
        return None
    if requested:
        indexes = [int(b) for b in requested if 1 <= int(b) <= band_count]
        if indexes:
            return indexes[:3]
    return [1, 2, 3]


def transparent_tile() -> bytes:
    return _TRANSPARENT_TILE


def render_tile(source: str, z: int, x: int, y: int, bands: list[int] | None = None) -> bytes:
    with COGReader(source) as cog:
        indexes = _indexes(cog.dataset.count, bands)
        try:
            image = cog.tile(x, y, z, tilesize=256, indexes=indexes)
        except TileOutsideBounds:
            return _TRANSPARENT_TILE
        ranges = []
        for band in image.array:
            valid = band[np.isfinite(band)]
            if valid.size == 0:
                ranges.append((0.0, 1.0))
                continue
            low = float(np.nanmin(valid))
            high = float(np.nanmax(valid))
            if high <= low:
                high = low + 1.0
            ranges.append((low, high))
        image = image.rescale(in_range=tuple(ranges))
        return image.render(img_format="PNG")


def raster_statistics(source: str, max_size: int = 1024) -> dict[str, Any]:
    with COGReader(source) as cog:
        image = cog.preview(max_size=max_size, indexes=[1] if cog.dataset.count else None)
        array = image.array
        if array.size == 0:
            return {}
        return {
            "min": float(np.nanmin(array)),
            "max": float(np.nanmax(array)),
            "mean": float(np.nanmean(array)),
        }
