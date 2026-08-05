"""Per-page OCR isolation + circuit breaker."""

import pytest

from smart_pdf2md.config import Options
from smart_pdf2md.errors import OcrFatalError
from smart_pdf2md.events import PageFailed
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.opencode_backend import OpencodeVlmBackend


def _fake_image():
    from PIL import Image

    return Image.new("RGB", (16, 16), color=(255, 255, 255))


class _Listener:
    def __init__(self):
        self.failed = []

    def emit(self, event):
        if isinstance(event, PageFailed):
            self.failed.append(event.page)

    def close(self):
        return None


def test_transient_failure_continues_to_next_page(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    calls = {"n": 0}

    class FakeResp:
        def __init__(self, status, payload=None, text=""):
            self.status_code = status
            self.text = text or "{}"
            self._payload = payload or {}

        def json(self):
            return self._payload

    class FakeSession:
        def post(self, *args, **kwargs):
            calls["n"] += 1
            # First page always 500 after retries; second succeeds.
            if calls["n"] <= 3:
                return FakeResp(500, text="server error")
            return FakeResp(
                200,
                {"content": [{"type": "text", "text": "ok page 2"}]},
            )

    backend = OpencodeVlmBackend()
    backend._session = FakeSession()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda pdf_path, page_numbers, **k: {
            p: _fake_image() for p in page_numbers
        },
    )
    monkeypatch.setattr("smart_pdf2md.ocr.opencode_backend.time.sleep", lambda *_: None)
    listener = _Listener()
    result = backend.ocr_pages(
        [
            PageResult(page=0, markdown=""),
            PageResult(page=1, markdown=""),
        ],
        "x.pdf",
        Options(show_progress=False, concurrency=1),
        listener=listener,
    )
    assert result[1] == ""
    assert result[2] == "ok page 2"
    assert listener.failed == [1]


def test_circuit_breaker_five_consecutive(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")

    class FakeResp:
        status_code = 500
        text = "boom"

        def json(self):
            return {}

    class FakeSession:
        def post(self, *args, **kwargs):
            return FakeResp()

    backend = OpencodeVlmBackend()
    backend._session = FakeSession()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda pdf_path, page_numbers, **k: {
            p: _fake_image() for p in page_numbers
        },
    )
    monkeypatch.setattr("smart_pdf2md.ocr.opencode_backend.time.sleep", lambda *_: None)

    pages = [PageResult(page=i, markdown="") for i in range(6)]
    with pytest.raises(OcrFatalError, match="circuit breaker"):
        backend.ocr_pages(
            pages,
            "x.pdf",
            Options(show_progress=False, concurrency=1),
        )
