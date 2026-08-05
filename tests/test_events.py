"""Cycle 2: ConversionEvent + NullListener port."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass

import pytest

from smart_pdf2md.events import (
    AnalysisDone,
    CacheFinal,
    CacheSummary,
    Completed,
    FallbackUsed,
    NullListener,
    OcrStarted,
    PageDone,
    PageRetry,
    PageStarted,
)


ALL_EVENTS = [
    AnalysisDone(pdf_type="scanned", confidence=0.9, total_pages=2, ocr_pages=[1, 2]),
    CacheSummary(hits=1, misses=1, cached_pages=[1]),
    OcrStarted(total=1, backend="fake", model=None),
    PageStarted(page=1, index=1),
    PageDone(page=1, char_count=10),
    PageRetry(page=1, attempt=1, reason="429"),
    FallbackUsed(page=1, requested_model="qwen3.6-plus", actual_model="grok-4.5"),
    CacheFinal(hits=1, misses=1),
    Completed(
        elapsed_ms=100,
        cache_hits=1,
        cache_misses=1,
        ocr_input_tokens=10,
        ocr_output_tokens=20,
        ocr_cost_usd=0.01,
    ),
]


@pytest.mark.parametrize("event", ALL_EVENTS, ids=lambda e: type(e).__name__)
def test_event_dataclasses_are_frozen(event):
    assert is_dataclass(event)
    with pytest.raises(Exception):
        event.page = 99  # type: ignore[attr-defined]


@pytest.mark.parametrize("event", ALL_EVENTS, ids=lambda e: type(e).__name__)
def test_events_are_json_serializable(event):
    raw = json.dumps(asdict(event))
    assert isinstance(json.loads(raw), dict)


def test_null_listener_swallows_all_events():
    listener = NullListener()
    for event in ALL_EVENTS:
        listener.emit(event)


def test_null_listener_close_is_idempotent():
    listener = NullListener()
    listener.close()
    listener.close()
