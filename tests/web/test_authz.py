"""Cycle 9: authorization — 404 not 403 for cross-user access."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from helpers import csrf_headers, register

pytestmark = pytest.mark.db

PROTECTED = [
    ("GET", "/documents"),
    ("GET", "/api/providers"),
    ("GET", "/jobs/00000000-0000-0000-0000-000000000001"),
    ("GET", "/admin/users"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_anonymous_rejected_on_every_protected_route(client, method, path):
    resp = client.request(method, path)
    assert resp.status_code in {401, 403}


def test_user_cannot_read_other_users_document_returns_404(client):
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "WB-1.pdf"
    if not fixture.is_file():
        pytest.skip("missing WB-1.pdf")
    register(client, "owner@example.com")
    headers = csrf_headers(client)
    up = client.post(
        "/documents",
        files={"file": ("a.pdf", fixture.read_bytes(), "application/pdf")},
        headers=headers,
    )
    assert up.status_code == 200
    doc_id = up.json()["id"]

    client.cookies.clear()
    register(client, "other@example.com")
    other_headers = csrf_headers(client)
    resp = client.get(f"/documents/{doc_id}", headers=other_headers)
    assert resp.status_code == 404


def test_user_cannot_read_other_users_job(client):
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import Document, Job, User

    register(client, "a@example.com")
    factory = get_session_factory()
    with factory() as session:
        user_a = session.scalar(select(User).where(User.email == "a@example.com"))
        assert user_a is not None
        doc = Document(
            owner_id=user_a.id,
            original_filename="x.pdf",
            stored_path="/tmp/x.pdf",
            page_count=1,
            page_native_chars=[0],
            pages_needing_ocr=[1],
        )
        session.add(doc)
        session.flush()
        job = Job(owner_id=user_a.id, document_id=doc.id, status="queued")
        session.add(job)
        session.commit()
        job_id = job.id

    client.cookies.clear()
    register(client, "b@example.com")
    headers = csrf_headers(client)
    resp = client.get(f"/jobs/{job_id}", headers=headers)
    assert resp.status_code == 404


def test_admin_routes_forbidden_for_plain_user(client):
    register(client, "admin0@example.com")
    client.cookies.clear()
    register(client, "plain@example.com")
    headers = csrf_headers(client)
    resp = client.get("/admin/users", headers=headers)
    assert resp.status_code == 403


def test_admin_can_create_user_when_register_disabled(admin_client, monkeypatch):
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import CreditTransaction, User
    from smart_pdf2md.web.settings import get_settings

    monkeypatch.setenv("WEB_ALLOW_REGISTER", "false")
    get_settings.cache_clear()
    try:
        blocked = admin_client.post(
            "/register",
            data={"email": "public@example.com", "password": "password123"},
            follow_redirects=False,
        )
        assert blocked.status_code == 403

        resp = admin_client.post(
            "/admin/users",
            data={"email": "created@example.com", "password": "password123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "created@example.com"
        assert body["role"] == "user"
        assert body["credits"] == 10

        # Admin session unchanged — still can reach admin.
        admin_page = admin_client.get("/admin/users")
        assert admin_page.status_code == 200

        with get_session_factory()() as session:
            created = session.scalar(
                select(User).where(User.email == "created@example.com")
            )
            assert created is not None
            assert created.role == "user"
            assert created.credits == 10
            ledger = session.scalars(
                select(CreditTransaction).where(
                    CreditTransaction.user_id == created.id
                )
            ).all()
            assert any(r.reason == "signup_grant" and r.delta == 10 for r in ledger)

        admin_client.cookies.clear()
        login = admin_client.post(
            "/login",
            data={"email": "created@example.com", "password": "password123"},
            follow_redirects=False,
        )
        assert login.status_code == 303
    finally:
        get_settings.cache_clear()


def test_plain_user_cannot_create_user(client):
    register(client, "admin1@example.com")
    client.cookies.clear()
    register(client, "plain1@example.com")
    headers = csrf_headers(client)
    resp = client.post(
        "/admin/users",
        data={"email": "nope@example.com", "password": "password123"},
        headers=headers,
    )
    assert resp.status_code == 403
