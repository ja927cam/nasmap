from pathlib import Path

from PIL import Image

from app.services import photos


def test_dms_conversion():
    assert abs((photos.dms_to_decimal((52, 12, 17.64), "N") or 0) - 52.2049) < 0.0001
    assert abs((photos.dms_to_decimal((0, 7, 18.0), "W") or 0) + 0.121666) < 0.001
    assert photos.dms_to_decimal(None, "N") is None


def test_photo_without_gps_is_reported(tmp_path: Path):
    path = tmp_path / "plain.jpg"
    Image.new("RGB", (32, 24), "white").save(path, "JPEG")
    metadata = photos.inspect_photo(path)
    assert metadata.lat is None
    assert metadata.lon is None
    assert metadata.width == 32
    assert metadata.height == 24
    assert len(metadata.checksum) == 64


def test_thumbnail_generation(tmp_path: Path):
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (1200, 800), "blue").save(source, "JPEG")
    destination = tmp_path / "thumb.jpg"
    photos.make_thumbnail(source, destination, size=200)
    with Image.open(destination) as image:
        assert max(image.size) <= 200
