"""Cycle 7: harness smoke test (no DB required)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from smart_pdf2md.web.app import create_app


def test_healthz_returns_ok():
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
