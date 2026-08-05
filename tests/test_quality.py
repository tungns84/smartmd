from smart_pdf2md.models import ConversionResult, PageResult
from smart_pdf2md.quality import (
    ReportCollector,
    build_report,
    detect_codeish_unfenced,
    detect_empty,
    detect_short_vs_native,
    detect_short_vs_neighbors,
    detect_table_sparse,
    write_report,
)


def test_detect_empty():
    issue = detect_empty(PageResult(page=0, markdown="  ", source="ocr"))
    assert issue is not None
    assert issue.kind == "empty"
    assert detect_empty(PageResult(page=0, markdown="hi", source="ocr")) is None


def test_detect_short_vs_native():
    page = PageResult(page=0, markdown="abc", source="ocr")
    assert detect_short_vs_native(page, native_chars=100) is not None
    assert detect_short_vs_native(page, native_chars=4) is None


def test_detect_short_vs_neighbors():
    pages = [
        PageResult(page=0, markdown="x" * 100, source="ocr"),
        PageResult(page=1, markdown="short", source="ocr"),
        PageResult(page=2, markdown="y" * 100, source="ocr"),
    ]
    assert detect_short_vs_neighbors(pages, 1) is not None
    assert detect_short_vs_neighbors(pages, 0) is None


def test_detect_table_sparse():
    rows = [
        "| a |  |  |",
        "| --- | --- | --- |",
        "|  |  |  |",
        "|  | b |  |",
        "|  |  |  |",
        "| x |  |  |",
    ]
    page = PageResult(page=0, markdown="\n".join(rows), source="ocr")
    assert detect_table_sparse(page) is not None


def test_detect_codeish_unfenced():
    md = "def foo():\n    pass\n\nclass Bar:\n    pass\n"
    assert detect_codeish_unfenced(PageResult(page=0, markdown=md, source="ocr"))
    fenced = "```python\ndef foo():\n    pass\nclass Bar:\n    pass\n```\n"
    assert detect_codeish_unfenced(PageResult(page=0, markdown=fenced, source="ocr")) is None


def test_build_report_and_write(tmp_path):
    collector = ReportCollector()
    from smart_pdf2md.events import PageEmpty, PageFailed

    collector.emit(PageEmpty(page=1, attempts=2))
    collector.emit(PageFailed(page=2, reason="boom"))
    result = ConversionResult(
        pdf_type="scanned",
        confidence=1.0,
        page_count=2,
        pages=[
            PageResult(page=0, markdown="", source="empty"),
            PageResult(page=1, markdown="", source="empty", ocr_error="boom"),
        ],
        empty_pages=[1],
    )
    report = build_report(result, collector)
    assert report.issue_count >= 2
    assert 1 in report.empty_pages
    assert 2 in report.failed_pages
    out = tmp_path / "q.json"
    write_report(out, report)
    assert '"issue_count"' in out.read_text(encoding="utf-8")
