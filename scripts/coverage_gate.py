#!/usr/bin/env python3
"""Ratchet coverage floors for silent-failure modules.

Reads coverage.json (from pytest --cov --cov-report=json) and compares
per-module branch coverage against coverage-floors.json.

Usage:
  uv run pytest --cov=smart_pdf2md --cov-report=json -q
  uv run python scripts/coverage_gate.py
  uv run python scripts/coverage_gate.py --update   # raise floors to current
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOORS_PATH = ROOT / "coverage-floors.json"
COVERAGE_PATH = ROOT / "coverage.json"

# Modules where silent failure is costly (wrong money, wrong cache, missing OCR).
GATED_MODULES = [
    "smart_pdf2md/ocr/opencode_pricing.py",
    "smart_pdf2md/ocr/opencode_backend.py",
    "smart_pdf2md/cache.py",
    "smart_pdf2md/converter.py",
    "smart_pdf2md/headers.py",
    "smart_pdf2md/merge.py",
    "smart_pdf2md/quality.py",
    "smart_pdf2md/env.py",
    "smart_pdf2md/ocr/vlm/registry.py",
    "smart_pdf2md/ocr/vlm/overlay.py",
    "smart_pdf2md/ocr/vlm/dialects/anthropic.py",
    "smart_pdf2md/ocr/vlm/dialects/openai.py",
    "smart_pdf2md/ocr/vlm/images.py",
    "smart_pdf2md/web/security.py",
    "smart_pdf2md/web/deps.py",
    "smart_pdf2md/web/credits.py",
    "smart_pdf2md/web/job_options.py",
]


def _normalize_key(path: str) -> str:
    """Map coverage.json file keys to gated module relative paths."""
    p = path.replace("\\", "/")
    marker = "smart_pdf2md/"
    idx = p.find(marker)
    if idx >= 0:
        return p[idx:]
    return p


def _file_stats(file_data: dict) -> tuple[float, float]:
    """Return (line_pct, branch_pct) for one coverage.py file entry."""
    summary = file_data.get("summary", {})
    statements = summary.get("num_statements", 0) or 0
    missing = summary.get("missing_lines", 0) or 0
    covered = statements - missing
    line_pct = (100.0 * covered / statements) if statements else 100.0

    branches = summary.get("num_branches", 0) or 0
    missing_branches = summary.get("missing_branches", 0) or 0
    covered_branches = branches - missing_branches
    branch_pct = (100.0 * covered_branches / branches) if branches else 100.0
    return round(line_pct, 2), round(branch_pct, 2)


def load_current() -> dict[str, dict[str, float]]:
    if not COVERAGE_PATH.is_file():
        print(f"Missing {COVERAGE_PATH.name}. Run: uv run pytest --cov=smart_pdf2md --cov-report=json", file=sys.stderr)
        sys.exit(2)
    data = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
    files = data.get("files", {})
    current: dict[str, dict[str, float]] = {}
    by_norm: dict[str, dict] = {}
    for path, file_data in files.items():
        by_norm[_normalize_key(path)] = file_data

    for mod in GATED_MODULES:
        file_data = by_norm.get(mod)
        if file_data is None:
            # Module may not exist yet (vlm/* added later); skip until present.
            continue
        line_pct, branch_pct = _file_stats(file_data)
        current[mod] = {"line": line_pct, "branch": branch_pct}
    return current


def load_floors() -> dict[str, dict[str, float]]:
    if not FLOORS_PATH.is_file():
        return {}
    return json.loads(FLOORS_PATH.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce coverage floors (ratchet).")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Raise floors to current measured coverage (never lower).",
    )
    args = parser.parse_args()

    current = load_current()
    floors = load_floors()

    if args.update:
        updated = dict(floors)
        for mod, stats in current.items():
            prev = updated.get(mod, {"line": 0.0, "branch": 0.0})
            updated[mod] = {
                "line": max(float(prev.get("line", 0)), stats["line"]),
                "branch": max(float(prev.get("branch", 0)), stats["branch"]),
            }
        # Preserve any future gated modules already in floors that aren't measured yet.
        FLOORS_PATH.write_text(
            json.dumps(updated, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Updated {FLOORS_PATH.name} ({len(updated)} modules)")
        for mod, stats in sorted(updated.items()):
            print(f"  {mod}: line={stats['line']} branch={stats['branch']}")
        return 0

    if not floors:
        print(
            f"Missing {FLOORS_PATH.name}. Capture baseline with:\n"
            "  uv run pytest --cov=smart_pdf2md --cov-report=json -q\n"
            "  uv run python scripts/coverage_gate.py --update",
            file=sys.stderr,
        )
        return 2

    failures: list[str] = []
    for mod, floor in sorted(floors.items()):
        if mod not in current:
            # Floor exists but module absent from this run — treat as fail if file should exist.
            if (ROOT / "src" / mod).is_file() or (ROOT / "src" / mod.replace("smart_pdf2md/", "smart_pdf2md/")).is_file():
                failures.append(f"{mod}: not in coverage.json (expected gated module)")
            continue
        stats = current[mod]
        for metric in ("line", "branch"):
            got = stats[metric]
            need = float(floor.get(metric, 0))
            if got + 1e-9 < need:
                failures.append(
                    f"{mod}: {metric} {got}% < floor {need}% (drop {need - got:.2f})"
                )

    if failures:
        print("Coverage gate FAILED:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1

    print("Coverage gate OK:")
    for mod in sorted(floors):
        if mod in current:
            s = current[mod]
            f = floors[mod]
            print(
                f"  {mod}: line={s['line']} (floor {f.get('line')}) "
                f"branch={s['branch']} (floor {f.get('branch')})"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
