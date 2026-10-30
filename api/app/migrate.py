"""Idempotent SQL migration runner.

The compose stack also mounts db/init into the Postgres entrypoint. Both paths
are safe: every migration is written with IF NOT EXISTS / OR REPLACE guards and
is recorded in app.schema_migrations.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import asyncpg

from .config import settings

logger = logging.getLogger("nasmap.migrate")
_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "db" / "init",
    Path(__file__).resolve().parents[1] / "db" / "init",
]
MIGRATIONS_DIR = next((path for path in _CANDIDATES if path.is_dir()), _CANDIDATES[0])


def _dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def wait_for_db(attempts: int = 60, delay: float = 2.0) -> None:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            conn = await asyncpg.connect(_dsn(), timeout=5)
            await conn.close()
            return
        except Exception as exc:  # noqa: BLE001 - startup retry loop
            last_error = exc
            if attempt % 5 == 0:
                logger.warning("waiting for database (%s/%s): %s", attempt, attempts, exc)
            await asyncio.sleep(delay)
    raise RuntimeError(f"database not ready: {last_error}")


async def apply_migrations() -> int:
    await wait_for_db()
    conn = await asyncpg.connect(_dsn())
    applied = 0
    try:
        # Serialize concurrent API/worker startups on the same database.
        await conn.execute("SELECT pg_advisory_lock(7272701)")
        await conn.execute(
            """
            CREATE SCHEMA IF NOT EXISTS app;
            CREATE TABLE IF NOT EXISTS app.schema_migrations (
                filename text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            );
            """
        )
        done = {
            r["filename"] for r in await conn.fetch("SELECT filename FROM app.schema_migrations")
        }
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            logger.info("applying migration %s", path.name)
            await conn.execute(path.read_text(encoding="utf-8"))
            await conn.execute(
                "INSERT INTO app.schema_migrations(filename) VALUES($1) ON CONFLICT DO NOTHING",
                path.name,
            )
            applied += 1
    finally:
        try:
            await conn.execute("SELECT pg_advisory_unlock(7272701)")
        except Exception:  # noqa: BLE001
            pass
        await conn.close()
    logger.info("migrations complete (%s applied)", applied)
    return applied


def main() -> None:
    logging.basicConfig(level=settings.log_level)
    asyncio.run(apply_migrations())


if __name__ == "__main__":
    main()
