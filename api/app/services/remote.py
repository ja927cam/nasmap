"""Safe remote URL fetching and source-type detection.

Remote imports are deliberately restrictive: http/https only, DNS resolution
and IP range checks on every redirect hop, a hard byte cap and a wall-clock
timeout. This blocks the common SSRF paths (cloud metadata, loopback, RFC1918,
link-local and unique-local IPv6) without requiring a proxy appliance.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from ..config import settings

logger = logging.getLogger("nasmap.remote")

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}
ALLOWED_CONTENT_HINTS = (
    "application/json",
    "application/geo+json",
    "application/gpx+xml",
    "application/vnd.google-earth.kml+xml",
    "application/zip",
    "application/octet-stream",
    "application/xml",
    "text/xml",
    "text/csv",
    "image/tiff",
    "application/geopackage+sqlite3",
)


class UnsafeURLError(ValueError):
    pass


@dataclass
class FetchResult:
    path: Path
    url: str
    final_url: str
    filename: str
    content_type: str
    size: int
    checksum: str


def validate_url(url: str, allow_private: bool | None = None) -> str:
    if allow_private is None:
        allow_private = settings.allow_private_url_imports
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in settings.allowed_schemes:
        raise UnsafeURLError(f"URL scheme '{parsed.scheme}' is not allowed")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no hostname")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed")
    host = parsed.hostname.lower().rstrip(".")
    if host in BLOCKED_HOSTNAMES:
        raise UnsafeURLError("Local and metadata hostnames are blocked")
    try:
        literal = ipaddress.ip_address(host)
        if not allow_private:
            _check_ip(literal)
        return url
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host '{host}'") from exc
    if not infos:
        raise UnsafeURLError(f"Could not resolve host '{host}'")
    if not allow_private:
        for info in infos:
            _check_ip(ipaddress.ip_address(info[4][0]))
    return url


def _check_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (
            isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped and _blocked_v4(ip.ipv4_mapped)
        )
    ):
        raise UnsafeURLError(f"URL resolves to a blocked address ({ip})")
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("169.254.169.254/32"):
        raise UnsafeURLError("Cloud metadata address is blocked")


def _blocked_v4(ip: ipaddress.IPv4Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip in ipaddress.ip_network("169.254.0.0/16")
    )


def _filename_from_response(url: str, headers: httpx.Headers) -> str:
    disposition = headers.get("content-disposition", "")
    if "filename=" in disposition:
        candidate = disposition.split("filename=", 1)[1].split(";")[0].strip().strip('"')
        if candidate:
            return Path(candidate).name
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if name:
        return name
    content_type = headers.get("content-type", "").split(";")[0].strip()
    suffix = {
        "application/geo+json": ".geojson",
        "application/json": ".json",
        "image/tiff": ".tif",
        "application/zip": ".zip",
        "text/csv": ".csv",
        "application/gpx+xml": ".gpx",
    }.get(content_type, ".bin")
    return f"remote{suffix}"


async def fetch_remote_to_file(
    url: str,
    directory: Path,
    max_mb: int | None = None,
    timeout: int | None = None,
) -> FetchResult:
    max_bytes = (max_mb or settings.max_url_import_mb) * 1024 * 1024
    timeout_seconds = timeout or settings.url_fetch_timeout_seconds
    current = validate_url(url)
    directory.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(timeout_seconds, connect=15),
        headers={"User-Agent": "NasMap/1.0 (+self-hosted geospatial importer)"},
    ) as client:
        for _hop in range(6):
            async with client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeURLError("Redirect without a Location header")
                    current = validate_url(str(httpx.URL(current).join(location)))
                    continue
                if response.status_code >= 400:
                    raise ValueError(f"Remote server returned HTTP {response.status_code}")
                length = response.headers.get("content-length")
                if length and int(length) > max_bytes:
                    size_mb = int(length) // (1024 * 1024)
                    raise ValueError(f"Remote file is {size_mb} MB, above the configured limit")
                content_type = response.headers.get("content-type", "application/octet-stream")
                if content_type and not any(h in content_type for h in ALLOWED_CONTENT_HINTS):
                    logger.info("unusual remote content-type: %s", content_type)
                filename = _filename_from_response(current, response.headers)
                target = (
                    directory / f"{hashlib.sha256(current.encode()).hexdigest()[:12]}-{filename}"
                )
                hasher = hashlib.sha256()
                size = 0
                with target.open("wb") as handle:
                    async for chunk in response.aiter_bytes(1024 * 256):
                        size += len(chunk)
                        if size > max_bytes:
                            handle.close()
                            target.unlink(missing_ok=True)
                            raise ValueError("Remote file exceeded the configured size limit")
                        hasher.update(chunk)
                        handle.write(chunk)
                return FetchResult(
                    path=target,
                    url=url,
                    final_url=current,
                    filename=filename,
                    content_type=content_type,
                    size=size,
                    checksum=hasher.hexdigest(),
                )
    raise ValueError("Too many redirects")


def detect_remote_kind(url: str, content_type: str = "", filename: str = "") -> str:
    parsed = urlparse(url)
    path = f"{parsed.path} {parsed.query}".lower()
    suffix = Path(filename or parsed.path).suffix.lower()
    ctype = content_type.lower()
    if "service=wms" in path or "request=getcapabilities" in path and "wms" in path:
        return "wms"
    if "service=wfs" in path or "wfs" in path and "request=getcapabilities" in path:
        return "wfs"
    if "featureserver" in path or "mapserver" in path or "/arcgis/" in path:
        return "arcgis"
    if "stac" in path:
        return "stac"
    if suffix in {".geojson", ".json"} or "json" in ctype:
        return "geojson"
    if suffix in {".gpkg"} or "geopackage" in ctype:
        return "gpkg"
    if suffix in {".tif", ".tiff"} or "tiff" in ctype:
        return "cog"
    if suffix in {".zip", ".shp", ".kml", ".kmz", ".gpx", ".csv"}:
        return "url"
    if ctype in {"application/xml", "text/xml"}:
        return "wms"
    return "url"


def arcgis_geojson_url(url: str) -> str:
    base = url.rstrip("/")
    if "/query" in base:
        return base
    return f"{base}/query?where=1%3D1&outFields=*&f=geojson&outSR=4326"


def stac_asset_url(payload: dict, url: str) -> str | None:
    assets = payload.get("assets") or {}
    preferred = ("cog", "geotiff", "data", "visual", "image")
    for key in preferred:
        asset = assets.get(key)
        if asset and asset.get("href"):
            return str(httpx.URL(url).join(asset["href"]))
    for asset in assets.values():
        media = (asset.get("type") or "").lower()
        if "tiff" in media or "cog" in media:
            return str(httpx.URL(url).join(asset["href"]))
    return None


def parse_stac_item(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != "Feature":
        raise ValueError("Only STAC Items are supported for direct imports (not collections)")
    return payload
