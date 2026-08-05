import pytest

from smart_pdf2md.config import Options
from smart_pdf2md.errors import OcrBackendError
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.paddleocr_backend import (
    PaddleOcrBackend,
    _predict_to_regions,
    _regions_to_markdown,
)


def test_regions_to_markdown_reading_order_and_paragraph_gap():
    # Same-line-ish vertical gap (height ~10) → single newlines
    # Large gap (> 1.5 * median height) → blank line (paragraph)
    regions = [
        {"text": "Bottom", "upper": 80.0, "left": 10.0, "height": 10.0},
        {"text": "Top-right", "upper": 10.0, "left": 60.0, "height": 10.0},
        {"text": "Top-left", "upper": 10.0, "left": 10.0, "height": 10.0},
        {"text": "  ", "upper": 50.0, "left": 10.0, "height": 10.0},
        {"text": "Para2", "upper": 50.0, "left": 10.0, "height": 10.0},
    ]
    md = _regions_to_markdown(regions)
    # Top-left / Top-right same upper → join with \n (gap 0)
    # Para2 at 50: gap from 10 = 40 > 1.5*10=15 → blank line
    # Bottom at 80: gap from 50 = 30 > 15 → blank line
    assert md == "Top-left\nTop-right\n\nPara2\n\nBottom"


def test_predict_to_regions_dict_res():
    result = [
        {
            "res": {
                "rec_texts": ["Hello", "World"],
                # World upper=5 h=10; Hello upper=40 h=10 → gap 35 > 1.5*10
                "rec_boxes": [[10, 40, 50, 50], [5, 5, 40, 15]],
            }
        }
    ]
    regions = _predict_to_regions(result)
    assert _regions_to_markdown(regions) == "World\n\nHello"


def test_missing_paddleocr_import_raises(monkeypatch):
    import builtins

    backend = PaddleOcrBackend()
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "paddleocr" or name.startswith("paddleocr."):
            raise ImportError("no paddleocr")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(OcrBackendError, match="PaddleOCR chưa sẵn sàng"):
        backend.ocr_pages(
            [PageResult(page=0, markdown="")],
            "x.pdf",
            Options(show_progress=False),
        )


def _fake_image():
    from PIL import Image

    return Image.new("RGB", (16, 16), color=(255, 255, 255))


def test_ocr_pages_success_calls_on_page_done(monkeypatch):
    class FakeEngine:
        def predict(self, img):
            return [
                {
                    "res": {
                        "rec_texts": ["Paragraph A", "Paragraph B"],
                        "rec_boxes": [
                            [10, 10, 100, 20],
                            [10, 50, 100, 60],
                        ],
                    }
                }
            ]

    backend = PaddleOcrBackend()
    backend._engine = FakeEngine()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.paddleocr_backend.render_pages",
        lambda *a, **k: {1: _fake_image()},
    )
    done = []
    started = []
    out = backend.ocr_pages(
        [PageResult(page=0, markdown="")],
        "x.pdf",
        Options(show_progress=False),
        on_page_done=lambda page, n: done.append((page, n)),
        on_page_start=lambda page, index: started.append((page, index)),
    )
    # gap 40 > 1.5 * median(10)=15 → paragraph break
    assert out[1] == "Paragraph A\n\nParagraph B"
    assert started == [(1, 1)]
    assert done == [(1, len(out[1]))]


def test_predict_runtime_error_wrapped(monkeypatch):
    class BoomEngine:
        def predict(self, img):
            raise RuntimeError("cuda OOM")

    backend = PaddleOcrBackend()
    backend._engine = BoomEngine()
    monkeypatch.setattr(
        "smart_pdf2md.ocr.paddleocr_backend.render_pages",
        lambda *a, **k: {1: _fake_image()},
    )
    with pytest.raises(OcrBackendError, match="PaddleOCR lỗi"):
        backend.ocr_pages(
            [PageResult(page=0, markdown="")],
            "x.pdf",
            Options(show_progress=False),
        )
