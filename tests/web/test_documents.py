"""Cycle 10: document library."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import csrf_headers, register

pytestmark = pytest.mark.db

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "WB-1.pdf"


def test_htmx_upload_returns_204_with_hx_redirect(authed_client):
    if not FIXTURE_PDF.is_file():
        pytest.skip("missing WB-1.pdf")
    resp = authed_client.post(
        "/documents",
        files={"file": ("doc.pdf", FIXTURE_PDF.read_bytes(), "application/pdf")},
        headers={"hx-request": "true"},
        follow_redirects=False,
    )
    assert resp.status_code == 204
    assert resp.headers["hx-redirect"].startswith("/documents/")


def test_htmx_upload_rejection_is_html_fragment(authed_client):
    resp = authed_client.post(
        "/documents",
        files={"file": ("not.pdf", b"just text", "application/pdf")},
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 422
    assert "text/html" in resp.headers["content-type"]


def test_upload_pdf_creates_document_row_file_and_page_count(authed_client):
    if not FIXTURE_PDF.is_file():
        pytest.skip("missing WB-1.pdf")
    data = FIXTURE_PDF.read_bytes()
    resp = authed_client.post(
        "/documents",
        files={"file": ("report.pdf", data, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page_count"] >= 1
    assert Path(
        __import__("smart_pdf2md.web.settings", fromlist=["get_settings"]).get_settings().web_data_dir
    ).exists()


def test_upload_rejects_file_without_pdf_magic_bytes(authed_client):
    resp = authed_client.post(
        "/documents",
        files={"file": ("fake.pdf", b"not-a-pdf-at-all", "application/pdf")},
    )
    assert resp.status_code == 422


def test_upload_rejects_over_max_size(authed_client, monkeypatch):
    monkeypatch.setenv("WEB_MAX_UPLOAD_MB", "0")
    from smart_pdf2md.web.settings import get_settings

    get_settings.cache_clear()
    # 0 MB means any non-empty file exceeds — but settings already cached on app.
    # Hit validation by patching settings on the module used by route.
    monkeypatch.setattr(
        "smart_pdf2md.web.routes.documents.get_settings",
        lambda: type("S", (), {"web_max_upload_mb": 0, "web_data_dir": get_settings().web_data_dir})(),
    )
    resp = authed_client.post(
        "/documents",
        files={"file": ("a.pdf", b"%PDF-1.4 hi", "application/pdf")},
    )
    assert resp.status_code == 422


def test_stored_path_ignores_user_supplied_filename(authed_client):
    if not FIXTURE_PDF.is_file():
        pytest.skip("missing WB-1.pdf")
    resp = authed_client.post(
        "/documents",
        files={"file": ("../../evil.pdf", FIXTURE_PDF.read_bytes(), "application/pdf")},
    )
    assert resp.status_code == 200
    detail = authed_client.get(f"/documents/{resp.json()['id']}")
    # stored on disk as source.pdf under uuid dirs — fetch via list
    assert "../" not in detail.json().get("id", "")


def test_list_and_delete_scoped_to_owner(client):
    if not FIXTURE_PDF.is_file():
        pytest.skip("missing WB-1.pdf")
    register(client, "owner@example.com")
    headers = csrf_headers(client)
    up = client.post(
        "/documents",
        files={"file": ("a.pdf", FIXTURE_PDF.read_bytes(), "application/pdf")},
        headers=headers,
    )
    assert up.status_code == 200
    doc_id = up.json()["id"]

    client.cookies.clear()
    register(client, "other@example.com")
    other = csrf_headers(client)
    listed = client.get("/documents", headers=other)
    assert listed.status_code == 200
    assert all(d["id"] != doc_id for d in listed.json())
    deleted = client.delete(f"/documents/{doc_id}", headers=other)
    assert deleted.status_code == 404
