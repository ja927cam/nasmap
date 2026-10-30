"""Non-image media attachments (documents, video, audio).

Only an explicit allowlist is accepted so the attachment endpoint cannot be used
as a general-purpose file host or to serve executables.
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

MEDIA_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
}


def is_media(filename: str) -> bool:
    return Path(filename).suffix.lower() in MEDIA_EXTENSIONS


def inspect_media(path: Path) -> dict:
    suffix = path.suffix.lower()
    content_type = MEDIA_EXTENSIONS.get(suffix) or mimetypes.guess_type(path.name)[0]
    if not content_type:
        raise ValueError("Unsupported media type")
    return {
        "filename": path.name,
        "storage_path": path,
        "content_type": content_type,
        "size_bytes": path.stat().st_size,
        "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
