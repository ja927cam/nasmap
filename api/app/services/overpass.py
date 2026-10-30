"""Fetch OSM elements from Overpass and turn them into app features.

The result is a normal editable Strata layer. It is a local copy: edits are not
written back to OpenStreetMap.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.validation import explain_validity, make_valid

from ..config import settings
from . import remote

logger = logging.getLogger("nasmap.overpass")

CATEGORIES: dict[str, list[str]] = {
    "buildings": ['nwr["building"]'],
    "landuse": ['nwr["landuse"]'],
    "roads": ['way["highway"]'],
    "waterways": ['nwr["waterway"]'],
    "natural": ['nwr["natural"]'],
    "amenities": ['nwr["amenity"]'],
    "leisure": ['nwr["leisure"]'],
    "boundaries": ['relation["boundary"="administrative"]'],
}

POLYGON_TAGS = {
    "building",
    "landuse",
    "leisure",
    "amenity",
    "place",
    "boundary",
    "landcover",
    "natural",
}


class OverpassError(RuntimeError):
    pass


def build_query(bbox: tuple[float, float, float, float], category: str) -> str:
    filters = CATEGORIES.get(category)
    if not filters:
        raise ValueError(f"Unknown OSM category '{category}'")
    west, south, east, north = bbox
    bbox_clause = f"{south},{west},{north},{east}"
    parts = "\n".join(f"  {item}({bbox_clause});" for item in filters)
    return (
        f"[out:json][timeout:{settings.overpass_timeout_seconds}];\n(\n{parts}\n);\nout geom meta;"
    )


async def fetch_elements(bbox: tuple[float, float, float, float], category: str) -> dict[str, Any]:
    if not settings.overpass_enabled:
        raise OverpassError("OSM data import is disabled")
    try:
        remote.validate_url(settings.overpass_url)
    except remote.UnsafeURLError as exc:
        raise OverpassError(str(exc)) from exc
    query = build_query(bbox, category)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.overpass_timeout_seconds + 15),
            follow_redirects=False,
            headers={"User-Agent": "Strata/1.0 (self-hosted OSM data import)"},
        ) as client:
            response = await client.post(settings.overpass_url, data={"data": query})
    except httpx.HTTPError as exc:
        raise OverpassError(f"Overpass request failed: {exc}") from exc
    if response.status_code >= 400:
        raise OverpassError(f"Overpass returned HTTP {response.status_code}: {response.text[:300]}")
    if len(response.content) > settings.overpass_max_mb * 1024 * 1024:
        raise OverpassError("Overpass response exceeded the configured size limit")
    try:
        payload = response.json()
    except ValueError as exc:
        raise OverpassError("Overpass did not return JSON") from exc
    if payload.get("remark") and not payload.get("elements"):
        raise OverpassError(str(payload.get("remark")))
    return payload


def _coords(geometry: list[dict[str, float]] | None) -> list[tuple[float, float]]:
    if not geometry:
        return []
    return [
        (float(item["lon"]), float(item["lat"]))
        for item in geometry
        if "lon" in item and "lat" in item
    ]


def _closed_ring(coords: list[tuple[float, float]]) -> list[tuple[float, float]] | None:
    if len(coords) < 3:
        return None
    ring = list(coords)
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring if len(ring) >= 4 else None


def _is_polygon(tags: dict[str, str], closed: bool) -> bool:
    if not closed:
        return False
    if tags.get("area") == "yes":
        return True
    if any(key in tags for key in POLYGON_TAGS):
        return True
    return tags.get("waterway") in {"riverbank", "dock"}


def _relation_geometry(element: dict[str, Any], tags: dict[str, str]):
    outers: list[list[tuple[float, float]]] = []
    inners: list[list[tuple[float, float]]] = []
    for member in element.get("members") or []:
        if member.get("type") != "way":
            continue
        ring = _closed_ring(_coords(member.get("geometry")))
        if ring is None:
            continue
        if member.get("role") == "inner":
            inners.append(ring)
        else:
            outers.append(ring)
    if not outers:
        return None, None

    if element.get("tags", {}).get("type") in {"route", "waterway"}:
        return MultiLineString([LineString(ring) for ring in outers]), "MultiLineString"

    polygons = []
    for outer in outers:
        shell = Polygon(outer)
        holes = []
        for inner in inners:
            probe = Point(inner[0])
            if shell.contains(probe) or shell.touches(probe):
                holes.append(inner)
        polygons.append(Polygon(outer, holes))
    if len(polygons) == 1:
        return polygons[0], "Polygon"
    return MultiPolygon(polygons), "MultiPolygon"


def element_geometry(element: dict[str, Any]):
    element_type = element.get("type")
    tags = {str(k): str(v) for k, v in (element.get("tags") or {}).items()}
    if element_type == "node" and element.get("lat") is not None:
        return Point(float(element["lon"]), float(element["lat"])), "Point", tags
    if element_type == "way":
        coords = _coords(element.get("geometry"))
        if len(coords) < 2:
            return None, None, tags
        closed = coords[0] == coords[-1]
        if _is_polygon(tags, closed):
            ring = _closed_ring(coords)
            if ring:
                return Polygon(ring), "Polygon", tags
        return LineString(coords), "LineString", tags
    if element_type == "relation":
        geom, geom_type = _relation_geometry(element, tags)
        return geom, geom_type, tags
    return None, None, tags


def parse_elements(
    payload: dict[str, Any], category: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    skipped = 0
    invalid = 0
    repaired = 0
    geometry_types: set[str] = set()
    elements = payload.get("elements") or []

    for element in elements:
        geom, geom_type, tags = element_geometry(element)
        if geom is None or geom.is_empty:
            skipped += 1
            continue
        props: dict[str, Any] = {
            **tags,
            "osm_type": element.get("type"),
            "osm_id": element.get("id"),
            "osm_version": element.get("version"),
            "osm_timestamp": element.get("timestamp"),
            "osm_user": element.get("user"),
            "osm_changeset": element.get("changeset"),
            "osm_category": category,
        }
        props = {key: value for key, value in props.items() if value is not None}
        if not geom.is_valid:
            invalid += 1
            props["_nasmap_invalid_geometry"] = explain_validity(geom)
            props["_nasmap_original_geometry_wkt"] = geom.wkt
            try:
                geom = make_valid(geom)
                repaired += 1
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
        if geom.is_empty:
            skipped += 1
            continue
        parts = (
            list(geom.geoms)
            if geom.geom_type.startswith(("Multi", "GeometryCollection"))
            else [geom]
        )
        for part in parts:
            if part.is_empty:
                continue
            if not part.is_valid:
                try:
                    part = make_valid(part)
                except Exception:  # noqa: BLE001
                    skipped += 1
                    continue
            if part.is_empty:
                continue
            geometry_types.add(part.geom_type)
            records.append(
                {
                    "properties": props,
                    "geometry": part.wkt,
                    "valid": True,
                    "error": None,
                }
            )

    stats = {
        "elements": len(elements),
        "feature_count": len(records),
        "skipped_count": skipped,
        "invalid_count": invalid,
        "repaired_count": repaired,
        "geometry_types": sorted(geometry_types),
    }
    return records, stats


def guess_geometry_type(geometry_types: list[str]) -> str:
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
