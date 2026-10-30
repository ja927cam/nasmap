"""HTTP middleware: request ids, access logs and security headers."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .logging import request_id_ctx

logger = logging.getLogger("nasmap.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request failed",
                extra={"method": request.method, "path": request.url.path},
            )
            raise
        finally:
            request_id_ctx.reset(token)

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        logger.info(
            f"{request.method} {request.url.path} {response.status_code}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Caddy is the only trusted hop in the default stack. It appends the
        # direct peer address, so use the last entry rather than a spoofable
        # client-supplied prefix.
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "127.0.0.1"
