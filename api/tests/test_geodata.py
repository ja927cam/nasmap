import json

from app.services import geodata


def test_geojson_detection_and_validation(tmp_path):
    path = tmp_path / "points.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "One", "value": 1},
                        "geometry": {"type": "Point", "coordinates": [0.12, 52.2]},
                    },
                    {
                        "type": "Feature",
                        "properties": {"name": "Bad"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]],
                        },
                    },
                ],
            }
        )
    )
    result = geodata.inspect_vector(path)
    assert result["stats"]["feature_count"] == 2
    assert result["stats"]["invalid_count"] == 1
    assert result["stats"]["repaired_count"] == 1
    assert result["geometry_type"] == "geometry"
    assert result["crs"] == "EPSG:4326"


def test_csv_lat_lon(tmp_path):
    path = tmp_path / "places.csv"
    path.write_text("name,lat,lon\nCambridge,52.2053,0.1218\n")
    result = geodata.inspect_vector(path)
    assert result["stats"]["feature_count"] == 1
    assert result["geometry_type"] == "point"
    assert result["records"][0]["properties"]["name"] == "Cambridge"


def test_csv_wkt(tmp_path):
    path = tmp_path / "lines.csv"
    path.write_text('name,geom\nA,"LINESTRING (0 0, 1 1)"\n')
    result = geodata.inspect_vector(path)
    assert result["geometry_type"] == "line"


def test_unsupported_extension():
    try:
        geodata.detect_kind("data.docx")
    except ValueError as exc:
        assert "Unsupported" in str(exc)
    else:
        raise AssertionError("expected ValueError")
