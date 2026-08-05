"""Cycle 2: convert_full emits ConversionEvent via listener port."""

from __future__ import annotations

from pathlib import Path

import pytest

from smart_pdf2md.converter import convert_full
from smart_pdf2md.events import (
    AnalysisDone,
    CacheFinal,
    CacheSummary,
    Completed,
    OcrStarted,
    PageDone,
    PageStarted,
)
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr import base as ocr_base

from fakes import FakeOcrBackend, RecordingListener, make_analysis, make_extract_pages


@pytest.fixture
def scanned_two_pages(monkeypatch, tmp_path: Path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    analysis = make_analysis(
        pdf_type="scanned",
        page_count=2,
        pages_needing_ocr=[1, 2],
    )
    pages = [
        PageResult(page=0, markdown="", needs_ocr=True, ocr_reason="image", source="native"),
        PageResult(page=1, markdown="", needs_ocr=True, ocr_reason="image", source="native"),
    ]
    monkeypatch.setattr(
        "smart_pdf2md.converter.extract_pages",
        make_extract_pages(pages, analysis),
    )
    backend = FakeOcrBackend(usage=(100, 50, 0.012))
    monkeypatch.setattr(ocr_base, "get_ocr_backend", lambda name: backend)
    monkeypatch.setattr("smart_pdf2md.converter.get_ocr_backend", lambda name: backend)
    return pdf, backend


def test_emits_analysis_done_with_pdf_type_and_ocr_pages(scanned_two_pages):
    pdf, _backend = scanned_two_pages
    listener = RecordingListener()
    convert_full(pdf, show_progress=False, use_cache=False, listener=listener)
    events = listener.of_type(AnalysisDone)
    assert len(events) == 1
    assert events[0].pdf_type == "scanned"
    assert events[0].ocr_pages == [1, 2]


def test_emits_ocr_started_then_page_started_page_done_per_page(scanned_two_pages):
    pdf, _backend = scanned_two_pages
    listener = RecordingListener()
    convert_full(pdf, show_progress=False, use_cache=False, listener=listener)
    types = [type(e).__name__ for e in listener.events]
    assert "OcrStarted" in types
    assert types.index("OcrStarted") < types.index("PageStarted")
    page_starts = listener.of_type(PageStarted)
    page_dones = listener.of_type(PageDone)
    assert [e.page for e in page_starts] == [1, 2]
    assert [e.page for e in page_dones] == [1, 2]
    ocr_started = listener.of_type(OcrStarted)[0]
    assert ocr_started.total == 2
    assert ocr_started.backend == "opencode"


def test_emits_cache_summary_on_second_run(scanned_two_pages, tmp_path: Path):
    pdf, _backend = scanned_two_pages
    cache_dir = tmp_path / "cache"
    # First run populates cache
    convert_full(
        pdf,
        show_progress=False,
        use_cache=True,
        listener=RecordingListener(),
    )
    # Point cache at isolated dir via env already handled by conftest;
    # second run should hit cache for both pages.
    listener = RecordingListener()
    convert_full(pdf, show_progress=False, use_cache=True, listener=listener)
    summaries = listener.of_type(CacheSummary)
    assert summaries
    assert summaries[0].hits == 2
    assert summaries[0].misses == 0
    assert not listener.of_type(OcrStarted)
    finals = listener.of_type(CacheFinal)
    assert finals and finals[0].hits == 2


def test_emits_completed_with_tokens_and_cost(scanned_two_pages):
    pdf, _backend = scanned_two_pages
    listener = RecordingListener()
    convert_full(pdf, show_progress=False, use_cache=False, listener=listener)
    done = listener.of_type(Completed)
    assert len(done) == 1
    assert done[0].ocr_input_tokens == 100
    assert done[0].ocr_output_tokens == 50
    assert done[0].ocr_cost_usd == pytest.approx(0.012)
    assert listener.closed


def test_listener_none_and_show_progress_false_stays_silent(scanned_two_pages, capsys):
    pdf, _backend = scanned_two_pages
    convert_full(pdf, show_progress=False, use_cache=False)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_listener_provided_suppresses_rich_output(scanned_two_pages, capsys):
    pdf, _backend = scanned_two_pages
    convert_full(
        pdf,
        show_progress=True,
        use_cache=False,
        listener=RecordingListener(),
    )
    captured = capsys.readouterr()
    assert captured.out == ""
