"""Live data adapters: RainViewer radar, Open-Meteo weather points, USGS quakes."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from ..config import settings
from . import remote

logger = logging.getLogger("nasmap.live")

_rain_cache: tuple[float, str, str] | None = None
_RAIN_TTL = 300


class LiveDataError(RuntimeError):
    pass


def wmo_description(code: int | None) -> str:
    values = {
        0: "Clear",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Drizzle",
        55: "Heavy drizzle",
        56: "Freezing drizzle",
        57: "Heavy freezing drizzle",
        61: "Light rain",
        63: "Rain",
        65: "Heavy rain",
        66: "Freezing rain",
        67: "Heavy freezing rain",
        71: "Light snow",
        73: "Snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Light rain showers",
        81: "Rain showers",
        82: "Violent rain showers",
        85: "Light snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Thunderstorm with heavy hail",
    }
    return values.get(int(code) if code is not None else -1, "Unknown")


async def rainviewer_frame(force: bool = False) -> tuple[str, str]:
    """Return ``(host, radar_path)`` for the latest available radar frame."""
    global _rain_cache
    now = time.monotonic()
    if not force and _rain_cache and now - _rain_cache[0] < _RAIN_TTL:
        return _rain_cache[1], _rain_cache[2]
    if not settings.rainviewer_enabled:
        raise LiveDataError("RainViewer is disabled")
    try:
        remote.validate_url(settings.rainviewer_metadata_url)
    except remote.UnsafeURLError as exc:
        raise LiveDataError(str(exc)) from exc
    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=False,
            headers={"User-Agent": "Strata/1.0 (self-hosted weather overlay)"},
        ) as client:
            response = await client.get(settings.rainviewer_metadata_url)
    except httpx.HTTPError as exc:
        raise LiveDataError(f"RainViewer request failed: {exc}") from exc
    if response.status_code >= 400:
        raise LiveDataError(f"RainViewer returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise LiveDataError("RainViewer returned invalid JSON") from exc
    radar = payload.get("radar") or {}
    frames = radar.get("past") or radar.get("nowcast") or []
    if not frames:
        raise LiveDataError("RainViewer has no radar frames")
    host = str(payload.get("host") or "https://tilecache.rainviewer.com").rstrip("/")
    path = str(frames[-1]["path"])
    _rain_cache = (now, host, path)
    return host, path


def rainviewer_template(host: str, path: str, color: int = 4, options: str = "1_1") -> str:
    return f"{host}{path}/256/{{z}}/{{x}}/{{y}}/{color}/{options}.png"


async def fetch_weather_grid(
    bbox: tuple[float, float, float, float], grid: int | None = None
) -> list[dict[str, Any]]:
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise LiveDataError("Invalid weather bounding box")
    size = max(2, min(int(grid or settings.live_grid_points), 6))
    if size * size > 36:
        raise LiveDataError("Weather grid is too large")

    lats: list[float] = []
    lons: list[float] = []
    for row in range(size):
        for col in range(size):
            lats.append(round(south + (north - south) * (row + 0.5) / size, 5))
            lons.append(round(west + (east - west) * (col + 0.5) / size, 5))

    params = {
        "latitude": ",".join(str(value) for value in lats),
        "longitude": ",".join(str(value) for value in lons),
        "current": (
            "temperature_2m,relative_humidity_2m,precipitation,rain,"
            "wind_speed_10m,wind_direction_10m,weather_code,cloud_cover,pressure_msl"
        ),
        "timezone": "UTC",
    }
    try:
        remote.validate_url(settings.open_meteo_url)
    except remote.UnsafeURLError as exc:
        raise LiveDataError(str(exc)) from exc
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=False,
            headers={"User-Agent": "Strata/1.0 (self-hosted weather layer)"},
        ) as client:
            response = await client.get(settings.open_meteo_url, params=params)
    except httpx.HTTPError as exc:
        raise LiveDataError(f"Open-Meteo request failed: {exc}") from exc
    if response.status_code >= 400:
        raise LiveDataError(f"Open-Meteo returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise LiveDataError("Open-Meteo returned invalid JSON") from exc
    items = payload if isinstance(payload, list) else [payload]
    records: list[dict[str, Any]] = []
    for item in items:
        current = item.get("current") or {}
        lon = item.get("longitude")
        lat = item.get("latitude")
        if lon is None or lat is None:
            continue
        code = current.get("weather_code")
        props = {
            "name": f"Weather {float(lat):.3f}, {float(lon):.3f}",
            "temperature_c": current.get("temperature_2m"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "precipitation_mm": current.get("precipitation"),
            "rain_mm": current.get("rain"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "wind_direction_deg": current.get("wind_direction_10m"),
            "cloud_cover_pct": current.get("cloud_cover"),
            "pressure_hpa": current.get("pressure_msl"),
            "weather_code": code,
            "weather": wmo_description(code),
            "observed_at": current.get("time"),
            "provider": "Open-Meteo",
        }
        records.append(
            {
                "properties": {key: value for key, value in props.items() if value is not None},
                "geometry": f"POINT({float(lon)} {float(lat)})",
                "valid": True,
                "error": None,
            }
        )
    if not records:
        raise LiveDataError("Open-Meteo returned no weather points")
    return records


async def fetch_earthquakes(min_magnitude: float = 2.5) -> list[dict[str, Any]]:
    try:
        remote.validate_url(settings.usgs_earthquakes_url)
    except remote.UnsafeURLError as exc:
        raise LiveDataError(str(exc)) from exc
    try:
        async with httpx.AsyncClient(
            timeout=45,
            follow_redirects=False,
            headers={"User-Agent": "Strata/1.0 (self-hosted earthquake layer)"},
        ) as client:
            response = await client.get(settings.usgs_earthquakes_url)
    except httpx.HTTPError as exc:
        raise LiveDataError(f"USGS request failed: {exc}") from exc
    if response.status_code >= 400:
        raise LiveDataError(f"USGS returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise LiveDataError("USGS returned invalid JSON") from exc
    records: list[dict[str, Any]] = []
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        magnitude = props.get("mag")
        if magnitude is None or float(magnitude) < min_magnitude or len(coords) < 2:
            continue
        timestamp = props.get("time")
        observed = (
            datetime.fromtimestamp(timestamp / 1000, tz=UTC).isoformat()
            if isinstance(timestamp, (int, float))
            else None
        )
        properties = {
            "name": props.get("title") or props.get("place") or f"M{float(magnitude):.1f}",
            "magnitude": magnitude,
            "place": props.get("place"),
            "time": observed,
            "updated": props.get("updated"),
            "url": props.get("url"),
            "type": props.get("type"),
            "depth_km": coords[2] if len(coords) > 2 else None,
            "tsunami": props.get("tsunami"),
            "alert": props.get("alert"),
            "significance": props.get("sig"),
            "status": props.get("status"),
            "magnitude_type": props.get("magType"),
            "provider": "USGS",
        }
        records.append(
            {
                "properties": {
                    key: value for key, value in properties.items() if value is not None
                },
                "geometry": f"POINT({float(coords[0])} {float(coords[1])})",
                "valid": True,
                "error": None,
            }
        )
    records.sort(key=lambda item: item["properties"].get("magnitude") or 0, reverse=True)
    return records[:5000]
