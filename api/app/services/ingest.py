"""Read-only server/NAS folder discovery for bulk imports.

Only directories configured through INGEST_ROOTS are visible. The path is
resolved (including symlinks) and must remain under one of those roots; the
Docker Compose stack mounts the host folder read-only at /ingest.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..config import settings
from . import geodata, photos

logger = logging.getLogger("nasmap.ingest")

IGNORED_DIRECTORIES = {
    "@eadir",
    "#recycle",
    ".@__thumb",
    "$recycle.bin",
    "system volume information",
    "__macosx",
    ".trash",
    ".trashes",
    ".spotlight-v100",
    ".fseventsd",
    "@recycle",
    "#snapshot",
    "@tmp",
    "@database",
}
IGNORED_FILE_PREFIXES = ("._", "._", "thumbs.db", ".ds_store")
PHOTO_KIND = "photo"
VECTOR_KIND = "vector"
RASTER_KIND = "raster"


class IngestUnavailable(RuntimeError):
    pass


class UnsafeIngestPath(ValueError):
    pass


@dataclass
class ScannedFile:
    path: Path
    relative_path: str
    kind: str
    size: int
    modified: datetime

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "relative_path": self.relative_path,
            "name": self.path.name,
            "kind": self.kind,
            "extension": self.path.suffix.lower(),
            "size": self.size,
            "modified": self.modified.isoformat(),
        }


def roots() -> list[Path]:
    return [root.resolve() for root in settings.ingest_root_list]


def root_info() -> list[dict]:
    rows = []
    for root in settings.ingest_root_list:
        resolved = root.resolve()
        rows.append(
            {
                "path": str(resolved),
                "exists": resolved.is_dir(),
                "readable": os.access(resolved, os.R_OK | os.X_OK) if resolved.exists() else False,
            }
        )
    return rows


def ensure_available() -> None:
    if not settings.ingest_enabled:
        raise IngestUnavailable("Server-side ingestion is disabled")
    if not settings.ingest_root_list:
        raise IngestUnavailable("No INGEST_ROOTS are configured")


def _under_any_root(path: Path, allowed_roots: list[Path]) -> bool:
    for root in allowed_roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def resolve_path(value: str | None) -> Path:
    ensure_available()
    allowed = roots()
    if not allowed:
        raise UnsafeIngestPath("No ingest roots are configured")
    if not value or value in {".", "/"}:
        candidate = allowed[0]
    else:
        raw = Path(value).expanduser()
        candidate = raw if raw.is_absolute() else allowed[0] / raw
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise UnsafeIngestPath(f"Folder does not exist: {value}") from exc
    if not _under_any_root(resolved, allowed):
        raise UnsafeIngestPath("Path is outside the configured ingest roots")
    if not resolved.is_dir():
        raise UnsafeIngestPath("Path is not a folder")
    return resolved


def resolve_file(value: str | Path) -> Path:
    ensure_available()
    allowed = roots()
    raw = Path(value)
    candidate = raw if raw.is_absolute() else allowed[0] / raw
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise UnsafeIngestPath(f"File does not exist: {value}") from exc
    if not _under_any_root(resolved, allowed):
        raise UnsafeIngestPath("File is outside the configured ingest roots")
    if not resolved.is_file():
        raise UnsafeIngestPath("Path is not a file")
    return resolved


def classify(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in photos.PHOTO_EXTENSIONS:
        return PHOTO_KIND
    if suffix in geodata.RASTER_EXTENSIONS:
        return RASTER_KIND
    if suffix in geodata.VECTOR_EXTENSIONS:
        return RASTER_KIND if geodata.is_raster(path.name) else VECTOR_KIND
    return None


def _ignored_dir(name: str) -> bool:
    return name.lower() in IGNORED_DIRECTORIES


def _ignored_file(name: str) -> bool:
    lower = name.lower()
    return lower.startswith(".") or lower in IGNORED_FILE_PREFIXES


def scan(
    path: Path,
    kinds: set[str] | None = None,
    recursive: bool = True,
    limit: int | None = None,
) -> tuple[list[ScannedFile], bool, list[dict]]:
    """Walk a folder and return supported files.

    Returns ``(files, truncated, errors)``. Only metadata is read; EXIF/geometry
    parsing happens later in the worker.
    """
    ensure_available()
    allowed = roots()
    resolved = resolve_path(str(path))
    if not _under_any_root(resolved, allowed):
        raise UnsafeIngestPath("Path is outside the configured ingest roots")

    root = next(
        (candidate for candidate in allowed if _under_any_root(resolved, [candidate])), allowed[0]
    )
    max_files = limit or settings.ingest_max_scan_files
    files: list[ScannedFile] = []
    errors: list[dict] = []
    truncated = False

    def walk(directory: Path) -> None:
        nonlocal truncated
        if truncated:
            return
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            errors.append({"path": str(directory), "error": str(exc)})
            return
        for entry in entries:
            if truncated:
                return
            try:
                entry_path = Path(entry.path)
                if entry.is_symlink() and not settings.ingest_follow_symlinks:
                    continue
                if entry.is_dir(follow_symlinks=settings.ingest_follow_symlinks):
                    if (
                        not entry.name.startswith(".")
                        and not _ignored_dir(entry.name)
                        and recursive
                    ):
                        walk(entry_path)
                    continue
                if not entry.is_file(follow_symlinks=settings.ingest_follow_symlinks):
                    continue
                if _ignored_file(entry.name):
                    continue
                kind = classify(entry_path)
                if kind is None or (kinds and kind not in kinds):
                    continue
                if len(files) >= max_files:
                    truncated = True
                    return
                stat = entry.stat(follow_symlinks=settings.ingest_follow_symlinks)
                files.append(
                    ScannedFile(
                        path=entry_path,
                        relative_path=str(entry_path.relative_to(root)),
                        kind=kind,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    )
                )
            except OSError as exc:
                errors.append({"path": str(entry.path), "error": str(exc)})

    walk(resolved)
    return files, truncated, errors


def scan_for_job(
    path: str,
    kinds: set[str] | None,
    recursive: bool,
) -> list[ScannedFile]:
    files, truncated, errors = scan(
        resolve_path(path),
        kinds=kinds,
        recursive=recursive,
        limit=settings.ingest_max_files_per_job,
    )
    if truncated:
        raise ValueError(
            f"Folder contains more than {settings.ingest_max_files_per_job} supported files. "
            "Narrow the folder or raise INGEST_MAX_FILES_PER_JOB."
        )
    if errors:
        logger.warning("ingest scan had %s unreadable entries", len(errors))
    if not files:
        raise ValueError("No supported files found in that folder")
    return files
