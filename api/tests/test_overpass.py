from app.services import overpass


def test_building_way_becomes_polygon():
    element = {
        "type": "way",
        "id": 10,
        "tags": {"building": "yes", "name": "Hall"},
        "geometry": [
            {"lat": 52.0, "lon": 0.0},
            {"lat": 52.0, "lon": 0.1},
            {"lat": 52.1, "lon": 0.1},
            {"lat": 52.1, "lon": 0.0},
            {"lat": 52.0, "lon": 0.0},
        ],
    }
    geom, kind, tags = overpass.element_geometry(element)
    assert kind == "Polygon"
    assert geom.geom_type == "Polygon"
    assert tags["building"] == "yes"


def test_road_way_becomes_line():
    element = {
        "type": "way",
        "id": 11,
        "tags": {"highway": "residential"},
        "geometry": [{"lat": 52.0, "lon": 0.0}, {"lat": 52.1, "lon": 0.1}],
    }
    geom, kind, _ = overpass.element_geometry(element)
    assert kind == "LineString"
    assert geom.geom_type == "LineString"


def test_node_and_parse_records():
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 12,
                "version": 3,
                "tags": {"amenity": "bench"},
                "lat": 52.2,
                "lon": 0.1,
            }
        ]
    }
    records, stats = overpass.parse_elements(payload, "amenities")
    assert stats["feature_count"] == 1
    assert records[0]["geometry"].startswith("POINT")
    assert records[0]["properties"]["osm_id"] == 12
    assert records[0]["properties"]["osm_version"] == 3


def test_query_contains_bbox_and_category():
    query = overpass.build_query((-1.0, 51.0, 0.0, 52.0), "buildings")
    assert "51.0,-1.0,52.0,0.0" in query
    assert 'nwr["building"]' in query
