"""Targeted empty-page retry: max_tokens bump then fallback model."""

from smart_pdf2md.config import Options
from smart_pdf2md.events import FallbackUsed, PageEmpty, PageRetry
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.opencode_backend import OpencodeVlmBackend


def _fake_image():
    from PIL import Image

    return Image.new("RGB", (16, 16), color=(255, 255, 255))


class _Listener:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def close(self):
        return None


def test_empty_max_tokens_retries_with_higher_budget(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    calls = {"n": 0}

    class FakeResp:
        def __init__(self, payload):
            self.status_code = 200
            self.text = "{}"
            self._payload = payload

        def json(self):
            return self._payload

    class FakeSession:
        def post(self, *args, **kwargs):
            calls["n"] += 1
            body = kwargs.get("json") or {}
            max_tokens = body.get("max_tokens", 0)
            if calls["n"] == 1:
                return FakeResp(
                    {
                        "content": [{"type": "text", "text": ""}],
                        "stop_reason": "max_tokens",
                        "usage": {"input_tokens": 10, "output_tokens": 10},
                    }
                )
            assert max_tokens > 8192 or max_tokens >= 8192
            return FakeResp(
                {
                    "content": [{"type": "text", "text": "Recovered page"}],
                    "stop_reason": "end_turn",
                }
            )

    backend = OpencodeVlmBackend()
    backend._session = FakeSession()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image()},
    )
    listener = _Listener()
    # Spec max_output_tokens for qwen is high enough to bump.
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.lookup",
        lambda model: None,
    )
    # Override default spec max via monkeypatch on _default_spec capability
    from smart_pdf2md.ocr import opencode_backend as mod
    from smart_pdf2md.ocr.vlm.spec import Capability, ImageLimits, ModelSpec, Pricing

    def high_spec(model_id: str) -> ModelSpec:
        return ModelSpec(
            id=model_id,
            label=model_id,
            provider="opencode",
            enabled=True,
            capability=Capability(
                dialect="anthropic_messages",
                supports_vision=True,
                max_output_tokens=16384,
                image=ImageLimits(max_side_px=None),
                prompt_profile="default",
                fallback_model="grok-4.5",
            ),
            pricing=Pricing(),
        )

    monkeypatch.setattr(mod, "_default_spec", high_spec)
    monkeypatch.setattr(mod, "lookup", lambda model: None)

    result = backend.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, concurrency=1, vlm_max_tokens=8192),
        listener=listener,
    )
    assert result[1] == "Recovered page"
    assert calls["n"] == 2
    assert any(isinstance(e, PageRetry) for e in listener.events)


def test_empty_non_truncated_uses_fallback_then_page_empty(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    models_seen: list[str] = []

    class FakeResp:
        def __init__(self, payload, status=200):
            self.status_code = status
            self.text = "{}"
            self._payload = payload

        def json(self):
            return self._payload

    class FakeSession:
        def post(self, url, *args, **kwargs):
            body = kwargs.get("json") or {}
            models_seen.append(body.get("model") or url)
            if "/messages" in url:
                return FakeResp(
                    {
                        "content": [{"type": "text", "text": "   "}],
                        "stop_reason": "end_turn",
                    }
                )
            # OpenAI fallback also empty after postprocess
            return FakeResp(
                {
                    "choices": [
                        {
                            "message": {"content": "   \n"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            )

    backend = OpencodeVlmBackend()
    backend._session = FakeSession()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image()},
    )
    listener = _Listener()
    result = backend.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, concurrency=1),
        listener=listener,
    )
    assert result[1] == ""
    assert any(isinstance(e, PageEmpty) for e in listener.events)
    assert any(isinstance(e, FallbackUsed) for e in listener.events)
