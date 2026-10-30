from pathlib import Path

import pytest

from app.config import settings
from app.services import ingest


@pytest.fixture
def ingest_root(tmp_path: Path, monkeypatch):
    root = tmp_path / "ingest"
    root.mkdir()
    monkeypatch.setattr(settings, "ingest_enabled", True)
    monkeypatch.setattr(settings, "ingest_roots", str(root))
    monkeypatch.setattr(settings, "ingest_follow_symlinks", False)
    return root


def test_resolve_relative_and_reject_traversal(ingest_root: Path, tmp_path: Path):
    (ingest_root / "holiday").mkdir()
    assert ingest.resolve_path("holiday") == (ingest_root / "holiday").resolve()

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ingest.UnsafeIngestPath):
        ingest.resolve_path(str(outside))
    with pytest.raises(ingest.UnsafeIngestPath):
        ingest.resolve_path("../outside")


def test_scan_finds_supported_and_ignores_nas_metadata(ingest_root: Path):
    (ingest_root / "a.jpg").write_bytes(b"not a real image")
    (ingest_root / "b.geojson").write_text("{}")
    (ingest_root / "c.tif").write_bytes(b"tiff")
    (ingest_root / "notes.txt").write_text("ignore")
    (ingest_root / ".hidden.jpg").write_bytes(b"hidden")
    junk = ingest_root / "@eaDir"
    junk.mkdir()
    (junk / "thumb.jpg").write_bytes(b"thumb")

    files, truncated, errors = ingest.scan(ingest_root, limit=50)
    names = sorted(item.path.name for item in files)
    assert names == ["a.jpg", "b.geojson", "c.tif"]
    assert not truncated
    assert errors == []


def test_scan_limit_and_kind_filter(ingest_root: Path):
    for index in range(5):
        (ingest_root / f"{index}.jpg").write_bytes(b"x")
    (ingest_root / "data.geojson").write_text("{}")
    photos, truncated, _ = ingest.scan(ingest_root, kinds={ingest.PHOTO_KIND}, limit=3)
    assert len(photos) == 3
    assert truncated is True
    geodata, _, _ = ingest.scan(ingest_root, kinds={ingest.VECTOR_KIND, ingest.RASTER_KIND})
    assert [item.path.name for item in geodata] == ["data.geojson"]
