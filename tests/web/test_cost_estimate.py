"""Cycle 11: cost estimate helpers."""

from __future__ import annotations

import pytest

from smart_pdf2md.web.job_options import estimate_job_cost_usd

pytestmark = pytest.mark.db


def test_cost_estimate_uses_baseline_without_history(authed_client):
    # No document — exercise pure helper for baseline
    cost = estimate_job_cost_usd(model="qwen3.6-plus", ocr_pages=2)
    assert cost is not None
    assert cost > 0


def test_cost_estimate_zero_when_no_ocr_pages():
    assert estimate_job_cost_usd(model="qwen3.6-plus", ocr_pages=0) == 0.0
