from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class WebSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://smartmd:smartmd@localhost:5432/smartmd"
    redis_url: str = "redis://localhost:6379/0"
    web_data_dir: Path = Path("data/web")
    web_secret_key: str = "change-me-in-production"
    web_default_credits: int = 10
    web_session_days: int = 14
    web_max_upload_mb: int = 50
    web_csrf_header: str = "x-csrf-token"
    # Public self-serve signup; default off for internal/trusted deploy.
    # Set WEB_ALLOW_REGISTER=true to enable GET/POST /register.
    web_allow_register: bool = False
    # Secure cookies by default (requires HTTPS / reverse proxy TLS).
    # Set COOKIE_SECURE=false for local HTTP.
    cookie_secure: bool = True
    cookie_name: str = "smartmd_session"
    # RQ kills the whole convert job after this many seconds (floor).
    web_job_timeout_seconds: int = 1800
    # Extra budget: OCR pages × this (HTTP timeout is 120s/page; leave headroom).
    web_job_timeout_per_page_seconds: int = 180
    # ETA seed used until the user has job history for a backend.
    web_eta_default_seconds_per_page: float = 25.0
    web_eta_paddle_seconds_per_page: float = 8.0
    # Parallel OCR threads per render batch (passed to convert_full).
    web_ocr_concurrency: int = 4
    # Max concurrent SSE event streams per user (429 past this).
    web_sse_max_streams_per_user: int = 4
    # Absolute ceiling for a single SSE connection (seconds).
    web_sse_max_duration_seconds: int = 3600


@lru_cache
def get_settings() -> WebSettings:
    return WebSettings()
