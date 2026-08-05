"""ETA math (pure) plus the eta fields exposed on the job JSON."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from smart_pdf2md.web.eta import (
    MAX_SECONDS_PER_PAGE,
    ema,
    format_duration,
    page_durations,
)
from smart_pdf2md.web.models import JobEvent

BASE = datetime(2026, 8, 5, 10, 0, 0, tzinfo=timezone.utc)


def _event(seq: int, event_type: str, payload: dict, offset_s: float) -> JobEvent:
    return JobEvent(
        job_id="job-1",
        seq=seq,
        event_type=event_type,
        payload=payload,
        created_at=BASE + timedelta(seconds=offset_s),
    )


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (None, "unknown"),
        (0, "0s"),
        (45, "45s"),
        (59.6, "1m 00s"),
        (60, "1m 00s"),
        (125, "2m 05s"),
        (3600, "1h 00m"),
        (3725, "1h 02m"),
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_ema_returns_seed_without_samples():
    assert ema([], seed=20.0) == 20.0


def test_ema_weights_recent_pages():
    # 0.3 * 10 + 0.7 * 20
    assert ema([10.0], seed=20.0) == pytest.approx(17.0)


def test_ema_clamped_to_sane_range():
    assert ema([10_000.0], seed=20.0) == MAX_SECONDS_PER_PAGE


def test_page_durations_pairs_start_and_done_per_page():
    events = [
        _event(1, "OcrStarted", {"total": 2}, 0),
        _event(2, "PageStarted", {"page": 1}, 0),
        _event(3, "PageDone", {"page": 1}, 12),
        _event(4, "PageStarted", {"page": 2}, 12),
        _event(5, "PageDone", {"page": 2}, 20),
    ]
    assert page_durations(events) == [12.0, 8.0]


def test_page_durations_ignores_unpaired_and_pageless_events():
    events = [
        _event(1, "CacheSummary", {"hits": 3}, 0),
        _event(2, "PageDone", {"page": 7}, 5),
        _event(3, "PageStarted", {"page": 8}, 6),
    ]
    assert page_durations(events) == []


def test_job_eta_uses_throughput_with_interleaved_pages(monkeypatch):
    """Parallel OCR: overlapping PageStarted/PageDone must not inflate ETA."""
    from smart_pdf2md.web import eta as eta_mod
    from smart_pdf2md.web.eta import job_eta
    from smart_pdf2md.web.models import Job

    monkeypatch.setattr(
        eta_mod,
        "seconds_per_page_prior",
        lambda *a, **k: (30.0, "default estimate"),
    )
    monkeypatch.setattr(
        eta_mod,
        "datetime",
        type(
            "D",
            (),
            {
                "now": staticmethod(lambda tz=None: BASE + timedelta(seconds=20)),
                "timezone": timezone,
            },
        ),
    )

    class _DB:
        def scalars(self, _query):
            return type(
                "R",
                (),
                {
                    "all": lambda self: [
                        _event(1, "OcrStarted", {"total": 4}, 0),
                        _event(2, "PageStarted", {"page": 1}, 0),
                        _event(3, "PageStarted", {"page": 2}, 0.5),
                        _event(4, "PageDone", {"page": 1}, 10),
                        _event(5, "PageDone", {"page": 2}, 12),
                        _event(6, "PageStarted", {"page": 3}, 12),
                        _event(7, "PageStarted", {"page": 4}, 12.5),
                    ]
                },
            )()

    job = Job(
        id="j1",
        owner_id="u1",
        document_id="d1",
        status="running",
        backend="opencode",
        vlm_model="qwen3.6-plus",
    )
    result = job_eta(_DB(), job)
    assert result.pages_done == 2
    assert result.eta_seconds is not None
    # Throughput ≈ 2/20s → remaining 2 → ~20s, not 2*30=60 from prior.
    assert result.eta_seconds < 40
    assert "throughput" in result.basis


@pytest.mark.db
def test_job_json_exposes_eta_fields(authed_client, monkeypatch, tmp_path):
    """A finished job reports real elapsed time and no remaining estimate."""
    from pathlib import Path

    from sqlalchemy import select

    from fakes import FakeOcrBackend
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import User

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "input" / "WB-1.pdf"
    if not fixture.is_file():
        pytest.skip("missing WB-1.pdf")

    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    monkeypatch.setattr(
        "smart_pdf2md.converter.get_ocr_backend", lambda name: FakeOcrBackend()
    )
    with get_session_factory()() as session:
        session.scalars(select(User)).first().credits = 100
        session.commit()

    doc_id = authed_client.post(
        "/documents",
        files={"file": ("doc.pdf", fixture.read_bytes(), "application/pdf")},
    ).json()["id"]
    job_id = authed_client.post(
        "/jobs",
        json={
            "document_id": doc_id,
            "backend": "opencode",
            "vlm_model": "mimo-v2.5",
            "force_ocr": True,
            "pages": "1",
        },
    ).json()["id"]

    body = authed_client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "succeeded"
    assert body["pages_total"] == 1
    assert body["pages_done"] == 1
    assert body["progress_pct"] == 100
    assert body["eta_seconds"] is None
    assert body["seconds_per_page"] > 0
    assert body["eta_basis"]
