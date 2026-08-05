"""Cycle 12: job lifecycle with RQ is_async=False + FakeOcrBackend."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from fakes import FakeOcrBackend
from helpers import csrf_headers, register

pytestmark = pytest.mark.db

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "WB-1.pdf"


@pytest.fixture
def fake_ocr(monkeypatch):
    backend = FakeOcrBackend(usage=(100, 50, 0.01))
    monkeypatch.setattr(
        "smart_pdf2md.web.worker.get_ocr_backend",
        lambda name: backend,
        raising=False,
    )
    monkeypatch.setattr(
        "smart_pdf2md.converter.get_ocr_backend",
        lambda name: backend,
    )
    return backend


def _upload(client, headers):
    if not FIXTURE_PDF.is_file():
        pytest.skip("missing WB-1.pdf")
    resp = client.post(
        "/documents",
        files={"file": ("doc.pdf", FIXTURE_PDF.read_bytes(), "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_job_succeeds_writes_output_and_records_tokens_cost(authed_client, fake_ocr, monkeypatch):
    # Force OCR path: use paddle-like fake via opencode backend override already set
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    doc_id = _upload(authed_client, {})
    # Give user many credits
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import User

    with get_session_factory()() as session:
        user = session.scalars(select(User)).first()
        user.credits = 100
        session.commit()

    resp = authed_client.post(
        "/jobs",
        json={
            "document_id": doc_id,
            "backend": "opencode",
            "vlm_model": "mimo-v2.5",
            "force_ocr": True,
        },
    )
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["id"]
    detail = authed_client.get(f"/jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] in {"succeeded", "queued", "running"}
    # With is_async=False, should finish inline
    assert body["status"] == "succeeded"
    assert body["ocr_input_tokens"] == 100
    assert Path(body["output_path"]).is_file()


def test_job_failure_stores_error_message_and_status(authed_client, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")

    class Boom(FakeOcrBackend):
        def ocr_pages(self, *a, **k):
            raise RuntimeError("boom-ocr")

    monkeypatch.setattr(
        "smart_pdf2md.converter.get_ocr_backend",
        lambda name: Boom(),
    )
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import User

    with get_session_factory()() as session:
        session.scalars(select(User)).first().credits = 100
        session.commit()

    doc_id = _upload(authed_client, {})
    resp = authed_client.post(
        "/jobs",
        json={
            "document_id": doc_id,
            "backend": "opencode",
            "vlm_model": "mimo-v2.5",
            "force_ocr": True,
        },
    )
    assert resp.status_code == 200
    body = authed_client.get(f"/jobs/{resp.json()['id']}").json()
    assert body["status"] == "failed"
    assert "boom" in (body["error_message"] or "")


def test_job_events_persisted_with_increasing_seq(authed_client, fake_ocr, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import JobEvent, User

    with get_session_factory()() as session:
        session.scalars(select(User)).first().credits = 100
        session.commit()

    doc_id = _upload(authed_client, {})
    resp = authed_client.post(
        "/jobs",
        json={
            "document_id": doc_id,
            "backend": "opencode",
            "vlm_model": "mimo-v2.5",
            "force_ocr": True,
        },
    )
    job_id = resp.json()["id"]
    with get_session_factory()() as session:
        events = session.scalars(
            select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.seq)
        ).all()
    assert events
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)
    assert seqs == list(range(1, len(seqs) + 1))


def _start_job(client, doc_id, **extra):
    payload = {
        "document_id": doc_id,
        "backend": "opencode",
        "vlm_model": "mimo-v2.5",
        "force_ocr": True,
    }
    payload.update(extra)
    return client.post("/jobs", json=payload)


def test_page_selection_holds_and_converts_only_selected_pages(
    authed_client, fake_ocr, monkeypatch
):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import User

    with get_session_factory()() as session:
        session.scalars(select(User)).first().credits = 100
        session.commit()

    doc_id = _upload(authed_client, {})
    resp = _start_job(authed_client, doc_id, pages="1")
    assert resp.status_code == 200, resp.text
    assert resp.json()["credits_held"] == 1

    body = authed_client.get(f"/jobs/{resp.json()['id']}").json()
    assert body["status"] == "succeeded"
    assert fake_ocr.calls == [[1]]
    markdown = Path(body["output_path"]).read_text(encoding="utf-8")
    assert "Noi dung OCR trang 1" in markdown
    assert "Noi dung OCR trang 2" not in markdown


def test_out_of_range_page_selection_rejected_422(authed_client, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    doc_id = _upload(authed_client, {})
    resp = _start_job(authed_client, doc_id, pages="9999")
    assert resp.status_code == 422


def test_output_path_is_per_job(authed_client, fake_ocr, monkeypatch):
    """Two jobs on one document must not overwrite each other's markdown."""
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import User

    with get_session_factory()() as session:
        session.scalars(select(User)).first().credits = 100
        session.commit()

    doc_id = _upload(authed_client, {})
    first = _start_job(authed_client, doc_id, pages="1").json()["id"]
    second = _start_job(authed_client, doc_id, pages="1").json()["id"]

    first_path = authed_client.get(f"/jobs/{first}").json()["output_path"]
    second_path = authed_client.get(f"/jobs/{second}").json()["output_path"]
    assert first_path != second_path
    assert Path(first_path).is_file() and Path(second_path).is_file()


def test_download_names_file_after_source_pdf(authed_client, fake_ocr, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import User

    with get_session_factory()() as session:
        session.scalars(select(User)).first().credits = 100
        session.commit()

    doc_id = _upload(authed_client, {})
    job_id = _start_job(authed_client, doc_id, pages="1").json()["id"]
    resp = authed_client.get(f"/jobs/{job_id}/download")
    assert resp.status_code == 200
    assert "doc.md" in resp.headers["content-disposition"]


def test_cancel_queued_job_refunds_hold(authed_client, monkeypatch, redis_conn):
    """Nothing else settles a job the worker never picked up."""
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    # Keep the job in "queued": the sync test queue would otherwise run it inline.
    monkeypatch.setattr(
        "smart_pdf2md.web.routes.jobs.run_conversion_job",
        lambda job_id: None,
    )
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import Job, User

    doc_id = _upload(authed_client, {})
    with get_session_factory()() as session:
        before = session.scalars(select(User)).first().credits

    resp = _start_job(authed_client, doc_id, pages="1")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["id"]
    hold = resp.json()["credits_held"]
    assert hold == 1

    with get_session_factory()() as session:
        assert session.scalars(select(User)).first().credits == before - hold
        assert session.get(Job, job_id).status == "queued"

    cancel = authed_client.post(f"/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    assert redis_conn.get(f"job:{job_id}:cancel") in {b"1", "1"}

    with get_session_factory()() as session:
        job = session.get(Job, job_id)
        assert job.status == "cancelled"
        assert job.settled_at is not None
        assert session.scalars(select(User)).first().credits == before


def test_htmx_start_returns_204_with_hx_redirect(authed_client, fake_ocr, monkeypatch):
    """htmx follows a 303 transparently, so the header must ride a bodyless 204."""
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import User

    with get_session_factory()() as session:
        session.scalars(select(User)).first().credits = 100
        session.commit()

    doc_id = _upload(authed_client, {})
    resp = authed_client.post(
        "/jobs",
        json={
            "document_id": doc_id,
            "backend": "opencode",
            "vlm_model": "mimo-v2.5",
            "force_ocr": True,
            "pages": "1",
        },
        headers={"hx-request": "true"},
        follow_redirects=False,
    )
    assert resp.status_code == 204
    assert resp.headers["hx-redirect"].startswith("/jobs/")


def test_htmx_job_error_returns_html_fragment(authed_client, monkeypatch):
    """422 must be HTML for htmx, otherwise raw JSON lands in the page."""
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    doc_id = _upload(authed_client, {})
    resp = authed_client.post(
        "/jobs",
        json={
            "document_id": doc_id,
            "backend": "opencode",
            "vlm_model": "mimo-v2.5",
            "force_ocr": True,
            "pages": "4242",
        },
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 422
    assert "text/html" in resp.headers["content-type"]
    assert "detail" not in resp.text


def test_cancel_finished_job_is_noop(authed_client, fake_ocr, monkeypatch, redis_conn):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import User

    with get_session_factory()() as session:
        session.scalars(select(User)).first().credits = 100
        session.commit()

    doc_id = _upload(authed_client, {})
    job_id = _start_job(authed_client, doc_id, pages="1").json()["id"]

    cancel = authed_client.post(f"/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "succeeded"
    assert redis_conn.get(f"job:{job_id}:cancel") is None
