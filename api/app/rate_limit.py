"""Small Redis fixed-window rate limiter.

If Redis is unavailable the request is allowed: authentication still requires
valid credentials and the API remains usable during a cache outage.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from .config import settings
from .middleware import client_ip
from .redis_client import get_redis

logger = logging.getLogger("nasmap.ratelimit")


async def _check(request: Request, bucket: str, limit: int, window: int) -> None:
    if not settings.rate_limiting_enabled or limit <= 0:
        return
    key = f"nasmap:rl:{bucket}:{client_ip(request)}"
    try:
        client = get_redis()
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window, nx=True)
        count, _ = await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("rate limiter unavailable: %s", exc)
        return
    if int(count) > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait and try again.",
            headers={"Retry-After": str(window)},
        )


async def auth_rate_limit(request: Request) -> None:
    await _check(request, "auth", settings.auth_rate_limit, settings.auth_rate_window_seconds)


async def upload_rate_limit(request: Request) -> None:
    await _check(request, "upload", settings.upload_rate_limit, settings.upload_rate_window_seconds)
