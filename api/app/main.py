"""Strata FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import redis.asyncio as redis
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import settings
from .database import SessionLocal, check_database, engine
from .logging import configure_logging
from .middleware import RequestContextMiddleware
from .routers import (
    admin,
    auth,
    features,
    imports,
    ingest,
    layers,
    live,
    osm,
    osm_data,
    overlays,
    photos,
    tessera,
    tiles,
    tools,
    uploads,
)
from .schemas import HealthResponse

configure_logging(settings.log_level, settings.json_logs)
logger = logging.getLogger("nasmap")
if settings.is_production and settings.secret_key in {
    "dev-only-change-me",
    "change-me-to-a-long-random-string",
}:
    logger.warning(
        "SECRET_KEY is still set to the example value; rotate it before exposing this instance"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.tessera_cache_dir.mkdir(parents=True, exist_ok=True)
    settings.tiles_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Strata API starting (env=%s)", settings.env)
    yield
    await engine.dispose()
    logger.info("Strata API stopped")


app = FastAPI(
    title="Strata API",
    version=__version__,
    description=(
        "Self-hosted private geospatial layers, OSM basemaps, remote data imports "
        "and Tessera satellite embeddings."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Content-Disposition"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    code = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        413: "payload_too_large",
        429: "rate_limited",
    }.get(exc.status_code, "http_error")
    detail = exc.detail
    message = detail if isinstance(detail, str) else "Request failed"
    payload = {
        "error": {
            "code": code,
            "message": message,
            "details": None if isinstance(detail, str) else detail,
        }
    }
    headers = getattr(exc, "headers", None)
    return JSONResponse(payload, status_code=exc.status_code, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        {
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": exc.errors(),
            }
        },
        status_code=422,
    )


@app.exception_handler(DataError)
async def data_error_handler(request: Request, exc: DataError):
    logger.warning("invalid database value on %s %s", request.method, request.url.path)
    return JSONResponse(
        {
            "error": {
                "code": "invalid_value",
                "message": "Invalid identifier or value in the request",
                "details": None,
            }
        },
        status_code=422,
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    logger.warning("database constraint violation on %s %s", request.method, request.url.path)
    return JSONResponse(
        {
            "error": {
                "code": "conflict",
                "message": "The request conflicts with existing data",
                "details": None,
            }
        },
        status_code=409,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        {"error": {"code": "internal_error", "message": "An internal error occurred"}},
        status_code=500,
    )


@app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
async def health(response: Response):
    services: dict[str, str] = {}
    try:
        await check_database()
        services["database"] = "ok"
    except Exception:  # noqa: BLE001
        services["database"] = "error"
    try:
        client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
        await client.ping()
        await client.aclose()
        services["redis"] = "ok"
    except Exception:  # noqa: BLE001
        services["redis"] = "error"
    status = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    return HealthResponse(
        status=status, version=__version__, time=datetime.now(UTC), services=services
    )


@app.get("/api/v1/config", tags=["system"])
async def public_config():
    """Non-secret runtime configuration consumed by the web client."""
    return {
        "app_name": settings.app_name,
        "basemap_mode": settings.basemap_mode,
        "osm_tile_url": (
            "/api/v1/basemap/osm/{z}/{x}/{y}.png"
            if settings.osm_tile_proxy
            else settings.osm_tile_url
        ),
        "osm_tile_attribution": settings.osm_tile_attribution,
        "tileserver_public_url": settings.tileserver_public_url,
        "registration_enabled": settings.registration_enabled,
        "osm_oauth_enabled": settings.osm_oauth_enabled,
        "tessera_enabled": settings.tessera_enabled,
        "max_upload_mb": settings.max_upload_mb,
        "max_photo_mb": settings.max_photo_mb,
        "max_attachment_mb": settings.max_attachment_mb,
        "max_url_import_mb": settings.max_url_import_mb,
    }


@app.get("/api/v1/system/status", tags=["system"])
async def system_status(request: Request):
    # Imported lazily to avoid circular imports during startup.
    from .auth import get_optional_user

    user = await get_optional_user(request)
    if not user or user.role != "admin":
        raise StarletteHTTPException(status_code=403, detail="Admin access required")
    async with SessionLocal() as db:
        counts = {}
        for table, key in (
            ("app.users", "users"),
            ("app.layers", "layers"),
            ("app.features", "features"),
            ("imports.import_jobs", "import_jobs"),
        ):
            value = await db.scalar(text(f"SELECT count(*) FROM {table}"))
            counts[key] = int(value or 0)
    return {"counts": counts, "version": __version__, "env": settings.env}


app.include_router(auth.router, prefix="/api/v1")
app.include_router(layers.router, prefix="/api/v1")
app.include_router(features.router, prefix="/api/v1")
app.include_router(uploads.router, prefix="/api/v1")
app.include_router(photos.router, prefix="/api/v1")
app.include_router(ingest.router, prefix="/api/v1")
app.include_router(overlays.router, prefix="/api/v1")
app.include_router(osm_data.router, prefix="/api/v1")
app.include_router(live.router, prefix="/api/v1")
app.include_router(imports.router, prefix="/api/v1")
app.include_router(tessera.router, prefix="/api/v1")
app.include_router(osm.router, prefix="/api/v1")
app.include_router(tiles.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
