from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from smart_pdf2md.web.routes import admin, auth, documents, jobs, providers
from smart_pdf2md.web.settings import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        settings = get_settings()
        if settings.cookie_secure:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        csp = (
            f"default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' https://cdn.tailwindcss.com https://unpkg.com; "
            f"style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            f"img-src 'self' data:; "
            f"connect-src 'self'; "
            f"font-src 'self' data:; "
            f"frame-ancestors 'none'; "
            f"base-uri 'self'; "
            f"form-action 'self'"
        )
        response.headers.setdefault("Content-Security-Policy-Report-Only", csp)
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    settings.web_data_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="smart-pdf2md", version="0.1.0")
    app.state.rq_is_async = True
    app.state.redis = None
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(auth.router)
    app.include_router(documents.router)
    app.include_router(providers.router)
    app.include_router(jobs.router)
    app.include_router(admin.router)

    static_dir = Path(__file__).resolve().parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates = Jinja2Templates(
        directory=str(Path(__file__).resolve().parent / "templates")
    )

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "allow_register": get_settings().web_allow_register,
                "csp_nonce": getattr(request.state, "csp_nonce", ""),
            },
        )

    return app


app = create_app()
