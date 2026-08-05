"""Strip repeated running headers/footers from per-page OCR markdown."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from smart_pdf2md.models import PageResult

_MD_EMPHASIS = re.compile(r"[*_`~]+")
_DIGITS = re.compile(r"\d+")
_WS = re.compile(r"\s+")
# GFM table rule rows must not be treated as running headers.
_TABLE_RULE = re.compile(r"^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")

MIN_PAGES = 5
FREQ_THRESHOLD = 0.30
MAX_LINE_LEN = 100


@dataclass(frozen=True)
class StripResult:
    pages: list[PageResult]
    patterns: list[str]
    removed_lines: int


def normalize_line(line: str) -> str:
    text = _MD_EMPHASIS.sub("", line)
    text = _DIGITS.sub("", text)
    text = _WS.sub(" ", text).strip()
    return text.casefold()


def _is_candidate_line(raw: str) -> bool:
    stripped = raw.strip()
    if not stripped or len(stripped) > MAX_LINE_LEN:
        return False
    if _TABLE_RULE.match(stripped):
        return False
    norm = normalize_line(stripped)
    # Page-number-only → empty norm (keep). Pure punctuation → skip.
    if norm and not any(ch.isalnum() for ch in norm):
        return False
    return True


def _edge_lines(markdown: str, *, head: bool, n: int = 2) -> list[tuple[str, str]]:
    """Return up to ``n`` candidate (original, normalized) lines from head or tail."""
    lines = markdown.splitlines()
    ordered = lines if head else list(reversed(lines))
    found: list[tuple[str, str]] = []
    for raw in ordered:
        if not _is_candidate_line(raw):
            continue
        stripped = raw.strip()
        found.append((stripped, normalize_line(stripped)))
        if len(found) >= n:
            break
    return found


def strip_running_headers(pages: list[PageResult]) -> StripResult:
    """Remove lines that repeat as headers/footers across ≥30% of pages."""
    if len(pages) < MIN_PAGES:
        return StripResult(pages=pages, patterns=[], removed_lines=0)

    head_norms: list[list[str]] = []
    tail_norms: list[list[str]] = []
    for page in pages:
        md = page.markdown or ""
        head_norms.append([norm for _, norm in _edge_lines(md, head=True)])
        tail_norms.append([norm for _, norm in _edge_lines(md, head=False)])

    def _frequent(per_page: list[list[str]]) -> set[str]:
        counts: Counter[str] = Counter()
        for norms in per_page:
            for norm in set(norms):
                counts[norm] += 1
        threshold = max(1, int(len(pages) * FREQ_THRESHOLD + 0.999))
        return {norm for norm, n in counts.items() if n >= threshold}

    head_bad = _frequent(head_norms)
    tail_bad = _frequent(tail_norms)
    if not head_bad and not tail_bad:
        return StripResult(pages=pages, patterns=[], removed_lines=0)

    patterns = sorted(p for p in (head_bad | tail_bad) if p)
    if "" in head_bad or "" in tail_bad:
        patterns.append("<page-number>")
    removed = 0
    out: list[PageResult] = []

    for page in pages:
        lines = (page.markdown or "").splitlines()
        if not lines:
            out.append(page)
            continue

        drop: set[int] = set()

        def _mark(indices: list[int], bad: set[str]) -> None:
            nonlocal removed
            for idx in indices:
                if not _is_candidate_line(lines[idx]):
                    continue
                raw = lines[idx].strip()
                norm = normalize_line(raw)
                if norm in bad:
                    drop.add(idx)

        head_idxs: list[int] = []
        for i, line in enumerate(lines):
            if _is_candidate_line(line):
                head_idxs.append(i)
                if len(head_idxs) >= 2:
                    break
        tail_idxs: list[int] = []
        for i in range(len(lines) - 1, -1, -1):
            if _is_candidate_line(lines[i]):
                tail_idxs.append(i)
                if len(tail_idxs) >= 2:
                    break

        _mark(head_idxs, head_bad)
        _mark(tail_idxs, tail_bad)

        if not drop:
            out.append(page)
            continue

        removed += len(drop)
        kept = [line for i, line in enumerate(lines) if i not in drop]
        new_md = "\n".join(kept).strip()
        if (page.markdown or "").endswith("\n") and new_md:
            new_md += "\n"
        out.append(
            PageResult(
                page=page.page,
                markdown=new_md,
                needs_ocr=page.needs_ocr,
                ocr_reason=page.ocr_reason,
                source=page.source,
                ocr_error=page.ocr_error,
            )
        )

    return StripResult(pages=out, patterns=patterns, removed_lines=removed)
