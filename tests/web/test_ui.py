"""Light HTML / CSRF UI acceptance tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from helpers import csrf_headers, register
from smart_pdf2md.web.db import get_session_factory
from smart_pdf2md.web.htmlutil import CSRF_COOKIE_NAME
from smart_pdf2md.web.models import Document, Job, JobEvent, User

pytestmark = pytest.mark.db

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "WB-1.pdf"
HTML_HEADERS = {"Accept": "text/html"}


def test_csrf_cookie_set_after_login(client):
    register(client, "csrf-ui@example.com")
    assert client.cookies.get(CSRF_COOKIE_NAME)
    headers = csrf_headers(client)
    assert headers["x-csrf-token"] == client.cookies.get(CSRF_COOKIE_NAME)


def test_documents_html_lists_filename(client):
    if not FIXTURE_PDF.is_file():
        pytest.skip("missing WB-1.pdf")
    register(client, "lib@example.com")
    headers = {**csrf_headers(client), **HTML_HEADERS}
    up = client.post(
        "/documents",
        files={"file": ("report.pdf", FIXTURE_PDF.read_bytes(), "application/pdf")},
        headers=csrf_headers(client),
    )
    assert up.status_code == 200
    page = client.get("/documents", headers=headers)
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")
    assert "report.pdf" in page.text


def test_admin_html_forbidden_for_non_admin(client):
    register(client, "admin-first@example.com")
    client.cookies.clear()
    register(client, "plain-ui@example.com")
    resp = client.get("/admin", headers={**csrf_headers(client), **HTML_HEADERS})
    assert resp.status_code == 403


def _seed_doc_and_job(session, email, **job_fields):
    user = session.scalar(select(User).where(User.email == email))
    assert user is not None
    doc = Document(
        owner_id=user.id,
        original_filename="report.pdf",
        stored_path="/tmp/report.pdf",
        page_count=3,
        pdf_type="scanned",
        page_native_chars=[0, 500, 0],
        pages_needing_ocr=[1, 3],
    )
    session.add(doc)
    session.flush()
    job = Job(owner_id=user.id, document_id=doc.id, **job_fields)
    session.add(job)
    session.commit()
    return doc.id, job.id


def test_document_html_renders_page_picker_with_ocr_markers(client):
    register(client, "picker@example.com")
    with get_session_factory()() as session:
        doc_id, _ = _seed_doc_and_job(session, "picker@example.com", status="queued")

    resp = client.get(f"/documents/{doc_id}", headers={**csrf_headers(client), **HTML_HEADERS})
    assert resp.status_code == 200
    assert 'id="page-grid"' in resp.text
    assert 'name="pages"' in resp.text
    # 3 pages, two of them thin enough to need OCR
    assert resp.text.count('class="peer sr-only page-box"') == 3
    assert resp.text.count('data-ocr="1"') == 2
    assert 'data-preset="ocr"' in resp.text


def test_library_html_renders_upload_dropzone(client):
    register(client, "drop@example.com")
    page = client.get("/documents", headers={**csrf_headers(client), **HTML_HEADERS})
    assert page.status_code == 200
    assert 'id="dropzone"' in page.text
    # The label must be wired to the input, otherwise it is not announced.
    assert 'for="pdf-file"' in page.text
    assert 'id="pdf-file"' in page.text
    assert "tối đa 50 MB" in page.text
    # Auto-upload replaces the separate Upload button outside of noscript.
    assert page.text.count(">Tải lên<") == 1


def test_library_html_shows_download_for_succeeded_job(client, tmp_path):
    register(client, "dl@example.com")
    output = tmp_path / "output.md"
    output.write_text("# hi", encoding="utf-8")
    with get_session_factory()() as session:
        _, job_id = _seed_doc_and_job(
            session,
            "dl@example.com",
            status="succeeded",
            output_path=str(output),
        )

    page = client.get("/documents", headers={**csrf_headers(client), **HTML_HEADERS})
    assert page.status_code == 200
    assert f"/jobs/{job_id}/download" in page.text


def test_library_html_links_running_job_badge(client):
    register(client, "running@example.com")
    with get_session_factory()() as session:
        _, job_id = _seed_doc_and_job(session, "running@example.com", status="running")

    page = client.get("/documents", headers={**csrf_headers(client), **HTML_HEADERS})
    assert f'/jobs/{job_id}"' in page.text
    assert "đang chạy" in page.text


def test_jobs_html_lists_only_own_jobs(client):
    register(client, "mine@example.com")
    with get_session_factory()() as session:
        _, mine = _seed_doc_and_job(session, "mine@example.com", status="succeeded")

    client.cookies.clear()
    register(client, "theirs@example.com")
    with get_session_factory()() as session:
        _, theirs = _seed_doc_and_job(session, "theirs@example.com", status="queued")

    page = client.get("/jobs", headers={**csrf_headers(client), **HTML_HEADERS})
    assert page.status_code == 200
    assert theirs in page.text
    assert mine not in page.text


def test_jobs_json_lists_only_own_jobs(client):
    register(client, "json-mine@example.com")
    with get_session_factory()() as session:
        _, mine = _seed_doc_and_job(session, "json-mine@example.com", status="queued")

    client.cookies.clear()
    register(client, "json-theirs@example.com")
    with get_session_factory()() as session:
        _, theirs = _seed_doc_and_job(session, "json-theirs@example.com", status="queued")

    body = client.get("/jobs", headers=csrf_headers(client)).json()
    ids = {row["id"] for row in body}
    assert ids == {theirs}
    assert mine not in ids


def test_running_job_html_shows_progress_and_time_remaining(client):
    """The running branch of the progress partial renders an actual estimate."""
    register(client, "eta-ui@example.com")
    with get_session_factory()() as session:
        _, job_id = _seed_doc_and_job(
            session,
            "eta-ui@example.com",
            status="running",
            backend="opencode",
            vlm_model="mimo-v2.5",
            options_json={"pages": [1, 3]},
            credits_held=2,
        )
        base = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
        for seq, (event_type, payload, offset) in enumerate(
            [
                ("OcrStarted", {"total": 3, "backend": "opencode", "model": "m"}, 0),
                ("PageStarted", {"page": 1, "index": 1}, 1),
                ("PageDone", {"page": 1, "char_count": 10}, 13),
                ("PageStarted", {"page": 2, "index": 2}, 13),
            ],
            start=1,
        ):
            session.add(
                JobEvent(
                    job_id=job_id,
                    seq=seq,
                    event_type=event_type,
                    payload=payload,
                    created_at=base + timedelta(seconds=offset),
                )
            )
        session.commit()

    resp = client.get(f"/jobs/{job_id}", headers={**csrf_headers(client), **HTML_HEADERS})
    assert resp.status_code == 200
    assert "Trang 1 / 3" in resp.text
    assert "còn" in resp.text
    assert "1,3" in resp.text  # page spec in the header
    assert f"/jobs/{job_id}/cancel" in resp.text


def test_job_html_page_200_for_owner(client):
    register(client, "job-ui@example.com")
    factory = get_session_factory()
    with factory() as session:
        user = session.scalar(select(User).where(User.email == "job-ui@example.com"))
        assert user is not None
        doc = Document(
            owner_id=user.id,
            original_filename="x.pdf",
            stored_path="/tmp/x.pdf",
            page_count=1,
            page_native_chars=[0],
            pages_needing_ocr=[1],
        )
        session.add(doc)
        session.flush()
        job = Job(owner_id=user.id, document_id=doc.id, status="queued")
        session.add(job)
        session.commit()
        job_id = job.id

    resp = client.get(f"/jobs/{job_id}", headers={**csrf_headers(client), **HTML_HEADERS})
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert job_id in resp.text
