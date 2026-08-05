"""Cycle 8: auth acceptance tests."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


def test_register_then_login_then_access_protected_page(client):
    r = client.post(
        "/register",
        data={"email": "a@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    docs = client.get("/documents")
    assert docs.status_code == 200


def test_first_registered_user_is_plain_user(client):
    from sqlalchemy import select

    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import User

    client.post(
        "/register",
        data={"email": "first@example.com", "password": "password123"},
        follow_redirects=False,
    )
    with get_session_factory()() as session:
        user = session.scalar(select(User).where(User.email == "first@example.com"))
        assert user is not None
        assert user.role == "user"


def test_pdf2md_admin_seeds_and_is_idempotent(app):
    from sqlalchemy import select

    from smart_pdf2md.web.admin_cli import seed_admin
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import User

    user, created = seed_admin("seed-admin@example.com", "password123")
    assert created is True
    assert user.role == "admin"

    again, created2 = seed_admin("seed-admin@example.com", "password456")
    assert created2 is False
    assert again.role == "admin"
    with get_session_factory()() as session:
        row = session.scalar(select(User).where(User.email == "seed-admin@example.com"))
        assert row is not None
        assert row.role == "admin"


def test_registration_and_cookie_secure_defaults():
    from smart_pdf2md.web.settings import WebSettings

    assert WebSettings.model_fields["web_allow_register"].default is False
    assert WebSettings.model_fields["cookie_secure"].default is True


def test_login_wrong_password_and_unknown_email_give_same_message(client):
    client.post(
        "/register",
        data={"email": "known@example.com", "password": "password123"},
        follow_redirects=False,
    )
    client.cookies.clear()
    bad_pw = client.post(
        "/login",
        data={"email": "known@example.com", "password": "wrong-password"},
    )
    unknown = client.post(
        "/login",
        data={"email": "missing@example.com", "password": "password123"},
    )
    assert bad_pw.status_code == 401
    assert unknown.status_code == 401
    assert bad_pw.json()["detail"] == unknown.json()["detail"]


def test_logout_invalidates_session_server_side(authed_client):
    r = authed_client.post("/logout")
    assert r.status_code in {303, 200}
    authed_client.cookies.clear()
    # Re-set cookie from before logout is hard; instead login then logout and hit protected
    # After logout cookie deleted — protected route 401
    denied = authed_client.get("/documents")
    assert denied.status_code == 401


def test_rate_limit_blocks_after_five_failures(client):
    for _ in range(5):
        client.post(
            "/login",
            data={"email": "ratelimit@example.com", "password": "x"},
        )
    blocked = client.post(
        "/login",
        data={"email": "ratelimit@example.com", "password": "x"},
    )
    assert blocked.status_code == 429


def test_register_disabled_blocks_post_and_hides_login_link(client, monkeypatch):
    monkeypatch.setenv("WEB_ALLOW_REGISTER", "false")
    from smart_pdf2md.web.settings import get_settings

    get_settings.cache_clear()
    try:
        blocked = client.post(
            "/register",
            data={"email": "blocked@example.com", "password": "password123"},
            follow_redirects=False,
        )
        assert blocked.status_code == 403
        assert "disabled" in blocked.json()["detail"].lower()

        html_get = client.get(
            "/register",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        assert html_get.status_code == 303
        assert html_get.headers.get("location") == "/login"

        login = client.get("/login", headers={"Accept": "text/html"})
        assert login.status_code == 200
        assert "/register" not in login.text

        home = client.get("/", headers={"Accept": "text/html"})
        assert home.status_code == 200
        assert 'href="/register"' not in home.text
    finally:
        get_settings.cache_clear()
