import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models import Feature
from app.routers import osm as osm_router
from app.services import osm, overpass, remote


def test_private_addresses_blocked():
    for url in (
        "http://127.0.0.1/",
        "http://localhost/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/data.geojson",
        "http://[::1]/",
        "http://192.168.1.10/",
    ):
        with pytest.raises(remote.UnsafeURLError):
            remote.validate_url(url)


def test_non_http_scheme_blocked():
    with pytest.raises(remote.UnsafeURLError):
        remote.validate_url("file:///etc/passwd")


def test_changeset_xml_escapes_values():
    xml = osm.changeset_xml('Survey "A" & B', "Strata", {"locale": "en"})
    assert "comment" in xml
    assert "&amp;" in xml
    assert "Survey" in xml
    assert 'k="locale" v="en"' in xml


def test_osm_change_create_and_modify():
    create = osm.osm_change_xml(
        lat=52.2, lon=0.12, tags={"amenity": "bench"}, osm_id=None, osm_version=None
    )
    assert "<create>" in create
    assert 'id="-1"' in create

    modify = osm.osm_change_xml(
        lat=52.2,
        lon=0.12,
        tags={"amenity": "bench"},
        osm_id=123,
        osm_version=4,
        changeset_id=99,
    )
    assert "<modify>" in modify
    assert 'id="123"' in modify
    assert 'version="4"' in modify
    assert 'changeset="99"' in modify


def test_parse_lat_lon_rejects_lines():
    with pytest.raises(HTTPException):
        osm.parse_lat_lon({"type": "LineString", "coordinates": [[0, 0], [1, 1]]})


def test_osm_login_state_roundtrip_and_tamper():
    state = osm.login_state("/map")
    payload = osm.decode_login_state(state)
    assert payload is not None
    assert payload["redirect_to"] == "/map"
    assert osm.decode_login_state(state + "x") is None


def test_merge_tags_keeps_existing_and_drops_photo_metadata():
    tags = osm.merge_tags(
        {"name": "Old name", "amenity": "cafe"},
        {"name": "New name", "photo_filename": "x.jpg", "photo_camera": "Fujifilm"},
    )
    assert tags == {"name": "New name", "amenity": "cafe"}


def test_nearby_nodes_sorted_and_untagged_skipped():
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 51.5001, "lon": 0.0, "tags": {}},
            {
                "type": "node",
                "id": 2,
                "version": 3,
                "lat": 51.5003,
                "lon": 0.0,
                "tags": {"amenity": "bench"},
            },
            {
                "type": "node",
                "id": 3,
                "version": 2,
                "lat": 51.5000,
                "lon": 0.0,
                "tags": {"name": "Cafe", "amenity": "cafe"},
            },
        ]
    }
    nodes = overpass.parse_nearby_nodes(payload, 51.5, 0.0)
    assert [node["osm_id"] for node in nodes] == [3, 2]
    assert nodes[0]["name"] == "Cafe"
    assert nodes[0]["distance_m"] == 0.0


def test_nearby_query_is_bounded():
    query = overpass.build_nearby_query(51.5, -0.12, 999)
    assert "around:500" in query
    assert "51.5000000,-0.1200000" in query
    assert "out body 200" in query


def test_prepare_attaches_to_existing_node_and_keeps_tags(monkeypatch):
    async def fake_fetch(osm_id, access_token=None):
        assert osm_id == 123
        return {
            "type": "node",
            "id": 123,
            "version": 7,
            "lat": 51.5,
            "lon": -0.12,
            "tags": {"amenity": "cafe", "name": "Old name"},
        }

    monkeypatch.setattr(osm, "fetch_node", fake_fetch)
    feature = Feature(properties={"name": "New name", "photo_filename": "secret.jpg"})
    payload = osm_router.PreviewIn(
        feature_id=uuid4(),
        comment="Attach survey",
        tags={"name": "New name"},
        osm_id=123,
    )
    tags, _, diff, osm_id, version, existing, lat, lon = asyncio.run(
        osm_router._prepare(feature, payload, {"type": "Point", "coordinates": [0, 0]})
    )
    assert osm_id == 123
    assert version == 7
    assert tags == {"amenity": "cafe", "name": "New name"}
    assert existing == {"amenity": "cafe", "name": "Old name"}
    assert (lat, lon) == (51.5, -0.12)
    assert 'id="123"' in diff
    assert 'version="7"' in diff
    assert "secret.jpg" not in diff
