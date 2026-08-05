"""Cycle 11: provider selector API."""

from __future__ import annotations

import pytest

from smart_pdf2md.ocr.vlm.registry import list_models

pytestmark = pytest.mark.db


def test_api_providers_lists_every_registry_model(authed_client):
    resp = authed_client.get("/api/providers")
    assert resp.status_code == 200
    body = resp.json()
    ids = {m["id"] for m in body["models"]}
    enabled = {spec.id for spec in list_models(enabled_only=True)}
    assert ids == enabled
    for m in body["models"]:
        assert m["enabled"] is True


@pytest.mark.parametrize(
    "env_key,backend_id",
    [
        ("OPENCODE_API_KEY", "opencode"),
        ("PADDLE_FORCE_UNAVAILABLE", "paddleocr"),
    ],
)
def test_api_providers_marks_backend_unavailable_with_reason(
    authed_client, monkeypatch, env_key, backend_id
):
    if env_key == "OPENCODE_API_KEY":
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    else:
        monkeypatch.setattr(
            "smart_pdf2md.web.routes.providers._paddle_available",
            lambda: (False, "paddleocr unavailable: forced"),
        )
    resp = authed_client.get("/api/providers")
    backends = {b["id"]: b for b in resp.json()["backends"]}
    assert backends[backend_id]["available"] is False
    assert backends[backend_id]["unavailable_reason"]


def test_api_providers_never_leaks_api_key(authed_client, monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-super-secret-key")
    resp = authed_client.get("/api/providers")
    assert "sk-super-secret-key" not in resp.text
