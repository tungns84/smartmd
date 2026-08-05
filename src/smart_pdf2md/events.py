"""UI-agnostic conversion progress events and listener port.

Core emits events; Rich CLI, Redis/SSE, and credit guards implement listeners.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class ConversionEvent:
    """Base marker for all conversion progress events."""


@dataclass(frozen=True)
class AnalysisDone(ConversionEvent):
    pdf_type: str
    confidence: float
    total_pages: int
    ocr_pages: list[int]


@dataclass(frozen=True)
class CacheSummary(ConversionEvent):
    hits: int
    misses: int
    cached_pages: list[int]


@dataclass(frozen=True)
class OcrStarted(ConversionEvent):
    total: int
    backend: str
    model: Optional[str]


@dataclass(frozen=True)
class PageStarted(ConversionEvent):
    page: int
    index: int


@dataclass(frozen=True)
class PageDone(ConversionEvent):
    page: int
    char_count: int


@dataclass(frozen=True)
class PageRetry(ConversionEvent):
    page: int
    attempt: int
    reason: str


@dataclass(frozen=True)
class PageEmpty(ConversionEvent):
    page: int
    attempts: int


@dataclass(frozen=True)
class PageFailed(ConversionEvent):
    page: int
    reason: str


@dataclass(frozen=True)
class FallbackUsed(ConversionEvent):
    page: int
    requested_model: str
    actual_model: str


@dataclass(frozen=True)
class HeadersStripped(ConversionEvent):
    patterns: list[str]
    removed_lines: int


@dataclass(frozen=True)
class CacheFinal(ConversionEvent):
    hits: int
    misses: int


@dataclass(frozen=True)
class Completed(ConversionEvent):
    elapsed_ms: int
    cache_hits: int
    cache_misses: int
    ocr_input_tokens: int
    ocr_output_tokens: int
    ocr_cost_usd: Optional[float]


@runtime_checkable
class ConversionListener(Protocol):
    def emit(self, event: ConversionEvent) -> None: ...

    def close(self) -> None: ...


class NullListener:
    """No-op listener for quiet / headless runs."""

    def emit(self, event: ConversionEvent) -> None:
        return None

    def close(self) -> None:
        return None


class LockedListener:
    """Serialize emit/close for listeners that assume a single thread."""

    def __init__(self, inner: ConversionListener) -> None:
        self._inner = inner
        self._lock = threading.Lock()

    def emit(self, event: ConversionEvent) -> None:
        with self._lock:
            self._inner.emit(event)

    def close(self) -> None:
        with self._lock:
            self._inner.close()


class FanOutListener:
    """Forward each event to multiple listeners."""

    def __init__(self, *listeners: ConversionListener) -> None:
        self._listeners = listeners

    def emit(self, event: ConversionEvent) -> None:
        for listener in self._listeners:
            listener.emit(event)

    def close(self) -> None:
        for listener in self._listeners:
            listener.close()


def format_ocr_pages(pages: Sequence[int]) -> str:
    """Shared short display for OCR page lists (CLI + listeners)."""
    page_list = list(pages)
    if len(page_list) <= 20:
        return str(page_list)
    head = ", ".join(str(p) for p in page_list[:10])
    return f"[{head}, ... {len(page_list)} trang]"
