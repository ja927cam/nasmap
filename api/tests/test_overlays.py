import pytest
from fastapi import HTTPException

from app.routers import overlays


def test_xyz_template_validation():
    template = "https://example.com/{z}/{x}/{y}.png"
    assert overlays._validate_template(template) == template
    with pytest.raises(HTTPException):
        overlays._validate_template("https://example.com/tiles.png")
    with pytest.raises(HTTPException):
        overlays._validate_template("file:///tmp/{z}/{x}/{y}.png")


def test_bounds_validation():
    assert overlays._bounds(None) == [-180, -85, 180, 85]
    assert overlays._bounds([-1, -2, 3, 4]) == [-1, -2, 3, 4]
    with pytest.raises(HTTPException):
        overlays._bounds([3, -2, -1, 4])
