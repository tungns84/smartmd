"""Cycle 6b: registry-driven OpenCode adapter behaviors."""

from __future__ import annotations

from typing import Any

import pytest

from smart_pdf2md.config import Options
from smart_pdf2md.errors import OcrBackendError
from smart_pdf2md.events import FallbackUsed, PageRetry
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.opencode_backend import OpencodeVlmBackend, _image_rejected
from smart_pdf2md.ocr.vlm.spec import ImageLimits

from fakes import RecordingListener


class FakeResp:
    def __init__(self, status: int, payload: dict[str, Any], text: str = "{}"):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []
        self._handler = None

    def set_handler(self, handler):
        self._handler = handler

    def post(self, url, *args, **kwargs):
        self.calls.append({"url": url, "headers": kwargs.get("headers"), "json": kwargs.get("json")})
        if self._handler:
            return self._handler(url, kwargs)
        return FakeResp(
            200,
            {"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 10, "output_tokens": 5}},
        )


def _fake_image(size=(2000, 1000)):
    from PIL import Image

    return Image.new("RGB", size, color=(255, 255, 255))


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.load_app_env",
        lambda: None,
    )
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.time.sleep",
        lambda *_: None,
    )
    b = OpencodeVlmBackend()
    session = FakeSession()
    b._session = session
    return b, session


def test_max_tokens_clamped_to_model_limit(backend, monkeypatch):
    b, session = backend
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image((32, 32))},
    )
    b.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, vlm_model="qwen3.6-plus", vlm_max_tokens=32768),
    )
    assert session.calls
    assert session.calls[0]["json"]["max_tokens"] == 8192


def test_no_vision_model_fails_fast_without_http_call(backend, monkeypatch):
    b, session = backend
    from smart_pdf2md.ocr.vlm import registry as reg
    from smart_pdf2md.ocr.vlm.spec import Capability, ModelSpec, Pricing, PricingTier

    def fake_lookup(model_id: str):
        if model_id == "text-only":
            return ModelSpec(
                id="text-only",
                label="Text",
                provider="opencode",
                enabled=True,
                capability=Capability(
                    dialect="openai_chat",
                    supports_vision=False,
                    max_output_tokens=1024,
                ),
                pricing=Pricing(tiers=(PricingTier(0, 0.1, 0.1),)),
            )
        return reg.lookup(model_id)

    monkeypatch.setattr("smart_pdf2md.ocr.opencode_backend.lookup", fake_lookup)
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image((32, 32))},
    )
    with pytest.raises(OcrBackendError, match="vision"):
        b.ocr_pages(
            [PageResult(page=0, markdown="")],
            "x.pdf",
            Options(show_progress=False, vlm_model="text-only"),
        )
    assert session.calls == []


def test_image_downscaled_per_model_limits_before_encode(backend, monkeypatch):
    import base64
    from io import BytesIO

    from PIL import Image

    b, session = backend
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image((4000, 2000))},
    )
    b.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, vlm_model="qwen3.6-plus"),
    )
    assert session.calls
    b64 = session.calls[0]["json"]["messages"][0]["content"][0]["source"]["data"]
    img = Image.open(BytesIO(base64.b64decode(b64)))
    assert max(img.size) == 2048


def test_fallback_emits_fallback_used_event(backend, monkeypatch):
    b, session = backend
    listener = RecordingListener()

    def handler(url, kwargs):
        if "/messages" in url:
            return FakeResp(400, {}, text="model does not support image content")
        return FakeResp(
            200,
            {
                "choices": [{"message": {"content": "fb"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    session.set_handler(handler)
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image((32, 32))},
    )
    b.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, vlm_model="qwen3.6-plus"),
        listener=listener,
    )
    events = [e for e in listener.events if isinstance(e, FallbackUsed)]
    assert events
    assert events[0].requested_model == "qwen3.6-plus"
    assert events[0].actual_model == "grok-4.5"


def test_fallback_priced_by_actual_model_not_requested(backend, monkeypatch):
    b, session = backend

    def handler(url, kwargs):
        if "/messages" in url:
            return FakeResp(400, {}, text="model does not support image content")
        return FakeResp(
            200,
            {
                "choices": [{"message": {"content": "fb"}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
            },
        )

    session.set_handler(handler)
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image((32, 32))},
    )
    b.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, vlm_model="qwen3.6-plus"),
    )
    _inp, _out, cost = b.consume_usage()
    assert cost == (1000 * 2.00 + 200 * 6.00) / 1_000_000


def test_fallback_disabled_raises_instead_of_switching(backend, monkeypatch):
    b, session = backend

    def handler(url, kwargs):
        return FakeResp(400, {}, text="model does not support image content")

    session.set_handler(handler)
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image((32, 32))},
    )
    with pytest.raises(OcrBackendError):
        b.ocr_pages(
            [PageResult(page=0, markdown="")],
            "x.pdf",
            Options(
                show_progress=False,
                vlm_model="qwen3.6-plus",
                allow_vlm_fallback=False,
            ),
        )
    assert all("/chat/completions" not in c["url"] for c in session.calls)


def test_disabled_fallback_model_not_used(backend, monkeypatch, tmp_path):
    """Whitelist overlay: disabled grok-4.5 must not be invoked as fallback."""
    from smart_pdf2md.ocr.vlm import registry as reg

    b, session = backend
    overlay = tmp_path / "models.toml"
    overlay.write_text(
        '[models."grok-4.5"]\nenabled = false\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2MD_MODEL_REGISTRY", str(overlay))
    reg.reload_registry()
    try:

        def handler(url, kwargs):
            return FakeResp(400, {}, text="model does not support image content")

        session.set_handler(handler)
        monkeypatch.setattr(
            "smart_pdf2md.ocr.opencode_backend.render_pages",
            lambda *a, **k: {1: _fake_image((32, 32))},
        )
        with pytest.raises(OcrBackendError):
            b.ocr_pages(
                [PageResult(page=0, markdown="")],
                "x.pdf",
                Options(show_progress=False, vlm_model="qwen3.7-plus"),
            )
        assert all("/chat/completions" not in c["url"] for c in session.calls)
    finally:
        monkeypatch.delenv("PDF2MD_MODEL_REGISTRY", raising=False)
        reg.reload_registry()


def test_unknown_model_still_works_with_provider_default_dialect(backend, monkeypatch):
    b, session = backend
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image((32, 32))},
    )
    result = b.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, vlm_model="custom-finetune-x"),
    )
    assert result[1] == "ok"
    assert "/messages" in session.calls[0]["url"]
    _inp, _out, cost = b.consume_usage()
    assert cost is None


def test_retry_emits_page_retry_event(backend, monkeypatch):
    b, session = backend
    listener = RecordingListener()
    n = {"i": 0}

    def handler(url, kwargs):
        n["i"] += 1
        if n["i"] < 3:
            return FakeResp(429, {}, text="rate limited")
        return FakeResp(
            200,
            {"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 1, "output_tokens": 1}},
        )

    session.set_handler(handler)
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image((32, 32))},
    )
    b.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, vlm_model="qwen3.6-plus"),
        listener=listener,
    )
    retries = [e for e in listener.events if isinstance(e, PageRetry)]
    assert len(retries) >= 1
    assert retries[0].page == 1


def test_image_rejected_heuristic_ignores_generic_image_word():
    assert _image_rejected(400, "bad image request format from client") is False
    assert _image_rejected(400, "model does not support image content") is True
    assert _image_rejected(400, "unsupported media type") is True
