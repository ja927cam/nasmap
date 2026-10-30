"""Vector geodata detection, validation, conversion and export.

GDAL is used through pyogrio/geopandas. Both ship binary GDAL wheels, which
keeps the Docker image self-contained while preserving support for the common
OGR drivers (GeoJSON, GPKG, Shapefile, KML, KMZ, GPX, CSV).
"""

from __future__ import annotations

import json
import logging
import math
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely import wkt as shapely_wkt
from shapely.geometry import Point, mapping, shape
from shapely.validation import explain_validity, make_valid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Feature, Layer

logger = logging.getLogger("nasmap.geodata")

VECTOR_EXTENSIONS = {
    ".geojson": "geojson",
    ".json": "geojson",
    ".gpkg": "gpkg",
    ".zip": "shapefile",
    ".shp": "shapefile",
    ".kml": "kml",
    ".kmz": "kmz",
    ".gpx": "gpx",
    ".csv": "csv",
    ".fgb": "flatgeobuf",
    ".gml": "gml",
    ".dxf": "dxf",
    ".parquet": "parquet",
}
RASTER_EXTENSIONS = {".tif": "cog", ".tiff": "cog"}
EXPORT_MEDIA_TYPES = {
    "geojson": "application/geo+json",
    "gpkg": "application/geopackage+sqlite3",
    "kml": "application/vnd.google-earth.kml+xml",
    "csv": "text/csv",
}
EXPORT_DRIVERS = {"geojson": "GeoJSON", "gpkg": "GPKG", "kml": "KML"}


class UnsupportedFormatError(ValueError):
    pass


def detect_kind(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in VECTOR_EXTENSIONS:
        return VECTOR_EXTENSIONS[suffix]
    if suffix in RASTER_EXTENSIONS:
        return RASTER_EXTENSIONS[suffix]
    raise UnsupportedFormatError(
        f"Unsupported file type '{suffix or 'unknown'}'. "
        "Supported: GeoJSON, GeoPackage, Shapefile ZIP, KML, KMZ, GPX, CSV, "
        "FlatGeobuf, GeoParquet, GML, DXF, GeoTIFF/COG."
    )


def is_raster(filename: str) -> bool:
    return Path(filename).suffix.lower() in RASTER_EXTENSIONS


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if pd.isna(value):
        return None
    return value


def _properties(record: dict[str, Any]) -> dict[str, Any]:
    return {str(k): _jsonable(v) for k, v in record.items() if not str(k).startswith("__")}


def _read_csv(path: Path) -> gpd.GeoDataFrame:
    frame: pd.DataFrame | None = None
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            frame = pd.read_csv(path, encoding=encoding, low_memory=False)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if frame is None:
        raise ValueError(f"Could not read CSV: {last_error}")
    if frame.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    lowered = {c.lower().strip(): c for c in frame.columns}
    geom_col = next(
        (lowered[k] for k in ("geometry", "wkt", "geom", "geojson") if k in lowered), None
    )
    lon_col = next((lowered[k] for k in ("longitude", "lon", "lng", "x") if k in lowered), None)
    lat_col = next((lowered[k] for k in ("latitude", "lat", "y") if k in lowered), None)

    geometries = []
    props = []
    if geom_col:
        values = frame[geom_col].astype(str)
        is_geojson = (
            geom_col.lower().strip() == "geojson" or values.str.strip().str.startswith("{").any()
        )
        for idx, value in enumerate(values):
            record = frame.drop(columns=[geom_col]).iloc[idx].to_dict()
            try:
                geom = shape(json.loads(value)) if is_geojson else shapely_wkt.loads(value)
            except Exception:  # noqa: BLE001
                geom = None
            geometries.append(geom)
            props.append(record)
    elif lon_col and lat_col:
        for _, row in frame.iterrows():
            try:
                lon = float(row[lon_col])
                lat = float(row[lat_col])
                geom = Point(lon, lat) if -180 <= lon <= 180 and -90 <= lat <= 90 else None
            except (TypeError, ValueError):
                geom = None
            record = row.drop(labels=[lon_col, lat_col]).to_dict()
            geometries.append(geom)
            props.append(record)
    else:
        raise ValueError(
            "CSV needs a longitude/latitude pair (lon/lat, longitude/latitude, x/y), "
            "a WKT column, or a GeoJSON geometry column."
        )

    result = gpd.GeoDataFrame(props, geometry=geometries, crs="EPSG:4326")
    return result


def _resolve_archive(path: Path) -> str:
    """Return a GDAL /vsizip/ path for zipped vector datasets."""
    if path.suffix.lower() not in {".zip", ".kmz"}:
        return str(path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    wanted = [".shp"] if path.suffix.lower() == ".zip" else [".kml"]
    wanted += [".gpkg", ".kml"]
    for member in names:
        if Path(member).suffix.lower() in wanted:
            return f"/vsizip/{path}/{member}"
    raise ValueError("ZIP/KMZ does not contain a supported vector file (.shp, .gpkg or .kml)")


def read_vector(path: Path) -> gpd.GeoDataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv(path)
    if suffix == ".parquet":
        try:
            frame = gpd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Could not read GeoParquet: {exc}") from exc
        if frame.crs is None:
            frame = frame.set_crs("EPSG:4326", allow_override=True)
        else:
            frame = frame.to_crs("EPSG:4326")
        return frame
    source = _resolve_archive(path)
    try:
        frame = gpd.read_file(source)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"GDAL could not open this dataset: {exc}") from exc
    if frame.crs is None:
        logger.warning("dataset %s has no CRS; assuming EPSG:4326", path.name)
        frame = frame.set_crs("EPSG:4326", allow_override=True)
    else:
        frame = frame.to_crs("EPSG:4326")
    return frame


def normalize_features(frame: gpd.GeoDataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate geometries and return import-ready records.

    Invalid geometries are repaired with shapely.make_valid when possible and
    the original WKT is retained in a property so nothing is silently lost.
    """
    records: list[dict[str, Any]] = []
    invalid = 0
    repaired = 0
    null_geometries = 0
    geom_types: set[str] = set()
    for _, row in frame.iterrows():
        geom = row.geometry
        prop = _properties({k: v for k, v in row.items() if k != "geometry"})
        if geom is None or geom.is_empty:
            null_geometries += 1
            records.append(
                {
                    "properties": prop,
                    "geometry": None,
                    "valid": False,
                    "error": "Empty or null geometry",
                }
            )
            continue
        if not geom.is_valid:
            invalid += 1
            prop["_nasmap_invalid_geometry"] = explain_validity(geom)
            prop["_nasmap_original_geometry_wkt"] = geom.wkt
            try:
                geom = make_valid(geom)
                repaired += 1
            except Exception:  # noqa: BLE001
                records.append(
                    {
                        "properties": prop,
                        "geometry": geom.wkt,
                        "valid": False,
                        "error": explain_validity(geom),
                    }
                )
                continue
        geom_types.add(geom.geom_type)
        records.append({"properties": prop, "geometry": geom.wkt, "valid": True, "error": None})
    stats = {
        "feature_count": len(records),
        "invalid_count": invalid,
        "repaired_count": repaired,
        "null_geometry_count": null_geometries,
        "geometry_types": sorted(geom_types),
    }
    return records, stats


def guess_layer_geometry(geometry_types: Iterable[str]) -> str:
    types = set(geometry_types)
    if not types:
        return "geometry"
    if types <= {"Point", "MultiPoint"}:
        return "point"
    if types <= {"LineString", "MultiLineString"}:
        return "line"
    if types <= {"Polygon", "MultiPolygon"}:
        return "polygon"
    return "geometry"


def inspect_vector(path: Path) -> dict[str, Any]:
    frame = read_vector(path)
    records, stats = normalize_features(frame)
    crs = frame.crs.to_string() if frame.crs else "EPSG:4326"
    bounds = None
    if len(frame.index):
        raw = frame.total_bounds.tolist()
        if all(math.isfinite(float(value)) for value in raw):
            bounds = [float(value) for value in raw]
    return {
        "records": records,
        "stats": stats,
        "crs": crs,
        "layer_crs": frame.crs.to_string() if frame.crs else "EPSG:4326",
        "geometry_type": guess_layer_geometry(stats["geometry_types"]),
        "bounds": bounds,
    }


def records_to_geojson(records: list[dict[str, Any]]) -> dict[str, Any]:
    features = []
    for record in records:
        if not record.get("geometry"):
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(shapely_wkt.loads(record["geometry"])),
                "properties": record.get("properties", {}),
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _safe_tempdir() -> Path:
    path = Path(tempfile.mkdtemp(prefix="nasmap-export-"))
    return path


def cleanup_exports(max_age_seconds: int = 86400) -> None:
    import time

    root = Path(tempfile.gettempdir())
    now = time.time()
    for item in root.glob("nasmap-export-*"):
        try:
            if item.is_dir() and now - item.stat().st_mtime > max_age_seconds:
                shutil.rmtree(item, ignore_errors=True)
        except OSError:
            continue


async def export_layer_file(db: AsyncSession, layer: Layer, fmt: str) -> tuple[Path, str, str]:
    rows = (
        await db.execute(
            select(Feature.properties, func.ST_AsGeoJSON(Feature.geometry)).where(
                Feature.layer_id == layer.id, Feature.deleted_at.is_(None)
            )
        )
    ).all()
    records = []
    for properties, geom_json in rows:
        if not geom_json:
            continue
        clean = {
            key: value
            for key, value in (properties or {}).items()
            if not str(key).startswith("_nasmap")
        }
        records.append({"properties": clean, "geometry": geom_json})

    directory = _safe_tempdir()
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in layer.name)[:60] or "layer"
    if fmt == "csv":
        rows_out = []
        for record in records:
            geom = json.loads(record["geometry"])
            row = dict(record["properties"])
            row["geometry_wkt"] = shape(geom).wkt
            rows_out.append(row)
        path = directory / f"{safe_name}.csv"
        pd.DataFrame(rows_out).to_csv(path, index=False)
        return path, EXPORT_MEDIA_TYPES[fmt], path.name

    if fmt == "geojson":
        path = directory / f"{safe_name}.geojson"
        path.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": json.loads(record["geometry"]),
                            "properties": record["properties"],
                        }
                        for record in records
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path, EXPORT_MEDIA_TYPES[fmt], path.name

    driver = EXPORT_DRIVERS.get(fmt)
    if not driver:
        raise ValueError(f"Unsupported export format: {fmt}")
    geometries = [shape(json.loads(record["geometry"])) for record in records]
    frame = gpd.GeoDataFrame(
        [record["properties"] for record in records], geometry=geometries, crs="EPSG:4326"
    )
    extension = "gpkg" if fmt == "gpkg" else "kml"
    path = directory / f"{safe_name}.{extension}"
    frame.to_file(path, driver=driver, engine="pyogrio")
    return path, EXPORT_MEDIA_TYPES[fmt], path.name


def read_geojson_geometry(value: dict[str, Any] | str):
    geom = shapely_wkt.loads(value) if isinstance(value, str) else shape(value)
    return geom


def crs_axis_order(crs: CRS) -> str:
    return f"{crs.to_string()} ({'geographic' if crs.is_geographic else 'projected'})"
