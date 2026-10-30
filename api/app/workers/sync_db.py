"""Thread-safe synchronous job updates used by progress callbacks.

GeoTessera and GDAL run in worker threads. They cannot touch the async
SQLAlchemy session, so this tiny psycopg2 helper updates a job row and checks
the cancellation flag from those threads.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg2
from psycopg2.extras import Json

from ..config import settings


def _connect():
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return psycopg2.connect(dsn, connect_timeout=10)


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    allowed = {
        "status",
        "progress",
        "message",
        "error",
        "result",
        "started_at",
        "finished_at",
        "layer_id",
    }
    updates = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        updates.append(f"{key} = %s")
        values.append(Json(value) if key == "result" else value)
    if not updates:
        return
    values.append(job_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE imports.import_jobs SET {', '.join(updates)} WHERE id = %s",
                values,
            )
        conn.commit()


def is_cancelled(job_id: str) -> bool:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT cancel_requested FROM imports.import_jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    return bool(row and row[0])


def job_status(job_id: str) -> str | None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM imports.import_jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    return row[0] if row else None


def set_result_json(job_id: str, result: dict[str, Any]) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE imports.import_jobs SET result = %s WHERE id = %s",
                (json.dumps(result), job_id),
            )
        conn.commit()
