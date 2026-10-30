"""RQ worker with a heartbeat file and a lightweight refresh scheduler."""

from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import redis
from rq import Queue, Worker

from ..config import settings
from ..logging import configure_logging
from ..redis_client import get_queue_connection
from .queue import QUEUE_NAME
from .tasks import enqueue_due_refreshes

configure_logging(settings.log_level, settings.json_logs)
logger = logging.getLogger("nasmap.worker.runner")
HEARTBEAT = Path(os.environ.get("WORKER_HEALTH_FILE", settings.worker_health_file))
_stop = threading.Event()


def heartbeat_loop() -> None:
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    while not _stop.is_set():
        HEARTBEAT.write_text(datetime.now(UTC).isoformat())
        _stop.wait(10)


def scheduler_loop() -> None:
    conn = get_queue_connection()
    lock_key = "nasmap:refresh-scheduler-lock"
    while not _stop.is_set():
        try:
            if conn.set(lock_key, "1", nx=True, ex=180):
                created = enqueue_due_refreshes()
                if created:
                    logger.info("scheduled %s external source refresh job(s)", created)
        except Exception:  # noqa: BLE001
            logger.exception("scheduled refresh check failed")
        _stop.wait(60)


def main() -> None:
    conn = get_queue_connection()
    try:
        conn.ping()
    except redis.RedisError as exc:
        logger.error("redis is not reachable: %s", exc)
        raise SystemExit(1) from exc

    threads = [
        threading.Thread(target=heartbeat_loop, name="heartbeat", daemon=True),
        threading.Thread(target=scheduler_loop, name="scheduler", daemon=True),
    ]
    for thread in threads:
        thread.start()

    HEARTBEAT.write_text(datetime.now(UTC).isoformat())
    queue = Queue(QUEUE_NAME, connection=conn)
    worker = Worker([queue], connection=conn, name=f"nasmap-{os.getpid()}")
    logger.info("worker listening on queue %s", QUEUE_NAME)
    try:
        worker.work(with_scheduler=False)
    finally:
        _stop.set()


if __name__ == "__main__":
    main()
