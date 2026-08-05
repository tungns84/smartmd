"""Security hardening: DoS bounds, escaping, headers, SSE pool safety."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from smart_pdf2md.web.db import get_engine, get_session_factory
from smart_pdf2md.web.job_options import parse_page_selection, validate_job_options
from smart_pdf2md.web.models import Document, Job, User

pytestmark = pytest.mark.db

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "WB-1.pdf"


def _upload(client):
    if not FIXTURE_PDF.is_file():
        pytest.skip("missing WB-1.pdf")
    resp = client.post(
        "/documents",
        files={"file": ("doc.pdf", FIXTURE_PDF.read_bytes(), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_huge_page_range_rejected_quickly_unit():
    started = time.perf_counter()
    with pytest.raises(HTTPException) as exc:
        parse_page_selection("1-1000000000", page_count=10)
    elapsed = time.perf_counter() - started
    assert exc.value.status_code == 422
    assert elapsed < 0.5
    assert len(str(exc.value.detail)) < 200


def test_huge_page_range_rejected_on_jobs_and_cost_estimate(authed_client, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    doc_id = _upload(authed_client)
    started = time.perf_counter()
    job = authed_client.post(
        "/jobs",
        json={
            "document_id": doc_id,
            "backend": "opencode",
            "vlm_model": "mimo-v2.5",
            "pages": "1-1000000000",
        },
    )
    assert job.status_code == 422
    assert len(job.text) < 500
    assert time.perf_counter() - started < 2.0

    estimate = authed_client.get(
        f"/api/documents/{doc_id}/cost-estimate",
        params={"pages": "1-1000000000", "model": "mimo-v2.5"},
    )
    assert estimate.status_code == 200
    body = estimate.json()
    assert "error" in body
    assert len(str(body["error"])) < 200


def test_content_length_fast_rejects_oversized_upload(authed_client, monkeypatch):
    monkeypatch.setattr(
        "smart_pdf2md.web.routes.documents.get_settings",
        lambda: type(
            "S",
            (),
            {
                "web_max_upload_mb": 1,
                "web_data_dir": __import__(
                    "smart_pdf2md.web.settings", fromlist=["get_settings"]
                ).get_settings().web_data_dir,
            },
        )(),
    )
    # Claim a huge Content-Length without sending that many bytes.
    boundary = "----bound"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="big.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
        "%PDF-1.4 tiny\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    resp = authed_client.post(
        "/documents",
        content=body,
        headers={
            "content-type": f"multipart/form-data; boundary={boundary}",
            "content-length": str(50 * 1024 * 1024),
        },
    )
    assert resp.status_code == 422


def test_malformed_dpi_and_credits_return_422(authed_client, admin_client):
    with pytest.raises(HTTPException) as exc:
        validate_job_options(
            {"backend": "opencode", "vlm_model": "mimo-v2.5", "dpi": "not-an-int"}
        )
    assert exc.value.status_code == 422

    doc_id = _upload(authed_client)
    bad = authed_client.post(
        "/jobs",
        data={
            "document_id": doc_id,
            "backend": "opencode",
            "vlm_model": "mimo-v2.5",
            "dpi": "abc",
        },
        headers={"hx-request": "true", "Accept": "text/html"},
    )
    assert bad.status_code == 422

    with get_session_factory()() as session:
        target = session.scalars(select(User).where(User.role == "user")).first()
        if target is None:
            from smart_pdf2md.web.security import hash_password

            target = User(
                email="cred-target@example.com",
                password_hash=hash_password("password123"),
                role="user",
                credits=1,
            )
            session.add(target)
            session.commit()
            tid = target.id
        else:
            tid = target.id

    credits = admin_client.post(
        f"/admin/users/{tid}/credits",
        json={"credits": "nope"},
    )
    assert credits.status_code == 422


def test_html_error_fragments_escape_reflected_model(authed_client):
    doc_id = _upload(authed_client)
    payload = '<img src=x onerror=alert(1)>'
    resp = authed_client.post(
        "/jobs",
        data={
            "document_id": doc_id,
            "backend": "opencode",
            "vlm_model": payload,
        },
        headers={"hx-request": "true", "Accept": "text/html"},
    )
    assert resp.status_code == 422
    # Escaped so the browser cannot parse a tag; attribute text may still appear.
    assert "<img" not in resp.text
    assert "&lt;img" in resp.text


def test_security_headers_present_on_html(client):
    resp = client.get("/", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "content-security-policy-report-only" in {
        k.lower() for k in resp.headers.keys()
    }
    # COOKIE_SECURE=false in fixture → no HSTS
    assert "strict-transport-security" not in {k.lower() for k in resp.headers.keys()}
    assert 'integrity="sha384-' in resp.text
    assert 'crossorigin="anonymous"' in resp.text


def test_sse_does_not_hold_db_pool_while_streaming(authed_client, tmp_path, monkeypatch):
    # Keep the live loop short so TestClient does not sit on pubsub timeouts.
    monkeypatch.setenv("WEB_SSE_MAX_DURATION_SECONDS", "2")
    from smart_pdf2md.web.settings import get_settings

    get_settings.cache_clear()
    try:
        with get_session_factory()() as session:
            user = session.scalars(select(User)).first()
            assert user is not None
            doc = Document(
                owner_id=user.id,
                original_filename="x.pdf",
                stored_path=str(tmp_path / "x.pdf"),
                page_count=1,
                pdf_type="scanned",
                page_native_chars=[0],
                pages_needing_ocr=[1],
                size_bytes=10,
            )
            session.add(doc)
            session.flush()
            job = Job(
                owner_id=user.id,
                document_id=doc.id,
                status="running",
                backend="opencode",
                vlm_model="mimo-v2.5",
                options_json={},
                credits_held=0,
            )
            session.add(job)
            session.commit()
            job_id = job.id

        engine = get_engine()
        pool = engine.pool
        checked_during: list[int] = []
        ready = threading.Event()

        def _probe():
            ready.wait(timeout=5)
            for _ in range(8):
                checked_during.append(pool.checkedout())
                time.sleep(0.1)

        probe = threading.Thread(target=_probe, daemon=True)
        probe.start()
        with authed_client.stream("GET", f"/jobs/{job_id}/events") as resp:
            assert resp.status_code == 200
            ready.set()
            # Consume until the duration ceiling ends the stream.
            "".join(resp.iter_text())
        probe.join(timeout=3)
        assert checked_during, "probe did not sample pool"
        assert max(checked_during) <= 1
    finally:
        get_settings.cache_clear()


def test_sse_stream_cap_returns_429(authed_client, tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_SSE_MAX_STREAMS_PER_USER", "1")
    from smart_pdf2md.web.routes.jobs import _acquire_sse_slot, _release_sse_slot
    from smart_pdf2md.web.settings import get_settings

    get_settings.cache_clear()
    user_id = None
    try:
        with get_session_factory()() as session:
            user = session.scalars(select(User)).first()
            user_id = user.id
            doc = Document(
                owner_id=user.id,
                original_filename="x.pdf",
                stored_path=str(tmp_path / "y.pdf"),
                page_count=1,
                pdf_type="scanned",
                page_native_chars=[0],
                pages_needing_ocr=[1],
                size_bytes=10,
            )
            session.add(doc)
            session.flush()
            job = Job(
                owner_id=user.id,
                document_id=doc.id,
                status="running",
                backend="opencode",
                vlm_model="mimo-v2.5",
                options_json={},
                credits_held=0,
            )
            session.add(job)
            session.commit()
            job_id = job.id

        # Simulate an already-open stream without blocking TestClient.
        assert _acquire_sse_slot(user_id, 1)
        second = authed_client.get(f"/jobs/{job_id}/events")
        assert second.status_code == 429
    finally:
        if user_id is not None:
            _release_sse_slot(user_id)
        get_settings.cache_clear()
