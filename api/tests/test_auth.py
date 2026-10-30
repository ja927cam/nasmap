from .conftest import register


async def test_register_login_refresh_logout(client):
    data = await register(client, "first@example.org")
    assert data["user"]["role"] == "admin"
    assert data["user"]["email"] == "first@example.org"
    assert data["access_token"]

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "admin"

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    logged_out = await client.post("/api/v1/auth/logout")
    assert logged_out.status_code == 200


async def test_duplicate_email_rejected(client):
    await register(client, "dupe@example.org")
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "dupe@example.org", "password": "another-password", "display_name": "Dupe"},
    )
    assert response.status_code == 409


async def test_login_rejects_bad_password(client):
    await register(client, "login@example.org")
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.org", "password": "definitely-wrong"},
    )
    assert response.status_code == 401


async def test_second_user_is_viewer(client):
    await register(client, "admin@example.org")
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "second@example.org",
            "password": "a-long-password",
            "display_name": "Second",
        },
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "viewer"
