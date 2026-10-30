"""Enqueue helpers shared by API routers."""

from __future__ import annotations

from rq import Queue

from ..redis_client import get_queue_connection

QUEUE_NAME = "nasmap"


def queue() -> Queue:
    return Queue(QUEUE_NAME, connection=get_queue_connection())


def enqueue_import(job_id: str) -> None:
    from .tasks import process_import_job

    queue().enqueue(
        process_import_job,
        job_id,
        job_id=f"import:{job_id}",
        job_timeout=60 * 60 * 12,
        result_ttl=86400,
        failure_ttl=86400 * 7,
    )
