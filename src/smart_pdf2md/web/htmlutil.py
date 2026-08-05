"""Shared HTML / HTMX helpers for the web UI."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Optional

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from smart_pdf2md.web.deps import load_session
from smart_pdf2md.web.models import User
from smart_pdf2md.web.settings import get_settings

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

CSRF_COOKIE_NAME = "csrf"


def html_error(message: str, status_code: int) -> HTMLResponse:
    """Return a short HTML error fragment with the message escaped."""
    return HTMLResponse(html.escape(str(message)), status_code=status_code)


def wants_html(request: Request) -> bool:
    """True for browser/HTMX HTML responses; False for JSON API clients."""
    if request.headers.get("hx-request", "").lower() == "true":
        return True
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return False
    return "text/html" in accept


def hx_redirect(request: Request, url: str) -> Response:
    """Navigate the browser after a POST, for both htmx and plain form posts.

    XHR follows a 303 transparently, so htmx only ever sees the final GET and an
    HX-Redirect header set on the redirect itself is lost. htmx needs a bodyless
    response carrying the header instead.
    """
    if request.headers.get("hx-request", "").lower() == "true":
        return Response(status_code=204, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


def set_csrf_cookie(response: Response, csrf_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.web_session_days * 86400,
        path="/",
    )


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


def shell_context(
    request: Request,
    db: Session,
    user: Optional[User],
    **extra: Any,
) -> dict[str, Any]:
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    _, row = load_session(db, token)
    ctx: dict[str, Any] = {
        "request": request,
        "user": user,
        "credits": user.credits if user else 0,
        "csrf_token": row.csrf_token if row else "",
        "is_admin": bool(user and user.role == "admin"),
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
    }
    ctx.update(extra)
    return ctx


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "on", "yes"}
