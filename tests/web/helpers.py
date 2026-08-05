from __future__ import annotations

from sqlalchemy import select


def register(client, email: str, password: str = "password123"):
    return client.post(
        "/register",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def csrf_headers(client) -> dict[str, str]:
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.htmlutil import CSRF_COOKIE_NAME
    from smart_pdf2md.web.models import SessionRow
    from smart_pdf2md.web.security import hash_session_token
    from smart_pdf2md.web.settings import get_settings

    cookie_csrf = client.cookies.get(CSRF_COOKIE_NAME)
    if cookie_csrf:
        return {"x-csrf-token": cookie_csrf}

    settings = get_settings()
    token = client.cookies.get(settings.cookie_name)
    assert token
    factory = get_session_factory()
    with factory() as session:
        row = session.scalar(
            select(SessionRow).where(SessionRow.token_hash == hash_session_token(token))
        )
        assert row is not None
        return {"x-csrf-token": row.csrf_token}
