"""Redis helpers used by rate limiting, queues and OAuth state."""

from __future__ import annotations

import redis.asyncio as redis

from .config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def get_queue_connection():
    import redis as sync_redis

    return sync_redis.from_url(settings.redis_url)
