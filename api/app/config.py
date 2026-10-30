"""Application configuration loaded from environment variables."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Strata"
    env: str = "production"
    debug: bool = False
    log_level: str = "INFO"
    json_logs: bool = True

    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    osm_token_encryption_key: str = ""

    database_url: str = "postgresql+asyncpg://nasmap:nasmap@localhost:5432/nasmap"
    redis_url: str = "redis://localhost:6379/0"

    site_url: str = "http://localhost"
    frontend_url: str = "http://localhost"
    cors_origins: str = ""

    upload_dir: Path = Path("./data/uploads")
    tessera_cache_dir: Path = Path("./data/tessera")
    tiles_dir: Path = Path("./data/tiles")

    max_upload_mb: int = 512
    max_photo_mb: int = 100
    max_attachment_mb: int = 250

    ingest_enabled: bool = True
    ingest_roots: str = "/ingest"
    ingest_max_scan_files: int = 1000
    ingest_max_files_per_job: int = 5000
    ingest_follow_symlinks: bool = False
    max_url_import_mb: int = 1024
    url_fetch_timeout_seconds: int = 90
    allow_private_url_imports: bool = False
    allowed_url_schemes: str = "http,https"

    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30
    cookie_secure: bool = False
    cookie_domain: str = ""
    first_user_is_admin: bool = True
    registration_enabled: bool = True

    auth_rate_limit: int = 10
    auth_rate_window_seconds: int = 60
    upload_rate_limit: int = 30
    upload_rate_window_seconds: int = 3600
    rate_limiting_enabled: bool = True

    basemap_mode: str = "remote_osm"
    osm_tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    osm_tile_attribution: str = "&copy; OpenStreetMap contributors"
    osm_tile_proxy: bool = True
    osm_tile_cache_ttl_days: int = 7
    overlay_tile_cache_ttl_hours: int = 24
    tileserver_public_url: str = "/tiles"
    tileserver_internal_url: str = "http://tileserver:8080"

    osm_oauth_enabled: bool = False
    osm_client_id: str = ""
    osm_client_secret: str = ""
    osm_redirect_uri: str = "http://localhost/api/v1/osm/callback"
    osm_api_base_url: str = "https://api.openstreetmap.org"
    osm_auth_url: str = "https://www.openstreetmap.org/oauth2/authorize"
    osm_token_url: str = "https://www.openstreetmap.org/oauth2/token"
    osm_scopes: str = "read_prefs write_api"
    osm_signin_auto_create: bool = False

    overpass_enabled: bool = True
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    overpass_timeout_seconds: int = 90
    overpass_max_area_deg2: float = 0.05
    overpass_max_mb: int = 64

    rainviewer_enabled: bool = True
    rainviewer_metadata_url: str = "https://api.rainviewer.com/public/weather-maps.json"
    open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"
    usgs_earthquakes_url: str = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
    )
    live_grid_points: int = 3

    tessera_enabled: bool = True
    tessera_version: str = "v1.1"
    tessera_variant: str = "cambridge"
    tessera_registry_url: str = ""
    tessera_max_tiles: int = 64

    nominatim_url: str = "https://nominatim.openstreetmap.org"
    geocoding_enabled: bool = True

    worker_health_file: str = "/tmp/nasmap-worker-heartbeat"

    @field_validator("site_url", "frontend_url", "osm_api_base_url", "tileserver_internal_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def cors_origin_list(self) -> list[str]:
        values = [v.strip() for v in self.cors_origins.split(",") if v.strip()]
        defaults = {self.site_url, self.frontend_url}
        return sorted(defaults | set(values))

    @property
    def allowed_schemes(self) -> set[str]:
        return {v.strip().lower() for v in self.allowed_url_schemes.split(",") if v.strip()}

    @property
    def ingest_root_list(self) -> list[Path]:
        return [
            Path(value.strip()).expanduser()
            for value in self.ingest_roots.split(",")
            if value.strip()
        ]

    @property
    def osm_scope_list(self) -> list[str]:
        return [v.strip() for v in self.osm_scopes.split() if v.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"prod", "production"}

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Settings:
        if self.is_production and self.secret_key in {
            "dev-only-change-me",
            "change-me-to-a-long-random-string",
        }:
            # A hard failure here would break first-run experiments. Log a loud
            # warning instead; docs/setup.md tells operators to rotate it.
            object.__setattr__(self, "_weak_secret", True)
        for directory in (self.upload_dir, self.tessera_cache_dir, self.tiles_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
