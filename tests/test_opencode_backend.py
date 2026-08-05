import unicodedata

import pytest
import requests

from smart_pdf2md.config import Options
from smart_pdf2md.errors import OcrBackendError, OcrFatalError
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.opencode_backend import (
    OpencodeVlmBackend,
    _build_payload,
    _extract_text,
    _extract_usage,
    _postprocess,
)


def test_build_payload_has_image_and_text_blocks():
    payload = _build_payload("abc123", model="qwen3.6-plus", max_tokens=8192)
    assert payload["model"] == "qwen3.6-plus"
    assert payload["max_tokens"] == 8192
    content = payload["messages"][0]["content"]
    assert len(content) == 2
    assert content[0]["type"] == "image"
    assert content[0]["source"]["data"] == "abc123"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1]["type"] == "text"
    assert "Vietnamese" in content[1]["text"]


def test_extract_text_joins_multiple_blocks():
    payload = {
        "content": [
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "world"},
            {"type": "image", "source": {}},
        ]
    }
    assert _extract_text(payload) == "Hello world"


def test_extract_text_bad_schema_raises():
    with pytest.raises(OcrBackendError, match="schema lạ"):
        _extract_text({"content": "not-a-list"})


def test_postprocess_strips_fence_and_nfc():
    # NFD: o + combining dot below → NFC Độ
    nfd = "Đô" + "\u0323"
    fenced = f"```markdown\n{nfd}\n```"
    out = _postprocess(fenced)
    assert out == unicodedata.normalize("NFC", nfd)
    assert "\u0323" not in out
    assert out == "Độ"


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    # Prevent load_app_env from re-injecting the key from a local .env.
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.load_app_env",
        lambda: None,
    )
    backend = OpencodeVlmBackend()
    with pytest.raises(OcrBackendError, match="OPENCODE_API_KEY"):
        backend.ocr_pages(
            [PageResult(page=0, markdown="")],
            "x.pdf",
            Options(show_progress=False),
        )


def test_http_401_raises_fatal(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")

    class FakeResp:
        status_code = 401
        text = '{"error":"nope"}'

        def json(self):
            return {"error": "nope"}

    class FakeSession:
        def post(self, *args, **kwargs):
            return FakeResp()

    backend = OpencodeVlmBackend()
    backend._session = FakeSession()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image()},
    )
    with pytest.raises(OcrFatalError, match="không hợp lệ"):
        backend.ocr_pages(
            [PageResult(page=0, markdown="")],
            "x.pdf",
            Options(show_progress=False, concurrency=1),
        )


def test_http_429_retries_then_page_failed(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    calls = {"n": 0}
    failed: list[tuple[int, str]] = []

    class FakeResp:
        status_code = 429
        text = "rate limited"

        def json(self):
            return {"error": "rate"}

    class FakeSession:
        def post(self, *args, **kwargs):
            calls["n"] += 1
            return FakeResp()

    class Listener:
        def emit(self, event):
            from smart_pdf2md.events import PageFailed

            if isinstance(event, PageFailed):
                failed.append((event.page, event.reason))

        def close(self):
            return None

    backend = OpencodeVlmBackend()
    backend._session = FakeSession()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image()},
    )
    monkeypatch.setattr("smart_pdf2md.ocr.opencode_backend.time.sleep", lambda *_: None)
    result = backend.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, concurrency=1),
        listener=Listener(),
    )
    assert result[1] == ""
    assert calls["n"] == 3  # initial + 2 retries
    assert len(failed) == 1
    assert failed[0][0] == 1
    assert "usage limit" in failed[0][1]


def test_timeout_retries_then_page_failed(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    calls = {"n": 0}

    class FakeSession:
        def post(self, *args, **kwargs):
            calls["n"] += 1
            raise requests.Timeout("slow")

    backend = OpencodeVlmBackend()
    backend._session = FakeSession()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image()},
    )
    monkeypatch.setattr("smart_pdf2md.ocr.opencode_backend.time.sleep", lambda *_: None)
    result = backend.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, concurrency=1),
    )
    assert result[1] == ""
    assert calls["n"] == 3


def test_ocr_pages_success_calls_on_page_done(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    md = "Độc lập - Tự do - Hạnh phúc"

    class FakeResp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"content": [{"type": "text", "text": md}]}

    class FakeSession:
        def post(self, *args, **kwargs):
            # Ensure Anthropic-style x-api-key auth
            headers = kwargs.get("headers") or {}
            assert "x-api-key" in headers
            assert headers["x-api-key"] == "sk-test"
            body = kwargs.get("json") or {}
            assert body["model"] == "qwen3.6-plus"
            return FakeResp()

    backend = OpencodeVlmBackend()
    backend._session = FakeSession()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image()},
    )
    done: list[tuple[int, int]] = []
    started: list[tuple[int, int]] = []
    result = backend.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, concurrency=1),
        on_page_done=lambda page, n: done.append((page, n)),
        on_page_start=lambda page, index: started.append((page, index)),
    )
    assert result[1] == md
    assert started == [(1, 1)]
    assert done == [(1, len(md))]


def test_extract_usage_anthropic():
    assert _extract_usage(
        {"usage": {"input_tokens": 1200, "output_tokens": 340}}
    ) == (1200, 340)


def test_extract_usage_openai():
    assert _extract_usage(
        {"usage": {"prompt_tokens": 900, "completion_tokens": 100}}
    ) == (900, 100)


def test_extract_usage_missing_returns_zeros():
    assert _extract_usage({"content": []}) == (0, 0)
    assert _extract_usage(None) == (0, 0)
    assert _extract_usage({"usage": {}}) == (0, 0)


def test_consume_usage_accumulates_from_responses(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    md = "page text"

    class FakeResp:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "content": [{"type": "text", "text": md}],
                "usage": {"input_tokens": 2500, "output_tokens": 800},
            }

    backend = OpencodeVlmBackend()
    backend._session = type("S", (), {"post": lambda self, *a, **k: FakeResp()})()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image(), 2: _fake_image()},
    )
    backend.ocr_pages(
        [
            PageResult(page=0, markdown=""),
            PageResult(page=1, markdown=""),
        ],
        "x.pdf",
        Options(show_progress=False, vlm_model="qwen3.6-plus", concurrency=1),
    )
    inp, out, cost = backend.consume_usage()
    assert inp == 5000
    assert out == 1600
    assert cost is not None
    assert abs(cost - (5000 * 0.50 + 1600 * 3.00) / 1_000_000) < 1e-12
    # Second consume is empty
    assert backend.consume_usage() == (0, 0, None)


def test_consume_usage_missing_usage_is_zero(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")

    class FakeResp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"content": [{"type": "text", "text": "hi"}]}

    backend = OpencodeVlmBackend()
    backend._session = type("S", (), {"post": lambda self, *a, **k: FakeResp()})()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image()},
    )
    backend.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, concurrency=1),
    )
    assert backend.consume_usage() == (0, 0, None)


def test_consume_usage_prices_grok_fallback_per_call(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    calls = {"n": 0}

    class FakeResp:
        def __init__(self, status, payload):
            self.status_code = status
            self.text = "err" if status >= 400 else "{}"
            self._payload = payload

        def json(self):
            return self._payload

    class FakeSession:
        def post(self, url, *args, **kwargs):
            calls["n"] += 1
            if "/messages" in url:
                # text must trip _image_rejected (checked on resp.text)
                resp = FakeResp(
                    400,
                    {"error": "model does not support image content"},
                )
                resp.text = "model does not support image content"
                return resp
            return FakeResp(
                200,
                {
                    "choices": [
                        {"message": {"content": "fallback md"}},
                    ],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
                },
            )

    backend = OpencodeVlmBackend()
    backend._session = FakeSession()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda *a, **k: {1: _fake_image()},
    )
    backend.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False, vlm_model="qwen3.6-plus", concurrency=1),
    )
    inp, out, cost = backend.consume_usage()
    assert inp == 1000
    assert out == 200
    # Priced as grok-4.5, not qwen3.6-plus
    assert cost == (1000 * 2.00 + 200 * 6.00) / 1_000_000


def test_format_ocr_cost_note():
    from smart_pdf2md.cli import _format_ocr_cost_note
    from smart_pdf2md.models import ConversionResult

    with_cost = ConversionResult(
        pdf_type="scanned",
        confidence=1.0,
        page_count=20,
        ocr_input_tokens=77600,
        ocr_output_tokens=27100,
        ocr_cost_usd=0.05605,
    )
    note = _format_ocr_cost_note(with_cost)
    assert note.startswith(" | ~$0.0561 (in 77.6k / out 27.1k)")

    tokens_only = ConversionResult(
        pdf_type="scanned",
        confidence=1.0,
        page_count=1,
        ocr_input_tokens=100,
        ocr_output_tokens=50,
        ocr_cost_usd=None,
    )
    assert _format_ocr_cost_note(tokens_only) == " | in 100 / out 50"

    empty = ConversionResult(pdf_type="text", confidence=1.0, page_count=1)
    assert _format_ocr_cost_note(empty) == ""


def _fake_image():
    from PIL import Image

    return Image.new("RGB", (16, 16), color=(255, 255, 255))
