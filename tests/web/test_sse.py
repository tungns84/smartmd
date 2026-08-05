"""Cycle 12: SSE replay and completion."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from fakes import FakeOcrBackend
from smart_pdf2md.web.db import get_session_factory
from smart_pdf2md.web.models import User

pytestmark = pytest.mark.db

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "WB-1.pdf"


@pytest.fixture
def fake_ocr(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    monkeypatch.setattr(
        "smart_pdf2md.converter.get_ocr_backend",
        lambda name: FakeOcrBackend(usage=(1, 1, 0.0)),
    )


def test_sse_streams_events_then_closes_after_completed(authed_client, fake_ocr):
    if not FIXTURE_PDF.is_file():
        pytest.skip("missing WB-1.pdf")
    with get_session_factory()() as session:
        session.scalars(select(User)).first().credits = 100
        session.commit()
    up = authed_client.post(
        "/documents",
        files={"file": ("doc.pdf", FIXTURE_PDF.read_bytes(), "application/pdf")},
    )
    job = authed_client.post(
        "/jobs",
        json={
            "document_id": up.json()["id"],
            "backend": "opencode",
            "vlm_model": "mimo-v2.5",
            "force_ocr": True,
        },
    )
    assert job.status_code == 200
    job_id = job.json()["id"]
    with authed_client.stream("GET", f"/jobs/{job_id}/events") as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())
    assert "Completed" in text or "AnalysisDone" in text


def test_sse_replays_history_from_last_event_id(authed_client, fake_ocr):
    if not FIXTURE_PDF.is_file():
        pytest.skip("missing WB-1.pdf")
    with get_session_factory()() as session:
        session.scalars(select(User)).first().credits = 100
        session.commit()
    up = authed_client.post(
        "/documents",
        files={"file": ("doc.pdf", FIXTURE_PDF.read_bytes(), "application/pdf")},
    )
    job = authed_client.post(
        "/jobs",
        json={
            "document_id": up.json()["id"],
            "backend": "opencode",
            "vlm_model": "mimo-v2.5",
            "force_ocr": True,
        },
    )
    job_id = job.json()["id"]
    # Job already finished — SSE should replay from DB
    with authed_client.stream(
        "GET", f"/jobs/{job_id}/events", headers={"Last-Event-ID": "0"}
    ) as resp:
        text = "".join(resp.iter_text())
    assert "id:" in text
