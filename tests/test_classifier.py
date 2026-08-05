from pathlib import Path

import pytest

from smart_pdf2md.classifier import analyze_pdf, extract_pages

FIXTURES = Path(__file__).parent / "fixtures" / "input"


def test_analyze_text_based_pdf():
    result = analyze_pdf(FIXTURES / "WB-1.pdf")
    assert result.pdf_type == "text_based"
    assert result.page_count == 8
    assert result.pages_needing_ocr == []
    assert result.confidence >= 0.9
    assert result.recommendation


def test_analyze_scanned_mixed_pdf():
    result = analyze_pdf(FIXTURES / "Thông-tư-89-2026-TT-BTC.pdf")
    assert result.pdf_type in {"scanned", "mixed", "image_based"}
    assert result.page_count > 100
    assert len(result.pages_needing_ocr) > 100


def test_analyze_presentation_pdf():
    result = analyze_pdf(FIXTURES / "Session 1.pdf")
    assert result.pdf_type == "text_based"
    assert result.page_count == 42


def test_analyze_missing_file():
    with pytest.raises(Exception):
        analyze_pdf(FIXTURES / "khong-ton-tai.pdf")


def test_extract_pages_text_based():
    pages, analysis = extract_pages(FIXTURES / "WB-1.pdf")
    assert len(pages) == 8
    assert [p.page for p in pages] == list(range(8))
    assert all(p.source == "native" for p in pages)
    assert pages[0].markdown.startswith("# ")


def test_extract_pages_vietnamese_diacritics():
    pages, _ = extract_pages(FIXTURES / "WB-1.pdf")
    combined = "\n".join(p.markdown for p in pages)
    assert "Thời lượng" in combined
    assert "Bước" in combined


def test_extract_pages_falls_back_to_poppler_when_inspector_returns_zero(monkeypatch):
    """Some ObjStm PDFs make pdf-inspector report page_count=0; poppler still knows."""
    import pdf_inspector

    class FakeResult:
        pdf_type = "scanned"
        markdown = None
        page_count = 0
        processing_time_ms = 1
        pages_needing_ocr = []
        title = None
        confidence = 0.9
        is_complex_layout = False
        pages_with_tables = []
        pages_with_columns = []
        has_encoding_issues = False

    class FakeExtraction:
        pages = []
        pages_with_tables = []
        pages_with_columns = []
        pages_needing_ocr = []
        is_complex = False

    monkeypatch.setattr(pdf_inspector, "process_pdf", lambda path: FakeResult())
    monkeypatch.setattr(
        pdf_inspector, "extract_pages_markdown", lambda path: FakeExtraction()
    )
    monkeypatch.setattr(
        "smart_pdf2md.classifier.page_count_from_poppler",
        lambda path, poppler_path=None: 327,
    )

    pages, analysis = extract_pages(FIXTURES / "WB-1.pdf")
    assert analysis.page_count == 327
    assert analysis.pdf_type == "scanned"
    assert len(pages) == 327
    assert pages[0].needs_ocr is True
    assert analysis.pages_needing_ocr == list(range(1, 328))
