"""CSRF enforcement on state-changing requests.

The header is the primary channel (HTMX hx-headers); the non-HttpOnly cookie is
a fallback for plain form posts.
"""

from __future__ import annotations

import pytest

from helpers import csrf_headers, register
from smart_pdf2md.web.htmlutil import CSRF_COOKIE_NAME

pytestmark = pytest.mark.db


def test_cookie_accepted_when_header_absent(client):
    register(client, "cookie-csrf@example.com")
    assert client.cookies.get(CSRF_COOKIE_NAME)
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code in {200, 204, 303}


def test_header_accepted(client):
    register(client, "header-csrf@example.com")
    headers = csrf_headers(client)
    del client.cookies[CSRF_COOKIE_NAME]
    resp = client.post("/logout", headers=headers, follow_redirects=False)
    assert resp.status_code in {200, 204, 303}


def test_missing_token_rejected_403(client):
    register(client, "no-token@example.com")
    del client.cookies[CSRF_COOKIE_NAME]
    resp = client.post("/logout")
    assert resp.status_code == 403


def test_wrong_token_rejected_403(client):
    register(client, "bad-token@example.com")
    resp = client.post("/logout", headers={"x-csrf-token": "not-the-token"})
    assert resp.status_code == 403


def test_without_session_rejected_401(client):
    resp = client.post("/logout", headers={"x-csrf-token": "anything"})
    assert resp.status_code == 401
