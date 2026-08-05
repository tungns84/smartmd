"""Parallel OCR batching: concurrent pages + usage lock safety."""

import threading
import time

from smart_pdf2md.config import Options
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.opencode_backend import OpencodeVlmBackend


def _fake_image():
    from PIL import Image

    return Image.new("RGB", (16, 16), color=(255, 255, 255))


def test_parallel_ocr_completes_all_pages(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-test")
    active = {"n": 0}
    lock = threading.Lock()
    peak = {"n": 0}

    class FakeResp:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "content": [{"type": "text", "text": "parallel ok"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }

    class FakeSession:
        def post(self, *args, **kwargs):
            with lock:
                active["n"] += 1
                peak["n"] = max(peak["n"], active["n"])
            time.sleep(0.05)
            with lock:
                active["n"] -= 1
            return FakeResp()

    backend = OpencodeVlmBackend()
    backend._session = FakeSession()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.opencode_backend.render_pages",
        lambda pdf_path, page_numbers, **k: {
            p: _fake_image() for p in page_numbers
        },
    )
    pages = [PageResult(page=i, markdown="") for i in range(4)]
    result = backend.ocr_pages(
        pages,
        "x.pdf",
        Options(show_progress=False, concurrency=4),
    )
    assert sorted(result) == [1, 2, 3, 4]
    assert all(result[p] == "parallel ok" for p in result)
    assert peak["n"] >= 2
    inp, out, _cost = backend.consume_usage()
    assert inp == 40
    assert out == 20
