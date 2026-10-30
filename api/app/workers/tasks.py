"""Background import jobs.

All long-running work (GDAL conversion, remote downloads, Tessera exports) runs
here, outside the request/response cycle. Progress is persisted on
imports.import_jobs so the UI can reconnect after a refresh or a restart.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy import select, update

from ..config import settings
from ..database import SessionLocal, engine
from ..models import ExternalSource, Feature, ImportJob, Layer, TesseraDataset
from ..services import geodata, ingest, overpass, photo_ingest, photos, raster, remote, tessera
from . import sync_db

logger = logging.getLogger("nasmap.worker")


class JobCancelled(RuntimeError):
    pass


async def _set_job(db, job: ImportJob, **fields: Any) -> None:
    for key, value in fields.items():
        setattr(job, key, value)
    await db.commit()


async def _check_cancel(db, job: ImportJob) -> None:
    await db.refresh(job, ["cancel_requested"])
    if job.cancel_requested:
        raise JobCancelled("Import cancelled by user")


def _safe_under(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    root_resolved = root.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise ValueError("Source path escapes the upload directory")
    return resolved


async def _create_layer(
    db,
    job: ImportJob,
    name: str,
    geometry_type: str,
    source_type: str,
    metadata: dict[str, Any],
    attribution: str = "",
    licence: str = "",
    visibility: str = "private",
) -> Layer:
    layer = Layer(
        owner_id=job.user_id,
        name=name,
        description="",
        visibility=visibility,
        geometry_type=geometry_type,
        source_type=source_type,
        style={},
        metadata_=metadata,
        attribution=attribution,
        licence=licence,
    )
    db.add(layer)
    await db.flush()
    return layer


async def _insert_vector_records(
    db,
    job: ImportJob,
    layer: Layer,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    inserted = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    total = len(records)
    batch_size = 500
    for start in range(0, total, batch_size):
        await _check_cancel(db, job)
        batch = records[start : start + batch_size]
        objects = []
        for record in batch:
            if not record.get("geometry") or not record.get("valid", True):
                skipped += 1
                if len(errors) < 50:
                    errors.append(
                        {
                            "feature": start + len(objects),
                            "error": record.get("error") or "Invalid geometry",
                            "properties": record.get("properties", {}),
                        }
                    )
                continue
            objects.append(
                Feature(
                    layer_id=layer.id,
                    properties=record.get("properties", {}),
                    geometry=WKTElement(record["geometry"], srid=4326),
                    created_by=job.user_id,
                    updated_by=job.user_id,
                )
            )
        if objects:
            db.add_all(objects)
            await db.flush()
            inserted += len(objects)
        pct = 10 + int(min(1.0, (start + len(batch)) / max(total, 1)) * 80)
        await _set_job(
            db,
            job,
            progress=pct,
            message=f"Wrote {inserted}/{total} features",
        )
    return {
        "feature_count": inserted,
        "skipped_count": skipped,
        "errors": errors,
    }


async def _import_vector_path(
    db,
    job: ImportJob,
    path: Path,
    options: dict[str, Any],
    source_type: str,
    source_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await _set_job(db, job, progress=5, message="Reading and validating vector data")
    inspected = await asyncio.to_thread(geodata.inspect_vector, path)
    stats = inspected["stats"]
    records = inspected["records"]

    layer_id = options.get("layer_id") or (str(job.layer_id) if job.layer_id else None)
    if layer_id:
        layer = await db.get(Layer, layer_id)
        if not layer or layer.deleted_at is not None:
            raise ValueError("Target layer no longer exists")
        mode = "append"
    else:
        mode = "create"
        layer = await _create_layer(
            db,
            job,
            options.get("name") or path.stem,
            inspected["geometry_type"],
            source_type,
            {
                "crs": inspected["crs"],
                "bounds": inspected["bounds"],
                "import_stats": stats,
                "original_filename": path.name,
                **(source_meta or {}),
            },
            attribution=options.get("attribution", ""),
            licence=options.get("licence", ""),
            visibility=options.get("visibility", "private"),
        )
        job.layer_id = layer.id

    if layer.geometry_type in {"raster", "table"}:
        raise ValueError("Cannot append vector features to a raster or table layer")
    if mode == "append" and layer.geometry_type in geodata.GEOMETRY_CLASSES:
        allowed = {
            "point": {"Point", "MultiPoint"},
            "line": {"LineString", "MultiLineString"},
            "polygon": {"Polygon", "MultiPolygon"},
        }[layer.geometry_type]
        incompatible = [t for t in stats["geometry_types"] if t not in allowed]
        if incompatible:
            found = ", ".join(incompatible)
            raise ValueError(
                f"Layer expects {layer.geometry_type} geometry but file contains {found}"
            )

    source_id = options.get("source_id")
    if source_id:
        for record in records:
            record.setdefault("properties", {})["_nasmap_source_id"] = source_id

    if options.get("refresh") and mode == "append":
        from sqlalchemy import update

        condition = [
            Feature.layer_id == layer.id,
            Feature.deleted_at.is_(None),
        ]
        if source_id:
            condition.append(Feature.properties["_nasmap_source_id"].astext == source_id)
        await db.execute(
            update(Feature)
            .where(*condition)
            .values(deleted_at=datetime.now(UTC), updated_by=job.user_id)
        )
        await db.commit()
        await _set_job(db, job, message="Replacing previous features from this source")

    await _set_job(db, job, message=f"Importing {len(records)} features")
    result = await _insert_vector_records(db, job, layer, records)
    result.update(
        {
            "layer_id": str(layer.id),
            "mode": mode,
            "geometry_type": layer.geometry_type,
            "crs": inspected["crs"],
            "bounds": inspected["bounds"],
            "stats": stats,
        }
    )
    return result


async def _import_raster_path(
    db,
    job: ImportJob,
    path: Path,
    options: dict[str, Any],
    source_type: str,
    source_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await _set_job(db, job, progress=10, message="Inspecting raster metadata")
    info = await asyncio.to_thread(raster.inspect_raster, path)
    if not info.get("crs"):
        raise ValueError(
            "Raster has no coordinate reference system. Georeference it (for example with "
            "gdal_translate -a_srs EPSG:4326) before importing."
        )
    existing_id = options.get("layer_id") or (str(job.layer_id) if job.layer_id else None)
    if existing_id:
        existing = await db.get(Layer, existing_id)
        if existing and existing.geometry_type == "raster":
            destination = (
                settings.upload_dir / "rasters" / str(existing.id) / f"{uuid.uuid4().hex}.tif"
            )
            await _set_job(db, job, progress=35, message="Building Cloud Optimized GeoTIFF")
            await asyncio.to_thread(raster.ensure_cog, path, destination)
            existing.metadata_ = {
                **(existing.metadata_ or {}),
                "raster": info,
                "raster_path": str(destination),
                "original_filename": path.name,
                **(source_meta or {}),
            }
            job.layer_id = existing.id
            await db.commit()
            await _set_job(db, job, progress=90, message="Raster replaced")
            return {"layer_id": str(existing.id), "raster": info, "raster_path": str(destination)}
    layer = await _create_layer(
        db,
        job,
        options.get("name") or path.stem,
        "raster",
        source_type,
        {
            "raster": info,
            "original_filename": path.name,
            **(source_meta or {}),
        },
        attribution=options.get("attribution", ""),
        licence=options.get("licence", ""),
        visibility=options.get("visibility", "private"),
    )
    job.layer_id = layer.id
    await _set_job(db, job, progress=35, message="Building Cloud Optimized GeoTIFF")
    destination = settings.upload_dir / "rasters" / str(layer.id) / f"{uuid.uuid4().hex}.tif"
    await asyncio.to_thread(raster.ensure_cog, path, destination)
    layer.metadata_ = {**(layer.metadata_ or {}), "raster_path": str(destination)}
    await db.commit()
    await _set_job(db, job, progress=90, message="Raster ready")
    return {
        "layer_id": str(layer.id),
        "raster": info,
        "raster_path": str(destination),
    }


async def _run_wfs_import(
    db, job: ImportJob, source: ExternalSource | None, options: dict[str, Any], workdir: Path
) -> tuple[Path, str, dict[str, Any]]:
    import xml.etree.ElementTree as ET

    import httpx

    url = job.source_url or ""
    type_name = options.get("type_name")
    if not type_name:
        remote.validate_url(url)
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.get(url)
        if response.status_code >= 400:
            raise ValueError(f"WFS capabilities request failed: HTTP {response.status_code}")
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise ValueError("WFS capabilities response is not valid XML") from exc
        for element in root.iter():
            if element.tag.endswith("FeatureType"):
                for child in element:
                    if child.tag.endswith("Name") and child.text:
                        type_name = child.text.strip()
                        break
            if type_name:
                break
    if not type_name:
        raise ValueError("Could not discover a WFS feature type; provide options.type_name")
    sep = "&" if "?" in url else "?"
    fetch_url = (
        f"{url}{sep}service=WFS&version=2.0.0&request=GetFeature"
        f"&typeNames={type_name}&outputFormat=application/json&srsName=EPSG:4326"
    )
    result = await remote.fetch_remote_to_file(fetch_url, workdir)
    return result.path, "url", {"wfs_type_name": type_name, "resolved_url": fetch_url}


async def _run_url_import(
    db, job: ImportJob, options: dict[str, Any], workdir: Path
) -> dict[str, Any]:
    url = job.source_url
    if not url:
        raise ValueError("No source URL on this job")
    source = None
    if options.get("source_id"):
        source = await db.get(ExternalSource, options["source_id"])

    kind = options.get("kind") or remote.detect_remote_kind(url)
    if kind == "wms":
        existing_id = options.get("layer_id") or (str(job.layer_id) if job.layer_id else None)
        wms_layers = options.get("wms_layers") or ""
        if not wms_layers:
            from urllib.parse import parse_qs, urlparse

            wms_layers = (parse_qs(urlparse(url).query).get("layers") or [""])[0]
        wms_meta = {
            "provider": "wms",
            "wms": {
                "url": options.get("wms_url") or url,
                "layers": wms_layers,
                "version": options.get("wms_version") or "1.3.0",
                "format": options.get("wms_format") or "image/png",
                "transparent": options.get("wms_transparent", True),
                "styles": options.get("wms_styles") or "",
            },
            "bounds": options.get("bounds") or [-180, -85, 180, 85],
        }
        if existing_id:
            existing = await db.get(Layer, existing_id)
            if existing and existing.geometry_type == "raster":
                existing.metadata_ = {**(existing.metadata_ or {}), **wms_meta}
                job.layer_id = existing.id
                await db.commit()
                return {"layer_id": str(existing.id), "kind": "wms"}
        layer = await _create_layer(
            db,
            job,
            options.get("name") or "WMS layer",
            "raster",
            "url",
            wms_meta,
            attribution=options.get("attribution", ""),
            licence=options.get("licence", ""),
            visibility=options.get("visibility", "private"),
        )
        job.layer_id = layer.id
        return {"layer_id": str(layer.id), "kind": "wms"}

    if kind == "wfs":
        path, source_type, meta = await _run_wfs_import(db, job, source, options, workdir)
        return await _import_vector_path(db, job, path, options, source_type, meta)

    if kind == "arcgis":
        fetch_url = remote.arcgis_geojson_url(url)
        fetched = await remote.fetch_remote_to_file(fetch_url, workdir)
        return await _import_vector_path(
            db,
            job,
            fetched.path,
            options,
            "url",
            {"resolved_url": fetch_url, "checksum": fetched.checksum},
        )

    fetched = await remote.fetch_remote_to_file(url, workdir)
    await _set_job(db, job, progress=30, message=f"Downloaded {fetched.size} bytes")
    detected = remote.detect_remote_kind(fetched.final_url, fetched.content_type, fetched.filename)
    if kind == "stac" or detected == "stac":
        try:
            payload = remote.parse_stac_item(fetched.path)
            asset_url = remote.stac_asset_url(payload, fetched.final_url)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Could not parse STAC item: {exc}") from exc
        if not asset_url:
            raise ValueError("STAC item has no COG/GeoTIFF asset")
        fetched = await remote.fetch_remote_to_file(asset_url, workdir)
        detected = "cog"

    meta = {
        "source_url": fetched.url,
        "resolved_url": fetched.final_url,
        "checksum": fetched.checksum,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "content_type": fetched.content_type,
    }
    if source:
        source.checksum = fetched.checksum
        source.retrieved_at = datetime.now(UTC)
        source.last_import_at = datetime.now(UTC)
        source.metadata_ = {**(source.metadata_ or {}), **meta}
        if source.refresh_interval_seconds:
            source.next_refresh_at = datetime.now(UTC) + timedelta(
                seconds=source.refresh_interval_seconds
            )
        await db.commit()

    if geodata.is_raster(fetched.filename) or detected == "cog":
        meta["provider"] = "cog"
        return await _import_raster_path(db, job, fetched.path, options, "url", meta)
    return await _import_vector_path(db, job, fetched.path, options, "url", meta)


async def _run_tessera_import(db, job: ImportJob, options: dict[str, Any]) -> dict[str, Any]:
    bbox = options.get("bbox")
    year = int(options.get("year") or 0)
    if not bbox or len(bbox) != 4:
        raise ValueError("Tessera import requires bbox=[min_lon,min_lat,max_lon,max_lat]")
    variant = options.get("variant") or None
    bands = options.get("bands")
    output_dir = settings.tessera_cache_dir / "jobs" / str(job.id)
    output_dir.mkdir(parents=True, exist_ok=True)

    def progress(pct: int, message: str) -> None:
        sync_db.update_job(str(job.id), progress=max(1, min(95, pct)), message=message)

    def cancelled() -> bool:
        return sync_db.is_cancelled(str(job.id))

    try:
        result = await asyncio.to_thread(
            tessera.import_region,
            tuple(bbox),
            year,
            output_dir,
            variant,
            bands,
            progress,
            cancelled,
        )
    except tessera.TesseraCancelled as exc:
        raise JobCancelled("Import cancelled by user") from exc
    if cancelled():
        raise JobCancelled("Import cancelled by user")

    if cancelled():
        raise JobCancelled("Import cancelled by user")
    await _set_job(db, job, progress=94, message="Building Cloud Optimized GeoTIFF")
    mosaic_path = Path(result["mosaic_path"])
    cog_path = settings.upload_dir / "rasters" / str(job.layer_id or job.id) / "mosaic.tif"
    await asyncio.to_thread(raster.ensure_cog, mosaic_path, cog_path)
    if cancelled():
        raise JobCancelled("Import cancelled by user")
    info = await asyncio.to_thread(raster.inspect_raster, cog_path)
    layer = await _create_layer(
        db,
        job,
        options.get("name") or f"Tessera {year} {variant or ''}".strip(),
        "raster",
        "tessera",
        {
            "provider": "tessera",
            "raster": info,
            "tessera": {
                "year": year,
                "variant": result["variant"],
                "version": result["version"],
                "bbox": list(bbox),
                "tile_count": result["tile_count"],
                "tile_files": result["tile_files"],
                "crs": "EPSG:3857 (web mosaic); native tiles are UTM",
                "band_count": info.get("band_count"),
                "source_band_count": 128,
                "resolution": 10,
                "licence": options.get("licence", "Tessera dataset terms"),
                "attribution": "Tessera / GeoTessera",
            },
            "raster_path": str(cog_path),
        },
        attribution="Tessera / GeoTessera",
        licence="Tessera dataset terms - https://geotessera.readthedocs.io",
        visibility=options.get("visibility", "private"),
    )
    job.layer_id = layer.id
    ring = (
        f"POLYGON(({bbox[0]} {bbox[1]},{bbox[2]} {bbox[1]},{bbox[2]} {bbox[3]},"
        f"{bbox[0]} {bbox[3]},{bbox[0]} {bbox[1]}))"
    )
    dataset = TesseraDataset(
        layer_id=layer.id,
        bbox=WKTElement(ring, srid=4326),
        year=year,
        variant=result["variant"],
        tile_ids=result["tiles"],
        band_count=info.get("band_count"),
        resolution=10,
        crs="EPSG:3857",
        licence="Tessera dataset terms",
        attribution="Tessera / GeoTessera",
        cache_path=str(output_dir),
        created_by=job.user_id,
    )
    db.add(dataset)
    return {
        "layer_id": str(layer.id),
        "mosaic_path": str(cog_path),
        "tile_files": result["tile_files"],
        "tile_count": result["tile_count"],
        "year": year,
        "variant": result["variant"],
    }


async def _run_ingest_photos(db, job: ImportJob, options: dict[str, Any]) -> dict[str, Any]:
    path_value = options.get("path") or job.source_path
    if not path_value:
        raise ValueError("No folder path on this ingest job")
    recursive = bool(options.get("recursive", True))
    await _set_job(db, job, progress=3, message="Scanning folder for photos")
    files = await asyncio.to_thread(ingest.scan_for_job, path_value, {ingest.PHOTO_KIND}, recursive)
    if len(files) > settings.ingest_max_files_per_job:
        raise ValueError("Too many photos; narrow the folder")

    layer_id = options.get("layer_id") or (str(job.layer_id) if job.layer_id else None)
    existing_layer = bool(layer_id)
    target_layer: Layer | None = None
    if layer_id:
        target_layer = await db.get(Layer, layer_id)
        if not target_layer or target_layer.deleted_at is not None:
            raise ValueError("Target photo layer no longer exists")
        if target_layer.geometry_type not in {"point", "geometry"}:
            raise ValueError("Photos can only be added to point layers")

    incoming = []
    skipped: list[dict[str, str]] = []
    total = len(files)
    max_photo_bytes = settings.max_photo_mb * 1024 * 1024
    for index, item in enumerate(files):
        await _check_cancel(db, job)
        if item.size > max_photo_bytes:
            skipped.append(
                {
                    "filename": item.path.name,
                    "reason": f"Larger than MAX_PHOTO_MB ({settings.max_photo_mb} MB)",
                }
            )
            continue
        try:
            metadata = await asyncio.to_thread(photos.inspect_photo, item.path)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"filename": item.path.name, "reason": f"Could not read photo: {exc}"})
            continue
        if metadata.lat is None or metadata.lon is None:
            skipped.append(
                {
                    "filename": metadata.filename,
                    "reason": "No GPS EXIF tag found",
                }
            )
            continue
        incoming.append(metadata)
        if index % 25 == 0 or index + 1 == total:
            pct = 5 + int(((index + 1) / max(total, 1)) * 35)
            await _set_job(db, job, progress=pct, message=f"Read EXIF for {index + 1}/{total}")

    if not incoming:
        raise ValueError(
            "No geotagged photos were found. Photos without EXIF GPS are listed in the result."
        )

    if target_layer is None:
        suffix = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        layer_name = (options.get("name") or "").strip() or f"Photos {suffix}"
        target_layer = await photo_ingest.create_photo_layer(
            db,
            job.user_id,
            layer_name,
            options.get("visibility", "private"),
        )
    await _set_job(
        db,
        job,
        progress=45,
        message=f"Importing {len(incoming)} geotagged photos",
    )

    try:
        summary = await photo_ingest.attach_photo_metadata(
            db,
            job.user_id,
            target_layer,
            incoming,
            skipped,
            match_existing=bool(options.get("match_existing")),
            existing_layer=existing_layer,
            match_radius_m=int(options.get("match_radius_m") or 60),
            progress=lambda current, count: sync_db.update_job(
                str(job.id),
                progress=45 + int((current / max(count, 1)) * 45),
                message=f"Importing photo {current}/{count}",
            ),
            is_cancelled=lambda: sync_db.is_cancelled(str(job.id)),
        )
    except photo_ingest.PhotoIngestCancelled as exc:
        raise JobCancelled("Import cancelled by user") from exc

    job.layer_id = target_layer.id
    return {
        "layer_id": str(target_layer.id),
        "layer_name": target_layer.name,
        "scanned": total,
        "created_features": summary["created_features"],
        "attached_photos": summary["attached_photos"],
        "skipped": skipped,
        "attachments": len(summary["attachments"]),
    }


async def _run_ingest_geodata(db, job: ImportJob, options: dict[str, Any]) -> dict[str, Any]:
    path_value = options.get("path") or job.source_path
    if not path_value:
        raise ValueError("No folder path on this ingest job")
    recursive = bool(options.get("recursive", True))
    await _set_job(db, job, progress=2, message="Scanning folder for geodata")
    files = await asyncio.to_thread(
        ingest.scan_for_job,
        path_value,
        {ingest.VECTOR_KIND, ingest.RASTER_KIND},
        recursive,
    )
    prefix = (options.get("name") or "").strip()
    succeeded = 0
    failed = 0
    layers: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total = len(files)

    for index, item in enumerate(files):
        await _check_cancel(db, job)
        relative_stem = str(Path(item.relative_path).with_suffix(""))
        child_name = f"{prefix} {relative_stem}".strip() or item.path.stem
        child = ImportJob(
            user_id=job.user_id,
            job_type="raster" if item.kind == ingest.RASTER_KIND else "upload",
            status="queued",
            source_path=str(item.path),
            options={
                "name": child_name,
                "visibility": options.get("visibility", "private"),
                "licence": options.get("licence", ""),
                "attribution": options.get("attribution", ""),
                "filename": item.path.name,
                "ingest": True,
                "relative_path": item.relative_path,
            },
        )
        db.add(child)
        await db.flush()
        child_id = str(child.id)
        await db.commit()
        await _process(child_id)
        await db.refresh(child)
        if child.status == "succeeded":
            succeeded += 1
            layer_id = child.result.get("layer_id") if child.result else None
            layers.append(
                {
                    "job_id": child_id,
                    "layer_id": layer_id,
                    "name": child_name,
                    "file": item.relative_path,
                }
            )
        else:
            failed += 1
            errors.append(
                {
                    "file": item.relative_path,
                    "job_id": child_id,
                    "error": child.error or "Import failed",
                }
            )
        pct = 5 + int(((index + 1) / max(total, 1)) * 90)
        await _set_job(
            db,
            job,
            progress=pct,
            message=f"Processed {index + 1}/{total} files ({failed} failed)",
        )

    result = {
        "scanned": total,
        "succeeded": succeeded,
        "failed": failed,
        "layers": layers,
        "errors": errors[:100],
        "files": [item.as_dict() for item in files[:500]],
    }
    if succeeded == 0:
        raise ValueError(
            "None of the files could be imported. Check the child jobs for detailed errors."
        )
    return result


def _job_file_path(job: ImportJob, options: dict[str, Any]) -> Path:
    if not job.source_path:
        raise ValueError("No source file on this job")
    if options.get("ingest"):
        return ingest.resolve_file(job.source_path)
    path = _safe_under(settings.upload_dir, Path(job.source_path))
    if not path.exists():
        raise ValueError("Uploaded file is missing")
    return path


async def _run_osm_import(db, job: ImportJob, options: dict[str, Any]) -> dict[str, Any]:
    bbox = options.get("bbox")
    category = options.get("category")
    if not bbox or len(bbox) != 4 or not category:
        raise ValueError("OSM import requires bbox and category")
    await _set_job(db, job, progress=3, message=f"Fetching OSM {category} from Overpass")
    payload = await overpass.fetch_elements(tuple(bbox), str(category))
    await _check_cancel(db, job)
    await _set_job(db, job, progress=8, message="Converting OSM geometry")
    records, stats = await asyncio.to_thread(overpass.parse_elements, payload, str(category))
    if not records:
        raise ValueError("No editable OSM features were found in that area and category")

    layer_id = options.get("layer_id") or (str(job.layer_id) if job.layer_id else None)
    if layer_id:
        layer = await db.get(Layer, layer_id)
        if not layer or layer.deleted_at is not None:
            raise ValueError("Target OSM layer no longer exists")
    else:
        geometry_type = overpass.guess_geometry_type(stats["geometry_types"])
        layer = await _create_layer(
            db,
            job,
            options.get("name") or f"OSM {category}",
            geometry_type,
            "osm",
            {
                "provider": "osm",
                "category": category,
                "bbox": list(bbox),
                "overpass_url": settings.overpass_url,
                "imported_at": datetime.now(UTC).isoformat(),
                "stats": stats,
            },
            attribution="© OpenStreetMap contributors",
            licence="ODbL 1.0",
            visibility=options.get("visibility", "private"),
        )
        layer.style = {
            "color": "#7c3aed",
            "fillColor": "#8b5cf6",
            "fillOpacity": 0.16,
            "lineWidth": 1.25,
            "circleRadius": 5,
        }
        job.layer_id = layer.id

    if layer.geometry_type in {"raster", "table"}:
        raise ValueError("Cannot append OSM features to a raster or table layer")
    if layer.geometry_type in {"point", "line", "polygon"}:
        allowed = {
            "point": {"Point", "MultiPoint"},
            "line": {"LineString", "MultiLineString"},
            "polygon": {"Polygon", "MultiPolygon"},
        }[layer.geometry_type]
        incompatible = [t for t in stats["geometry_types"] if t not in allowed]
        if incompatible:
            raise ValueError(
                f"Target layer expects {layer.geometry_type} geometry but the OSM data "
                f"contains {', '.join(incompatible)}"
            )

    result = await _insert_vector_records(db, job, layer, records)
    layer.metadata_ = {
        **(layer.metadata_ or {}),
        "provider": "osm",
        "category": category,
        "bbox": list(bbox),
        "overpass_url": settings.overpass_url,
        "imported_at": datetime.now(UTC).isoformat(),
        "stats": stats,
    }
    result.update(
        {
            "layer_id": str(layer.id),
            "geometry_type": layer.geometry_type,
            "category": category,
            "bbox": list(bbox),
            "stats": stats,
        }
    )
    return result


async def _process(job_id: str) -> None:
    async with SessionLocal() as db:
        job = await db.get(ImportJob, job_id)
        if not job:
            logger.error("job %s disappeared", job_id)
            return
        if job.status == "cancelled" or job.cancel_requested:
            job.status = "cancelled"
            job.finished_at = datetime.now(UTC)
            await db.commit()
            return
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.attempts += 1
        job.progress = 1
        job.message = "Starting"
        await db.commit()

        options: dict[str, Any] = job.options or {}
        workdir = settings.upload_dir / "remote" / str(job.id)
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            if job.job_type == "url":
                result = await _run_url_import(db, job, options, workdir)
            elif job.job_type in {"upload", "raster"}:
                path = _job_file_path(job, options)
                if job.job_type == "raster" or geodata.is_raster(path.name):
                    result = await _import_raster_path(db, job, path, options, "upload")
                else:
                    result = await _import_vector_path(db, job, path, options, "upload")
            elif job.job_type == "ingest":
                mode = options.get("mode")
                if mode == "photos":
                    result = await _run_ingest_photos(db, job, options)
                elif mode == "geodata":
                    result = await _run_ingest_geodata(db, job, options)
                else:
                    raise ValueError(f"Unsupported ingest mode {mode}")
            elif job.job_type == "osm":
                result = await _run_osm_import(db, job, options)
            elif job.job_type == "tessera":
                if not settings.tessera_enabled:
                    raise ValueError("Tessera support is disabled")
                result = await _run_tessera_import(db, job, options)
            else:
                raise ValueError(f"Unsupported job type {job.job_type}")

            await _check_cancel(db, job)
            if options.get("source_id"):
                src = await db.get(ExternalSource, options["source_id"])
                if src and job.layer_id:
                    src.layer_id = job.layer_id
                    src.last_import_at = datetime.now(UTC)
            job.status = "succeeded"
            job.progress = 100
            job.message = "Completed"
            job.result = result
            job.finished_at = datetime.now(UTC)
            await db.commit()
            logger.info("job %s succeeded", job_id)
        except JobCancelled as exc:
            job.status = "cancelled"
            job.message = str(exc)
            job.finished_at = datetime.now(UTC)
            await db.commit()
            logger.info("job %s cancelled", job_id)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            job = await db.get(ImportJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(exc)[:4000]
                job.message = "Import failed"
                job.finished_at = datetime.now(UTC)
                await db.commit()
            logger.exception("job %s failed: %s", job_id, exc)


async def _run_in_child(job_id: str) -> None:
    # RQ forks a child per job. Do not reuse asyncpg connections inherited from
    # the parent worker or its scheduler thread.
    await engine.dispose()
    await _process(job_id)


def process_import_job(job_id: str) -> None:
    """RQ entrypoint (sync)."""
    try:
        asyncio.run(_run_in_child(job_id))
    except Exception:  # noqa: BLE001
        logger.exception("unhandled worker error for %s", job_id)
        sync_db.update_job(
            job_id,
            status="failed",
            message="Import failed",
            error="Unhandled worker error; inspect worker logs",
            finished_at=datetime.now(UTC),
        )


def enqueue_due_refreshes() -> int:
    # Importing here avoids a circular import at module load.
    from .queue import enqueue_import

    async def run() -> int:
        # This runs in a scheduler thread with a fresh asyncio.run() loop each
        # minute, so drop connections bound to the previous loop first.
        await engine.dispose()
        async with SessionLocal() as db:
            now = datetime.now(UTC)
            # If a worker is SIGKILLed, its running job would otherwise stay
            # "running" forever. Jobs update progress at least every few
            # minutes; six hours without an update means the worker is gone.
            stale_cutoff = now - timedelta(hours=6)
            await db.execute(
                update(ImportJob)
                .where(ImportJob.status == "running", ImportJob.updated_at < stale_cutoff)
                .values(
                    status="failed",
                    message="Import failed",
                    error="Worker stopped unexpectedly. Retry the import.",
                    finished_at=now,
                )
            )
            sources = (
                await db.scalars(
                    select(ExternalSource).where(
                        ExternalSource.enabled.is_(True),
                        ExternalSource.refresh_interval_seconds.is_not(None),
                        ExternalSource.next_refresh_at.is_not(None),
                        ExternalSource.next_refresh_at <= now,
                    )
                )
            ).all()
            jobs: list[str] = []
            for source in sources:
                job = ImportJob(
                    user_id=source.user_id,
                    layer_id=source.layer_id,
                    job_type="url",
                    status="queued",
                    source_url=source.url,
                    options={
                        "kind": source.kind,
                        "source_id": str(source.id),
                        "layer_id": str(source.layer_id) if source.layer_id else None,
                        "name": (source.metadata_ or {}).get("name") or "Refreshed source",
                        "licence": source.licence,
                        "attribution": source.attribution,
                        "refresh": True,
                    },
                )
                db.add(job)
                source.next_refresh_at = now + timedelta(seconds=source.refresh_interval_seconds)
                await db.flush()
                jobs.append(str(job.id))
            await db.commit()
        await engine.dispose()
        for job_id in jobs:
            enqueue_import(job_id)
        return len(jobs)

    return asyncio.run(run())
