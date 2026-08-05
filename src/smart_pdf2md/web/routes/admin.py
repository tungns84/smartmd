from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from smart_pdf2md.web.credits import admin_set_credits, grant_signup_credits
from smart_pdf2md.web.deps import DbSession, require_admin, require_csrf
from smart_pdf2md.web.htmlutil import html_error, hx_redirect, shell_context, templates, wants_html
from smart_pdf2md.web.job_options import _coerce_int
from smart_pdf2md.web.models import CreditTransaction, User
from smart_pdf2md.web.security import hash_password
from smart_pdf2md.web.settings import get_settings

router = APIRouter(prefix="/admin", tags=["admin"])


def _create_user_error(request: Request, message: str):
    if wants_html(request):
        return html_error(message, 422)
    raise HTTPException(status_code=422, detail=message)


def _users_payload(db, users: list[User]) -> list[dict[str, Any]]:
    result = []
    for u in users:
        ledger = db.scalars(
            select(CreditTransaction)
            .where(CreditTransaction.user_id == u.id)
            .order_by(CreditTransaction.created_at.desc())
            .limit(5)
        ).all()
        result.append(
            {
                "id": u.id,
                "email": u.email,
                "role": u.role,
                "credits": u.credits,
                "recent_ledger": [
                    {
                        "delta": t.delta,
                        "reason": t.reason,
                        "balance_after": t.balance_after,
                    }
                    for t in ledger
                ],
            }
        )
    return result


@router.get("", response_class=HTMLResponse)
async def admin_home(
    request: Request,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
):
    """HTML admin dashboard. JSON clients should use GET /admin/users."""
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        shell_context(request, db, admin, users=users),
    )


@router.get("/users")
async def list_users(
    request: Request,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
):
    users = db.scalars(select(User).order_by(User.created_at)).all()
    if wants_html(request):
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            shell_context(request, db, admin, users=users),
        )
    return _users_payload(db, list(users))


@router.post("/users", dependencies=[Depends(require_csrf)])
async def create_user(
    request: Request,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
):
    """Create a plain user with default credits. Does not change admin session."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        if not isinstance(payload, dict):
            return _create_user_error(request, "Email hoặc mật khẩu không hợp lệ")
        email = str(payload.get("email", ""))
        password = str(payload.get("password", ""))
    else:
        form = await request.form()
        email = str(form.get("email", ""))
        password = str(form.get("password", ""))

    email_n = email.strip().lower()
    if not email_n or len(password) < 8:
        return _create_user_error(request, "Email hoặc mật khẩu không hợp lệ")

    exists = db.scalar(select(User).where(User.email == email_n))
    if exists:
        return _create_user_error(request, "Email đã được đăng ký")

    settings = get_settings()
    user = User(
        email=email_n,
        password_hash=hash_password(password),
        role="user",
        credits=0,
    )
    db.add(user)
    db.flush()
    grant_signup_credits(db, user, settings.web_default_credits)
    db.commit()

    if wants_html(request):
        return hx_redirect(request, "/admin")
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "credits": user.credits,
    }


@router.post("/users/{user_id}/credits", dependencies=[Depends(require_csrf)])
async def set_user_credits(
    user_id: str,
    request: Request,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        if not isinstance(payload, dict) or "credits" not in payload:
            raise HTTPException(status_code=422, detail="credits required")
        credits_val = _coerce_int(
            payload["credits"], 0, "credits", lo=0, hi=1_000_000
        )
    else:
        form = await request.form()
        if "credits" not in form:
            raise HTTPException(status_code=422, detail="credits required")
        credits_val = _coerce_int(
            form["credits"], 0, "credits", lo=0, hi=1_000_000
        )

    try:
        user = admin_set_credits(db, user_id, credits_val, admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    db.commit()

    if wants_html(request):
        return templates.TemplateResponse(
            request,
            "partials/admin_user_row.html",
            shell_context(request, db, admin, u=user),
        )
    return {"id": user.id, "credits": user.credits}
