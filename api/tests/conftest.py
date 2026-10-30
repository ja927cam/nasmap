from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest

TEST_DB = (
    os.getenv("TEST_DATABASE_URL")
    or os.getenv("DATABASE_URL")
    or "postgresql+asyncpg://nasmap:nasmap@localhost:5432/nasmap_test"
)
os.environ.setdefault("DATABASE_URL", TEST_DB)
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-for-tests")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("JSON_LOGS", "false")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("TESSERA_ENABLED", "false")
os.environ.setdefault("UPLOAD_DIR", "/tmp/nasmap-test/uploads")
os.environ.setdefault("TESSERA_CACHE_DIR", "/tmp/nasmap-test/tessera")
os.environ.setdefault("TILES_DIR", "/tmp/nasmap-test/tiles")
os.environ.setdefault("FIRST_USER_IS_ADMIN", "true")
os.environ.setdefault("REGISTRATION_ENABLED", "true")

from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import apply_migrations  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CANDIDATES = [
    ROOT / "sample-data",
    Path(__file__).resolve().parents[1] / "sample-data",
]
SAMPLE_DIR = next((path for path in SAMPLE_CANDIDATES if path.is_dir()), SAMPLE_CANDIDATES[0])


def sync_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest.fixture(scope="session")
def migrated_database():
    try:
        asyncio.run(apply_migrations())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostGIS test database unavailable: {exc}")


async def _clean_database():
    conn = await asyncpg.connect(sync_dsn())
    try:
        await conn.execute("TRUNCATE app.users CASCADE")
        await conn.execute("TRUNCATE imports.import_jobs CASCADE")
    finally:
        await conn.close()


@pytest.fixture
async def client(migrated_database):
    await _clean_database()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http


@pytest.fixture
def sample_path():
    return SAMPLE_DIR


async def register(client: AsyncClient, email: str, password: str = "correct-horse-battery"):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": email.split("@")[0]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    client.headers["Authorization"] = f"Bearer {payload['access_token']}"
    return payload


@pytest.fixture
async def admin_client(client):
    await register(client, "admin@example.org")
    return client
