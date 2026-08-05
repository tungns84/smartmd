"""Post-conversion OCR quality report: pure detectors + event collector."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Optional, Sequence

from smart_pdf2md.events import (
    ConversionEvent,
    PageEmpty,
    PageFailed,
)
from smart_pdf2md.models import ConversionResult, PageResult

_CODEISH = re.compile(
    r"^(?:"
    r"def\s+\w+|class\s+\w+|import\s+\w+|from\s+\w+\s+import|"
    r"if\s+__name__|console\.log|function\s+\w+|const\s+\w+|let\s+\w+|"
    r"public\s+(?:static\s+)?(?:void|class)|#include\s*<"
    r")"
)


@dataclass
class QualityIssue:
    page: int
    kind: str
    detail: str


@dataclass
class QualityReport:
    issues: list[QualityIssue] = field(default_factory=list)
    empty_pages: list[int] = field(default_factory=list)
    failed_pages: list[int] = field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_count": self.issue_count,
            "empty_pages": self.empty_pages,
            "failed_pages": self.failed_pages,
            "issues": [asdict(i) for i in self.issues],
        }


class ReportCollector:
    """ConversionListener that records empty/failed page events for the report."""

    def __init__(self) -> None:
        self.empty: dict[int, int] = {}
        self.failed: dict[int, str] = {}
        self._closed = False

    def emit(self, event: ConversionEvent) -> None:
        if isinstance(event, PageEmpty):
            self.empty[event.page] = event.attempts
        elif isinstance(event, PageFailed):
            self.failed[event.page] = event.reason

    def close(self) -> None:
        self._closed = True


def detect_empty(page: PageResult) -> Optional[QualityIssue]:
    if (page.markdown or "").strip():
        return None
    if page.source in {"ocr", "empty", "cache"} or page.needs_ocr or page.ocr_error:
        return QualityIssue(
            page=page.page + 1,
            kind="empty",
            detail=page.ocr_error or "OCR output rỗng",
        )
    return None


def detect_short_vs_native(
    page: PageResult,
    native_chars: int,
    *,
    ratio: float = 0.5,
) -> Optional[QualityIssue]:
    if page.source not in {"ocr", "empty", "cache"}:
        return None
    ocr_chars = len((page.markdown or "").strip())
    if native_chars <= 0 or ocr_chars >= native_chars * ratio:
        return None
    return QualityIssue(
        page=page.page + 1,
        kind="short_vs_native",
        detail=f"OCR {ocr_chars} chars < {ratio:.0%} of native {native_chars}",
    )


def detect_short_vs_neighbors(
    pages: Sequence[PageResult],
    index: int,
    *,
    window: int = 2,
    ratio: float = 0.3,
) -> Optional[QualityIssue]:
    page = pages[index]
    if page.source not in {"ocr", "empty", "cache"}:
        return None
    lengths = [
        len((p.markdown or "").strip())
        for i, p in enumerate(pages)
        if i != index and abs(i - index) <= window
    ]
    if not lengths:
        return None
    mid = median(lengths)
    ocr_chars = len((page.markdown or "").strip())
    if mid <= 0 or ocr_chars >= mid * ratio:
        return None
    return QualityIssue(
        page=page.page + 1,
        kind="short_vs_neighbors",
        detail=f"OCR {ocr_chars} chars < {ratio:.0%} of neighbor median {mid:.0f}",
    )


_TABLE_SEP = re.compile(r"^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")


def detect_table_sparse(
    page: PageResult,
    *,
    empty_cell_ratio: float = 0.5,
) -> Optional[QualityIssue]:
    md = page.markdown or ""
    rows = [
        line
        for line in md.splitlines()
        if line.strip().startswith("|") and not _TABLE_SEP.match(line.strip())
    ]
    if len(rows) < 3:
        return None
    cells = 0
    empty = 0
    for row in rows:
        parts = [c.strip() for c in row.strip().strip("|").split("|")]
        for cell in parts:
            cells += 1
            if not cell:
                empty += 1
    if cells == 0 or empty / cells < empty_cell_ratio:
        return None
    return QualityIssue(
        page=page.page + 1,
        kind="table_sparse",
        detail=f"{empty}/{cells} table cells empty ({empty / cells:.0%})",
    )


def detect_codeish_unfenced(page: PageResult) -> Optional[QualityIssue]:
    md = page.markdown or ""
    in_fence = False
    hits = 0
    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _CODEISH.match(stripped):
            hits += 1
    if hits < 2:
        return None
    return QualityIssue(
        page=page.page + 1,
        kind="codeish_unfenced",
        detail=f"{hits} code-like lines outside fences",
    )


def build_report(
    result: ConversionResult,
    collector: Optional[ReportCollector] = None,
    *,
    native_chars: Optional[Sequence[int]] = None,
) -> QualityReport:
    issues: list[QualityIssue] = []
    empty_pages = list(result.empty_pages)
    failed_pages = sorted(
        {p.page + 1 for p in result.pages if p.ocr_error}
        | (set(collector.failed) if collector else set())
    )
    if collector:
        for page in collector.empty:
            if page not in empty_pages:
                empty_pages.append(page)
    empty_pages = sorted(set(empty_pages))

    for idx, page in enumerate(result.pages):
        for detector in (
            lambda p=page: detect_empty(p),
            lambda p=page, i=idx: (
                detect_short_vs_native(p, native_chars[i])
                if native_chars is not None and i < len(native_chars)
                else None
            ),
            lambda i=idx: detect_short_vs_neighbors(result.pages, i),
            lambda p=page: detect_table_sparse(p),
            lambda p=page: detect_codeish_unfenced(p),
        ):
            issue = detector()
            if issue is not None:
                issues.append(issue)

    return QualityReport(
        issues=issues,
        empty_pages=empty_pages,
        failed_pages=failed_pages,
    )


def write_report(path: str | Path, report: QualityReport) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
