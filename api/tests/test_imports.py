import io
from pathlib import Path

from PIL import Image

from app.config import settings
from app.services import live, overpass
from app.workers import tasks


async def test_geojson_upload_spatial_query_and_crud(admin_client, sample_path: Path, monkeypatch):
    import app.routers.uploads as uploads_router

    monkeypatch.setattr(uploads_router, "enqueue_import", lambda job_id: None)
    sample = sample_path / "cambridge-landmarks.geojson"
    with sample.open("rb") as handle:
        response = await admin_client.post(
            "/api/v1/uploads",
            files={"file": (sample.name, handle, "application/geo+json")},
            data={"name": "Cambridge landmarks", "visibility": "private"},
        )
    assert response.status_code == 202, response.text
    job = response.json()

    await tasks._process(job["id"])

    status = await admin_client.get(f"/api/v1/imports/{job['id']}")
    assert status.status_code == 200
    job = status.json()
    assert job["status"] == "succeeded", job
    assert job["result"]["feature_count"] == 5
    layer_id = job["layer_id"]
    assert layer_id

    layer = await admin_client.get(f"/api/v1/layers/{layer_id}")
    assert layer.status_code == 200
    assert layer.json()["feature_count"] == 5

    features = await admin_client.get(f"/api/v1/layers/{layer_id}/features")
    assert features.json()["meta"]["total"] == 5

    bbox = await admin_client.get(
        f"/api/v1/layers/{layer_id}/features?bbox=0.1160,52.2045,0.1172,52.2053"
    )
    assert bbox.json()["meta"]["total"] == 1
    assert bbox.json()["features"][0]["properties"]["name"] == "King's College Chapel"

    search = await admin_client.get(f"/api/v1/layers/{layer_id}/features?q=Market")
    assert search.json()["meta"]["total"] == 1

    created = await admin_client.post(
        f"/api/v1/layers/{layer_id}/features",
        json={
            "properties": {"name": "New point"},
            "geometry": {"type": "Point", "coordinates": [0.12, 52.21]},
        },
    )
    assert created.status_code == 201, created.text
    feature_id = created.json()["id"]
    assert created.json()["version"] == 1

    patched = await admin_client.patch(
        f"/api/v1/features/{feature_id}", json={"properties": {"name": "Renamed"}}
    )
    assert patched.status_code == 200
    assert patched.json()["properties"]["name"] == "Renamed"
    assert patched.json()["version"] == 2

    versions = await admin_client.get(f"/api/v1/features/{feature_id}/versions")
    assert versions.status_code == 200
    assert len(versions.json()) >= 2

    deleted = await admin_client.delete(f"/api/v1/features/{feature_id}")
    assert deleted.status_code == 200


async def test_csv_upload(admin_client, sample_path: Path, monkeypatch):
    import app.routers.uploads as uploads_router

    monkeypatch.setattr(uploads_router, "enqueue_import", lambda job_id: None)
    sample = sample_path / "cambridge-pubs.csv"
    with sample.open("rb") as handle:
        response = await admin_client.post(
            "/api/v1/uploads",
            files={"file": (sample.name, handle, "text/csv")},
            data={"name": "Cambridge pubs"},
        )
    assert response.status_code == 202, response.text
    await tasks._process(response.json()["id"])
    job = (await admin_client.get(f"/api/v1/imports/{response.json()['id']}")).json()
    assert job["status"] == "succeeded", job
    assert job["result"]["feature_count"] == 4
    features = await admin_client.get(f"/api/v1/layers/{job['layer_id']}/features")
    assert features.json()["meta"]["total"] == 4


async def test_upload_rejects_unknown_type(admin_client):
    response = await admin_client.post(
        "/api/v1/uploads",
        files={"file": ("evil.exe", b"not a geodata file", "application/octet-stream")},
    )
    assert response.status_code == 422


async def test_ssrf_private_url_rejected(admin_client):
    response = await admin_client.post(
        "/api/v1/imports/url",
        json={"url": "http://127.0.0.1:8000/secret.geojson", "kind": "geojson"},
    )
    assert response.status_code == 422
    assert "blocked" in response.text.lower()


def gps_jpeg_bytes(lat=(52, 12, 17.64), lon=(0, 7, 18.0)) -> bytes:
    image = Image.new("RGB", (64, 48), "teal")
    exif = Image.Exif()
    exif[0x8825] = {
        1: "N" if lat[0] >= 0 else "S",
        2: (abs(lat[0]), lat[1], lat[2]),
        3: "E" if lon[0] >= 0 else "W",
        4: (abs(lon[0]), lon[1], lon[2]),
    }
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


async def test_photo_upload_creates_point_and_attachment(admin_client):
    response = await admin_client.post(
        "/api/v1/photos/import",
        files={"files": ("geotagged.jpg", gps_jpeg_bytes(), "image/jpeg")},
        data={"name": "Survey photos"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created_features"] == 1
    assert result["attached_photos"] == 0
    layer_id = result["layer_id"]

    features = await admin_client.get(f"/api/v1/layers/{layer_id}/features")
    assert features.status_code == 200
    assert features.json()["meta"]["total"] == 1
    feature = features.json()["features"][0]
    assert feature["properties"]["photo_filename"] == "geotagged.jpg"
    assert abs(feature["geometry"]["coordinates"][0] - 0.1216667) < 0.001
    assert abs(feature["geometry"]["coordinates"][1] - 52.2049) < 0.001

    attachments = await admin_client.get(f"/api/v1/features/{feature['id']}/attachments")
    assert attachments.status_code == 200
    assert len(attachments.json()) == 1
    attachment = attachments.json()[0]
    content = await admin_client.get(attachment["content_url"])
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/")
    thumb = await admin_client.get(attachment["thumb_url"])
    assert thumb.status_code == 200
    assert thumb.headers["content-type"] == "image/jpeg"


async def test_server_folder_photo_ingest(admin_client, tmp_path, monkeypatch):
    import app.routers.ingest as ingest_router

    root = tmp_path / "nas"
    root.mkdir()
    (root / "holiday.jpg").write_bytes(gps_jpeg_bytes())
    monkeypatch.setattr(settings, "ingest_enabled", True)
    monkeypatch.setattr(settings, "ingest_roots", str(root))
    monkeypatch.setattr(ingest_router, "enqueue_import", lambda job_id: None)

    scan = await admin_client.post(
        "/api/v1/ingest/scan",
        json={"path": str(root), "recursive": True, "kind": "photos"},
    )
    assert scan.status_code == 200, scan.text
    assert scan.json()["total"] == 1

    started = await admin_client.post(
        "/api/v1/ingest",
        json={"path": str(root), "mode": "photos", "name": "NAS photos"},
    )
    assert started.status_code == 202, started.text
    job_id = started.json()["id"]
    await tasks._process(job_id)

    job = await admin_client.get(f"/api/v1/imports/{job_id}")
    assert job.status_code == 200
    data = job.json()
    assert data["status"] == "succeeded", data
    assert data["result"]["created_features"] == 1
    assert data["result"]["scanned"] == 1

    features = await admin_client.get(f"/api/v1/layers/{data['layer_id']}/features")
    assert features.json()["meta"]["total"] == 1
    attachments = await admin_client.get(
        f"/api/v1/features/{features.json()['features'][0]['id']}/attachments"
    )
    assert len(attachments.json()) == 1
    content = await admin_client.get(attachments.json()[0]["content_url"])
    assert content.status_code == 200


async def test_create_xyz_overlay(admin_client):
    response = await admin_client.post(
        "/api/v1/overlays/xyz",
        json={
            "name": "Example raster",
            "url_template": "https://1.1.1.1/{z}/{x}/{y}.png",
            "attribution": "Example",
            "visibility": "private",
            "minzoom": 0,
            "maxzoom": 14,
        },
    )
    assert response.status_code == 201, response.text
    layer = response.json()
    assert layer["geometry_type"] == "raster"
    assert layer["metadata"]["provider"] == "xyz"
    assert layer["metadata"]["xyz"]["url"] == "https://1.1.1.1/{z}/{x}/{y}.png"

    fetched = await admin_client.get(f"/api/v1/layers/{layer['id']}")
    assert fetched.status_code == 200


async def test_attach_photo_to_any_feature(admin_client):
    layer = await admin_client.post(
        "/api/v1/layers",
        json={"name": "Survey points", "visibility": "private", "geometry_type": "point"},
    )
    layer_id = layer.json()["id"]
    feature = await admin_client.post(
        f"/api/v1/layers/{layer_id}/features",
        json={
            "properties": {"name": "Bench"},
            "geometry": {"type": "Point", "coordinates": [0.1, 52.2]},
        },
    )
    feature_id = feature.json()["id"]
    added = await admin_client.post(
        f"/api/v1/features/{feature_id}/attachments",
        files={"files": ("bench.jpg", gps_jpeg_bytes(), "image/jpeg")},
    )
    assert added.status_code == 200, added.text
    assert len(added.json()["attachments"]) == 1
    attachment = added.json()["attachments"][0]
    content = await admin_client.get(attachment["content_url"])
    assert content.status_code == 200
    deleted = await admin_client.delete(f"/api/v1/attachments/{attachment['id']}")
    assert deleted.status_code == 200


async def test_osm_import_job(admin_client, monkeypatch):
    import app.routers.osm_data as osm_data_router

    payload = {
        "elements": [
            {
                "type": "way",
                "id": 9001,
                "version": 2,
                "tags": {"building": "yes", "name": "Test Hall"},
                "geometry": [
                    {"lat": 52.2, "lon": 0.1},
                    {"lat": 52.2, "lon": 0.101},
                    {"lat": 52.201, "lon": 0.101},
                    {"lat": 52.201, "lon": 0.1},
                    {"lat": 52.2, "lon": 0.1},
                ],
            }
        ]
    }

    async def fake_fetch(bbox, category):
        return payload

    monkeypatch.setattr(overpass, "fetch_elements", fake_fetch)
    monkeypatch.setattr(osm_data_router, "enqueue_import", lambda job_id: None)
    response = await admin_client.post(
        "/api/v1/osm/import",
        json={
            "bbox": [0.099, 52.199, 0.102, 52.202],
            "category": "buildings",
            "name": "OSM test buildings",
        },
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    await tasks._process(job_id)
    job = (await admin_client.get(f"/api/v1/imports/{job_id}")).json()
    assert job["status"] == "succeeded", job
    assert job["result"]["feature_count"] == 1
    layer_id = job["layer_id"]
    layer = (await admin_client.get(f"/api/v1/layers/{layer_id}")).json()
    assert layer["geometry_type"] == "polygon"
    assert layer["source_type"] == "osm"
    assert layer["metadata"]["provider"] == "osm"
    features = (await admin_client.get(f"/api/v1/layers/{layer_id}/features")).json()
    assert features["meta"]["total"] == 1
    assert features["features"][0]["properties"]["osm_id"] == 9001


async def test_live_weather_and_earthquake_layers(admin_client, monkeypatch):
    async def weather(bbox, grid=None):
        return [
            {
                "properties": {"name": "A", "temperature_c": 12.0},
                "geometry": "POINT(0.0 52.0)",
                "valid": True,
                "error": None,
            },
            {
                "properties": {"name": "B", "temperature_c": 13.0},
                "geometry": "POINT(0.1 52.1)",
                "valid": True,
                "error": None,
            },
        ]

    monkeypatch.setattr(live, "fetch_weather_grid", weather)
    created = await admin_client.post(
        "/api/v1/live/weather/grid",
        json={"bbox": [-0.1, 51.9, 0.2, 52.2], "name": "Weather test"},
    )
    assert created.status_code == 200, created.text
    layer = created.json()
    assert layer["metadata"]["provider"] == "open-meteo"
    features = (await admin_client.get(f"/api/v1/layers/{layer['id']}/features")).json()
    assert features["meta"]["total"] == 2

    async def weather_one(bbox, grid=None):
        return [
            {
                "properties": {"name": "A", "temperature_c": 14.0},
                "geometry": "POINT(0.0 52.0)",
                "valid": True,
                "error": None,
            }
        ]

    monkeypatch.setattr(live, "fetch_weather_grid", weather_one)
    refreshed = await admin_client.post(
        "/api/v1/live/weather/grid",
        json={
            "bbox": [-0.1, 51.9, 0.2, 52.2],
            "layer_id": layer["id"],
            "name": "Weather test",
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    features = (await admin_client.get(f"/api/v1/layers/{layer['id']}/features")).json()
    assert features["meta"]["total"] == 1

    async def quakes(min_magnitude=2.5):
        return [
            {
                "properties": {"name": "M5 test", "magnitude": 5.0},
                "geometry": "POINT(1.0 2.0)",
                "valid": True,
                "error": None,
            }
        ]

    monkeypatch.setattr(live, "fetch_earthquakes", quakes)
    quake = await admin_client.post(
        "/api/v1/live/earthquakes",
        json={"min_magnitude": 4.5, "name": "Quake test"},
    )
    assert quake.status_code == 200, quake.text
    assert quake.json()["metadata"]["provider"] == "usgs-earthquakes"
