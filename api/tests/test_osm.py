import pytest
from fastapi import HTTPException

from app.services import osm, remote


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
