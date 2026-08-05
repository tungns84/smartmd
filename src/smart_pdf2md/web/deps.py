from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from smart_pdf2md.web.db import get_db
from smart_pdf2md.web.models import SessionRow, User
from smart_pdf2md.web.security import hash_session_token
from smart_pdf2md.web.settings import get_settings

DbSession = Annotated[Session, Depends(get_db)]


def load_session(
    db: Session, cookie_token: Optional[str]
) -> tuple[Optional[User], Optional[SessionRow]]:
    if not cookie_token:
        return None, None
    token_hash = hash_session_token(cookie_token)
    row = db.scalar(select(SessionRow).where(SessionRow.token_hash == token_hash))
    if row is None:
        return None, None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.flush()
        return None, None
    user = db.get(User, row.user_id)
    return user, row


async def current_user_optional(request: Request, db: DbSession) -> Optional[User]:
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    user, _ = load_session(db, token)
    return user


async def require_user(request: Request, db: DbSession) -> User:
    user = await current_user_optional(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="login required"
        )
    return user


async def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin only"
        )
    return user


async def require_csrf(
    request: Request,
    db: DbSession,
    x_csrf_token: Annotated[Optional[str], Header()] = None,
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    _, row = load_session(db, token)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="login required"
        )
    # Prefer explicit header (HTMX hx-headers); fall back to non-HttpOnly csrf cookie.
    provided = x_csrf_token or request.headers.get(settings.web_csrf_header)
    if not provided:
        from smart_pdf2md.web.htmlutil import CSRF_COOKIE_NAME

        provided = request.cookies.get(CSRF_COOKIE_NAME)
    if provided != row.csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed"
        )


def require_owner(resource_owner_id: str, user: User) -> None:
    if resource_owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
