from pathlib import Path

import pytest

from smart_pdf2md import analyze, convert
from smart_pdf2md.errors import OcrBackendError

FIXTURES = Path(__file__).parent / "fixtures" / "input"


def test_convert_returns_markdown():
    markdown = convert(FIXTURES / "WB-1.pdf", show_progress=False)
    assert markdown.startswith("<!-- Page 1 -->")
    assert "<!-- Page 8 -->" in markdown
    assert "Thời lượng" in markdown


def test_convert_with_output(tmp_path):
    out = tmp_path / "out.md"
    markdown = convert(FIXTURES / "WB-1.pdf", output=out, show_progress=False)
    assert out.exists()
    assert out.read_text(encoding="utf-8") == markdown


def test_convert_no_page_markers():
    markdown = convert(
        FIXTURES / "WB-1.pdf",
        page_markers=False,
        show_progress=False,
    )
    assert "<!--" not in markdown


def test_convert_compact():
    markdown = convert(FIXTURES / "WB-1.pdf", compact=True, show_progress=False)
    assert "\n\n\n" not in markdown


def test_convert_scanned_uses_ocr_backend(monkeypatch):
    from smart_pdf2md import converter as conv
    from smart_pdf2md.errors import OcrBackendError
    from smart_pdf2md.ocr.base import OcrBackend

    class _FailingBackend(OcrBackend):
        name = "fake"

        def ocr_pages(self, pages, pdf_path, options, on_page_done=None, on_page_start=None):
            raise OcrBackendError("backend down")

    monkeypatch.setattr(conv, "get_ocr_backend", lambda name: _FailingBackend())
    with pytest.raises(OcrBackendError, match="backend down"):
        conv.convert_full(
            FIXTURES / "Thông-tư-89-2026-TT-BTC.pdf",
            show_progress=False,
            pages=[2],
        )


def test_analyze_api():
    result = analyze(FIXTURES / "WB-1.pdf")
    assert result.pdf_type == "text_based"


def test_sparse_native_page_routed_to_ocr(monkeypatch):
    from smart_pdf2md import converter as conv
    from smart_pdf2md.classifier import AnalysisResult
    from smart_pdf2md.errors import OcrBackendError
    from smart_pdf2md.models import PageResult
    from smart_pdf2md.ocr.base import OcrBackend

    called = []

    class _CapturingBackend(OcrBackend):
        name = "fake"

        def ocr_pages(self, pages, pdf_path, options, on_page_done=None, on_page_start=None):
            called.extend(p.page + 1 for p in pages)
            return {p.page + 1: "Nội dung OCR" for p in pages}

    analysis = AnalysisResult(
        pdf_type="mixed",
        confidence=0.5,
        page_count=2,
        pages_needing_ocr=[2],
        has_encoding_issues=False,
        is_complex_layout=False,
        title=None,
        processing_time_ms=1,
        recommendation="",
    )

    def fake_extract_pages(_path):
        pages = [
            PageResult(page=0, markdown="Ký bởi: BỘ TÀI CHÍNH", needs_ocr=False),
            PageResult(page=1, markdown="", needs_ocr=True),
        ]
        return pages, analysis

    monkeypatch.setattr(conv, "extract_pages", fake_extract_pages)
    monkeypatch.setattr(conv, "get_ocr_backend", lambda name: _CapturingBackend())

    result = conv.convert_full("fake.pdf", show_progress=False, use_cache=False)
    assert called == [1, 2]
    assert result.pages[0].source == "ocr"


def test_sparse_page_not_ocr_in_text_based(monkeypatch):
    from smart_pdf2md import converter as conv
    from smart_pdf2md.classifier import AnalysisResult
    from smart_pdf2md.models import PageResult

    analysis = AnalysisResult(
        pdf_type="text_based",
        confidence=1.0,
        page_count=1,
        pages_needing_ocr=[],
        has_encoding_issues=False,
        is_complex_layout=False,
        title=None,
        processing_time_ms=1,
        recommendation="",
    )

    def fake_extract_pages(_path):
        return [PageResult(page=0, markdown="Trang gần như trống", needs_ocr=False)], analysis

    monkeypatch.setattr(conv, "extract_pages", fake_extract_pages)
    result = conv.convert_full("fake.pdf", show_progress=False)
    assert result.pages[0].source == "native"
