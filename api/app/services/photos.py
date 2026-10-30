"""Geotagged photo handling: EXIF parsing, storage helpers and thumbnails."""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

logger = logging.getLogger("nasmap.photos")

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".jfif", ".tif", ".tiff", ".png", ".webp", ".raf"}
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".png": "image/png",
    ".webp": "image/webp",
    ".raf": "image/x-fujifilm-raf",
}
RAF_CONTENT_TYPE = "image/x-fujifilm-raf"
GPS_IFD = 0x8825


@dataclass
class PhotoMetadata:
    filename: str
    storage_path: Path
    content_type: str
    size_bytes: int
    checksum: str
    width: int
    height: int
    orientation: int | None
    lat: float | None
    lon: float | None
    altitude: float | None
    timestamp: str | None
    camera: str | None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def dms_to_decimal(dms: Any, ref: str | None) -> float | None:
    """Convert EXIF GPS (degrees, minutes, seconds) to decimal degrees."""
    if not dms or len(dms) < 3:
        return None
    degrees = _to_float(dms[0])
    minutes = _to_float(dms[1])
    seconds = _to_float(dms[2])
    value = degrees + minutes / 60.0 + seconds / 3600.0
    if ref and str(ref).upper() in {"S", "W"}:
        value = -value
    return value


def _read_gps(exif: Image.Exif) -> tuple[float | None, float | None, float | None]:
    try:
        gps = exif.get_ifd(GPS_IFD)
    except Exception:  # noqa: BLE001
        gps = {}
    if not gps:
        return None, None, None
    lat = dms_to_decimal(gps.get(2), gps.get(1))
    lon = dms_to_decimal(gps.get(4), gps.get(3))
    if lat is None or lon is None:
        return None, None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None, None
    altitude = None
    if gps.get(6) is not None:
        altitude = _to_float(gps.get(6))
        if gps.get(5) in {1, "1"}:
            altitude = -altitude
        if altitude is not None and not math.isfinite(altitude):
            altitude = None
    return lat, lon, altitude


def _timestamp(exif: Image.Exif) -> str | None:
    raw = exif.get(36867) or exif.get(306)
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return text


def _embedded_raf_image(path: Path) -> tuple[Image.Image, Image.Exif | None, tuple[int, int]]:
    import io

    import rawpy

    with rawpy.imread(str(path)) as raw:
        width, height = raw.sizes.width, raw.sizes.height
        thumbnail = raw.extract_thumb()
        if thumbnail.format == rawpy.ThumbFormat.JPEG:
            image = Image.open(io.BytesIO(thumbnail.data))
            image.load()
            try:
                exif = image.getexif()
            except Exception:  # noqa: BLE001
                exif = None
            return image, exif, (width, height)
        if thumbnail.format == rawpy.ThumbFormat.BITMAP:
            return Image.fromarray(thumbnail.data), None, (width, height)
    raise ValueError("The RAF file does not contain an embedded preview")


def _inspect_raf(path: Path) -> PhotoMetadata:
    image, exif, dimensions = _embedded_raf_image(path)
    try:
        lat = lon = altitude = None
        camera = None
        timestamp = None
        orientation = None
        if exif is not None:
            lat, lon, altitude = _read_gps(exif)
            make = str(exif.get(271) or "").strip()
            model = str(exif.get(272) or "").strip()
            camera = " ".join(part for part in (make, model) if part) or None
            orientation = exif.get(274)
            timestamp = _timestamp(exif)
        width, height = dimensions
        return PhotoMetadata(
            filename=path.name,
            storage_path=path,
            content_type=RAF_CONTENT_TYPE,
            size_bytes=path.stat().st_size,
            checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
            width=width,
            height=height,
            orientation=int(orientation) if orientation else None,
            lat=lat,
            lon=lon,
            altitude=altitude,
            timestamp=timestamp,
            camera=camera,
        )
    finally:
        image.close()


def inspect_photo(path: Path) -> PhotoMetadata:
    suffix = path.suffix.lower()
    if suffix not in PHOTO_EXTENSIONS:
        raise ValueError(f"Unsupported photo type '{suffix}'. Use JPEG, TIFF, PNG, WebP or RAF.")
    if suffix == ".raf":
        return _inspect_raf(path)
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        exif = image.getexif()
        lat, lon, altitude = _read_gps(exif)
        make = str(exif.get(271) or "").strip()
        model = str(exif.get(272) or "").strip()
        camera = " ".join(part for part in (make, model) if part) or None
        width, height = image.size
        orientation = exif.get(274)
        timestamp = _timestamp(exif)
    return PhotoMetadata(
        filename=path.name,
        storage_path=path,
        content_type=CONTENT_TYPES.get(suffix, "application/octet-stream"),
        size_bytes=path.stat().st_size,
        checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
        width=width,
        height=height,
        orientation=int(orientation) if orientation else None,
        lat=lat,
        lon=lon,
        altitude=altitude,
        timestamp=timestamp,
        camera=camera,
    )


def _open_preview_image(source: Path) -> Image.Image:
    if source.suffix.lower() == ".raf":
        image, _, _ = _embedded_raf_image(source)
        return image
    return Image.open(source)


def _save_jpeg(image: Image.Image, destination: Path, max_size: int, quality: int) -> Path:
    image = ImageOps.exif_transpose(image)
    image.thumbnail((max_size, max_size))
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(".tmp")
    image.save(tmp, format="JPEG", quality=quality, optimize=True)
    tmp.replace(destination)
    image.close()
    return destination


def make_thumbnail(source: Path, destination: Path, size: int = 480) -> Path:
    with _open_preview_image(source) as image:
        return _save_jpeg(image, destination, size, 85)


def make_preview(source: Path, destination: Path, size: int = 2400) -> Path:
    with _open_preview_image(source) as image:
        return _save_jpeg(image, destination, size, 88)


def is_photo(filename: str) -> bool:
    return Path(filename).suffix.lower() in PHOTO_EXTENSIONS


def photo_title(metadata: PhotoMetadata) -> str:
    stem = Path(metadata.filename).stem
    if metadata.timestamp:
        return f"{stem} · {metadata.timestamp[:16].replace('T', ' ')}"
    return stem
