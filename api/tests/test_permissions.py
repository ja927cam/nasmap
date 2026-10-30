from httpx import ASGITransport, AsyncClient

from app.main import app

from .conftest import register


async def test_private_layer_hidden_and_granted(admin_client):
    layer_resp = await admin_client.post(
        "/api/v1/layers",
        json={"name": "Private survey", "visibility": "private", "geometry_type": "point"},
    )
    assert layer_resp.status_code == 201, layer_resp.text
    layer = layer_resp.json()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as viewer:
        await register(viewer, "viewer@example.org")
        listing = await viewer.get("/api/v1/layers")
        assert listing.status_code == 200
        assert listing.json()["meta"]["total"] == 0

        hidden = await viewer.get(f"/api/v1/layers/{layer['id']}")
        assert hidden.status_code == 403

        grant = await admin_client.post(
            f"/api/v1/layers/{layer['id']}/permissions",
            json={"email": "viewer@example.org", "role": "viewer"},
        )
        assert grant.status_code == 201, grant.text

        visible = await viewer.get(f"/api/v1/layers/{layer['id']}")
        assert visible.status_code == 200

        denied = await viewer.post(
            f"/api/v1/layers/{layer['id']}/features",
            json={"properties": {}, "geometry": {"type": "Point", "coordinates": [0.1, 52.2]}},
        )
        assert denied.status_code == 403


async def test_public_layer_is_readable(admin_client):
    layer = await admin_client.post(
        "/api/v1/layers",
        json={"name": "Public parks", "visibility": "public", "geometry_type": "polygon"},
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as viewer:
        await register(viewer, "public-viewer@example.org")
        response = await viewer.get(f"/api/v1/layers/{layer.json()['id']}")
        assert response.status_code == 200
        assert response.json()["access_role"] == "viewer"


async def test_viewer_cannot_create_layers(client):
    await register(client, "admin@example.org")
    async with AsyncClient(base_url="http://testserver", transport=client._transport) as viewer:
        await register(viewer, "readonly@example.org")
        response = await viewer.post(
            "/api/v1/layers",
            json={"name": "Nope", "visibility": "private", "geometry_type": "point"},
        )
        assert response.status_code == 403
