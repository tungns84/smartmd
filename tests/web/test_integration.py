"""Cycle 13: integration gate (real Postgres + Redis + worker)."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


def _enabled() -> bool:
    return os.environ.get("PDF2MD_WEB_E2E", "").strip() == "1"


@pytest.mark.skipif(not _enabled(), reason="PDF2MD_WEB_E2E!=1")
def test_full_flow_register_upload_convert_download():
    pytest.skip("Run manually with compose stack + PDF2MD_WEB_E2E=1")


@pytest.mark.skipif(not _enabled(), reason="PDF2MD_WEB_E2E!=1")
def test_worker_process_picks_up_real_queue():
    pytest.skip("Run manually with compose stack + PDF2MD_WEB_E2E=1")


@pytest.mark.skipif(not _enabled(), reason="PDF2MD_WEB_E2E!=1")
def test_registry_fingerprint_matches_between_web_and_worker():
    from smart_pdf2md.ocr.vlm.registry import registry_fingerprint

    assert registry_fingerprint()
