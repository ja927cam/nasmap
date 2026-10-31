from app.routers import osm as osm_router
from app.services import osm


async def _point_feature(admin_client):
    layer = await admin_client.post(
        "/api/v1/layers",
        json={"name": "OSM attachment test", "visibility": "private", "geometry_type": "point"},
    )
    layer_id = layer.json()["id"]
    feature = await admin_client.post(
        f"/api/v1/layers/{layer_id}/features",
        json={
            "properties": {"name": "Bench survey", "photo_filename": "private.jpg"},
            "geometry": {"type": "Point", "coordinates": [0.1, 52.2]},
        },
    )
    return feature.json()


async def test_nearby_nodes_endpoint(admin_client, monkeypatch):
    feature = await _point_feature(admin_client)

    async def fake_nearby(lat, lon, radius_m):
        assert (lat, lon, radius_m) == (52.2, 0.1, 25)
        return [
            {
                "osm_id": 42,
                "osm_version": 3,
                "lat": 52.2001,
                "lon": 0.1001,
                "distance_m": 12.3,
                "tags": {"amenity": "bench"},
                "name": "bench",
            }
        ]

    monkeypatch.setattr(osm_router.overpass, "fetch_nearby_nodes", fake_nearby)
    response = await admin_client.post(
        "/api/v1/osm/nearby",
        json={"feature_id": feature["id"], "radius_m": 25},
    )
    assert response.status_code == 200, response.text
    assert response.json()["nodes"][0]["osm_id"] == 42


async def test_preview_attaches_to_existing_node(admin_client, monkeypatch):
    feature = await _point_feature(admin_client)

    async def fake_fetch(osm_id, access_token=None):
        assert osm_id == 42
        return {
            "type": "node",
            "id": 42,
            "version": 8,
            "lat": 52.2002,
            "lon": 0.1002,
            "tags": {"amenity": "bench", "name": "Old bench"},
        }

    monkeypatch.setattr(osm, "fetch_node", fake_fetch)
    response = await admin_client.post(
        "/api/v1/osm/preview",
        json={
            "feature_id": feature["id"],
            "comment": "Attach bench survey",
            "source": "Strata survey",
            "tags": {"name": "New bench"},
            "osm_id": 42,
        },
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["action"] == "modify"
    assert preview["osm_id"] == 42
    assert preview["lat"] == 52.2002
    assert preview["lon"] == 0.1002
    assert preview["tags"] == {"amenity": "bench", "name": "New bench"}
    assert preview["existing_tags"] == {"amenity": "bench", "name": "Old bench"}
    assert "photo_filename" not in preview["diff_xml"]
