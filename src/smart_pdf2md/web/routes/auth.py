from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from smart_pdf2md.web.credits import grant_signup_credits
from smart_pdf2md.web.deps import DbSession, require_csrf, require_user
from smart_pdf2md.web.htmlutil import (
    clear_csrf_cookie,
    hx_redirect,
    set_csrf_cookie,
    templates,
    wants_html,
)
from smart_pdf2md.web.models import LoginAttempt, SessionRow, User
from smart_pdf2md.web.security import (
    hash_password,
    hash_session_token,
    new_csrf_token,
    new_session_token,
    session_expiry,
    verify_password,
)
from smart_pdf2md.web.settings import get_settings

router = APIRouter(tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.web_session_days * 86400,
    )


def _create_session(db: Session, user: User) -> tuple[str, str]:
    settings = get_settings()
    token = new_session_token()
    csrf = new_csrf_token()
    db.add(
        SessionRow(
            user_id=user.id,
            token_hash=hash_session_token(token),
            csrf_token=csrf,
            expires_at=session_expiry(settings.web_session_days),
        )
    )
    return token, csrf


def _auth_redirect(token: str, csrf: str) -> RedirectResponse:
    resp = RedirectResponse("/documents", status_code=303)
    _set_session_cookie(resp, token)
    set_csrf_cookie(resp, csrf)
    return resp


def _rate_limited(db: Session, email: str) -> bool:
    since = datetime.now(timezone.utc) - timedelta(minutes=15)
    failures = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.email == email.lower(),
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= since,
        )
    )
    return int(failures or 0) >= 5


def _html_or_http_error(
    request: Request,
    *,
    template: str,
    error: str,
    status_code: int,
    email: str = "",
    **extra,
):
    if wants_html(request):
        ctx = {"error": error, "email": email, **extra}
        return templates.TemplateResponse(
            request,
            template,
            ctx,
            status_code=status_code,
        )
    raise HTTPException(status_code=status_code, detail=error)


def _register_disabled_response(request: Request):
    if wants_html(request):
        return RedirectResponse("/login", status_code=303)
    raise HTTPException(status_code=403, detail="Registration is disabled")


@router.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    if not get_settings().web_allow_register:
        return _register_disabled_response(request)
    return templates.TemplateResponse(
        request, "register.html", {"error": None, "email": ""}
    )


@router.post("/register")
async def register(
    request: Request,
    db: DbSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    settings = get_settings()
    if not settings.web_allow_register:
        return _register_disabled_response(request)
    email_n = email.strip().lower()
    if not email_n or len(password) < 8:
        return _html_or_http_error(
            request,
            template="register.html",
            error="Email hoặc mật khẩu không hợp lệ",
            status_code=422,
            email=email_n,
        )
    exists = db.scalar(select(User).where(User.email == email_n))
    if exists:
        return _html_or_http_error(
            request,
            template="register.html",
            error="Email đã được đăng ký",
            status_code=422,
            email=email_n,
        )
    user = User(
        email=email_n,
        password_hash=hash_password(password),
        role="user",
        credits=0,
    )
    db.add(user)
    db.flush()
    grant_signup_credits(db, user, settings.web_default_credits)
    token, csrf = _create_session(db, user)
    db.commit()
    return _auth_redirect(token, csrf)


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
            "email": "",
            "allow_register": get_settings().web_allow_register,
        },
    )


@router.post("/login")
async def login(
    request: Request,
    db: DbSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    settings = get_settings()
    email_n = email.strip().lower()
    if _rate_limited(db, email_n):
        return _html_or_http_error(
            request,
            template="login.html",
            error="Quá nhiều lần đăng nhập sai",
            status_code=429,
            email=email_n,
            allow_register=settings.web_allow_register,
        )
    user = db.scalar(select(User).where(User.email == email_n))
    ok = bool(user and verify_password(user.password_hash, password))
    db.add(LoginAttempt(email=email_n, success=ok))
    if not ok:
        db.commit()
        return _html_or_http_error(
            request,
            template="login.html",
            error="Email hoặc mật khẩu không đúng",
            status_code=401,
            email=email_n,
            allow_register=settings.web_allow_register,
        )
    assert user is not None
    token, csrf = _create_session(db, user)
    db.commit()
    return _auth_redirect(token, csrf)


@router.post("/logout", dependencies=[Depends(require_csrf)])
async def logout(request: Request, db: DbSession, user: Annotated[User, Depends(require_user)]):
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    if token:
        row = db.scalar(
            select(SessionRow).where(SessionRow.token_hash == hash_session_token(token))
        )
        if row:
            db.delete(row)
            db.commit()
    resp = hx_redirect(request, "/login")
    resp.delete_cookie(settings.cookie_name)
    clear_csrf_cookie(resp)
    return resp
