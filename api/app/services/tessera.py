"""Adapter around the official geotessera Python package.

Only documented GeoTessera APIs are used:
  * ``GeoTessera`` / ``registry.load_blocks_for_region`` for coverage
  * ``export_embedding_geotiffs`` for tile -> GeoTIFF export
  * ``merge_geotiffs_to_mosaic`` for a web-friendly mosaic

The package is imported lazily so the API remains usable when Tessera support
is disabled or the optional data registry cannot be reached.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import settings

logger = logging.getLogger("nasmap.tessera")


class TesseraUnavailable(RuntimeError):
    pass


@dataclass
class TesseraTile:
    year: int
    lon: float
    lat: float

    @property
    def id(self) -> str:
        return f"{self.year}_{self.lon:.2f}_{self.lat:.2f}"

    @property
    def bbox(self) -> list[float]:
        return [self.lon - 0.05, self.lat - 0.05, self.lon + 0.05, self.lat + 0.05]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "year": self.year,
            "lon": self.lon,
            "lat": self.lat,
            "bbox": self.bbox,
        }


def _import_geotessera():
    try:
        from geotessera import GeoTessera  # type: ignore
        from geotessera import registry as gt_registry  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise TesseraUnavailable(
            "The geotessera package is not installed in this container. "
            "Rebuild the API image or set TESSERA_ENABLED=false."
        ) from exc
    return GeoTessera, gt_registry


def _version_key(version: str) -> str:
    return version.strip().lstrip("v")


def make_client(year: int | None = None, variant: str | None = None, bbox=None):
    GeoTessera, _ = _import_geotessera()
    version = settings.tessera_version
    variant = variant if variant is not None else (settings.tessera_variant or None)
    kwargs: dict[str, Any] = {
        "dataset_version": version,
        "dataset_variant": variant or None,
        "cache_dir": settings.tessera_cache_dir / "registry",
        "embeddings_dir": settings.tessera_cache_dir / "tiles",
    }
    if settings.tessera_registry_url:
        kwargs["registry_url"] = settings.tessera_registry_url
    if bbox is not None:
        # The registry ignores tiles whose centres fall outside bbox+margin.
        # Keep the package default margin so edge tiles intersecting the box
        # are still listed.
        kwargs["bbox"] = bbox
    return GeoTessera(**kwargs)


def available_variants(version: str | None = None) -> list[str]:
    _, gt_registry = _import_geotessera()
    key = _version_key(version or settings.tessera_version)
    try:
        variants = gt_registry.known_variants(key)
    except Exception:  # noqa: BLE001
        variants = []
    if not variants:
        return [settings.tessera_variant or "cambridge"]
    preferred = settings.tessera_variant
    if preferred in variants:
        variants = [preferred] + [variant for variant in variants if variant != preferred]
    return variants


def available_years() -> list[int]:
    client = make_client()
    return sorted(int(y) for y in client.registry.get_available_years())


def coverage(
    bbox: tuple[float, float, float, float], year: int, variant: str | None = None
) -> dict[str, Any]:
    _validate_bbox(bbox)
    client = make_client(bbox=bbox, variant=variant)
    tiles = client.registry.load_blocks_for_region(bounds=bbox, year=year)
    parsed = []
    for tile in tiles:
        if len(tile) == 3:
            tile_year, lon, lat = tile
        else:
            tile_year, (lon, lat) = year, tile
        parsed.append(TesseraTile(int(tile_year), float(lon), float(lat)))
    years = sorted(int(y) for y in client.registry.get_available_years())
    return {
        "bbox": list(bbox),
        "year": year,
        "variant": client.dataset_variant,
        "version": client.dataset_version,
        "tile_count": len(parsed),
        "tiles": [tile.as_dict() for tile in parsed],
        "available_years": years,
        "available_variants": available_variants(),
        "max_tiles": settings.tessera_max_tiles,
        "crs": "native UTM per tile; exports are reprojected for web display",
        "resolution": "10 m (0.1 degree tiles, 1000x1000 px)",
        "band_count": 128,
        "licence": "Tessera embeddings - see https://geotessera.readthedocs.io for dataset terms",
        "attribution": "Tessera / GeoTessera satellite embeddings",
        "coverage_within_limit": len(parsed) <= settings.tessera_max_tiles,
    }


def _validate_bbox(bbox: tuple[float, float, float, float]) -> None:
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise ValueError("bbox must be min_lon,min_lat,max_lon,max_lat within valid ranges")
    if (max_lon - min_lon) * (max_lat - min_lat) > 25:
        raise ValueError("Tessera imports are limited to a 25 square-degree area per job")


def import_region(
    bbox: tuple[float, float, float, float],
    year: int,
    output_dir: Path,
    variant: str | None = None,
    bands: list[int] | None = None,
    progress: Callable[[int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    _validate_bbox(bbox)
    output_dir.mkdir(parents=True, exist_ok=True)
    client = make_client(bbox=bbox, variant=variant)
    tiles = client.registry.load_blocks_for_region(bounds=bbox, year=year)
    if not tiles:
        raise ValueError("No Tessera tiles are available for this bounding box and year")
    if len(tiles) > settings.tessera_max_tiles:
        raise ValueError(
            f"Area contains {len(tiles)} tiles; the configured limit is "
            f"{settings.tessera_max_tiles}. Narrow the bounding box or raise TESSERA_MAX_TILES."
        )

    def on_progress(current: int, total: int, message: str = "") -> None:
        if is_cancelled and is_cancelled():
            raise TesseraCancelled("Import cancelled by user")
        if progress and total:
            pct = min(80, int(current / total * 80))
            progress(pct, message or f"Processing tile {current}/{total}")

    if progress:
        progress(2, f"Downloading {len(tiles)} Tessera tile(s)")

    # Export individual tiles with native UTM references (useful to GIS users).
    files = client.export_embedding_geotiffs(
        tiles,
        output_dir=output_dir / "tiles",
        bands=bands,
        progress_callback=on_progress,
    )
    if not files:
        raise ValueError("Tessera export produced no GeoTIFF files")

    if progress:
        progress(82, "Mosaicking tiles for web display")
    mosaic_path = output_dir / f"tessera_{year}_{_safe_variant(client.dataset_variant)}.tif"
    try:
        client.merge_geotiffs_to_mosaic(
            files,
            output_path=mosaic_path,
            target_crs="EPSG:3857",
            compress="lzw",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("mosaic creation failed (%s); using first tile as raster layer", exc)
        mosaic_path = Path(files[0])

    if progress:
        progress(92, "Finalising raster layer")
    return {
        "mosaic_path": str(mosaic_path),
        "tile_files": files,
        "tile_count": len(files),
        "year": year,
        "variant": client.dataset_variant,
        "version": client.dataset_version,
        "tiles": [{"year": t[0], "lon": t[1], "lat": t[2]} for t in tiles],
    }


class TesseraCancelled(RuntimeError):
    pass


def _safe_variant(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (value or "default"))
