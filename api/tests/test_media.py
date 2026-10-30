from pathlib import Path

from app.services import media


def test_media_allowlist(tmp_path: Path):
    path = tmp_path / "notes.pdf"
    path.write_bytes(b"%PDF-1.4 test")
    info = media.inspect_media(path)
    assert info["content_type"] == "application/pdf"
    assert info["size_bytes"] > 0
    assert len(info["checksum"]) == 64
    assert media.is_media("clip.mp4")
    assert media.is_media("report.pdf")
    assert not media.is_media("script.sh")
    assert not media.is_media("archive.zip")
