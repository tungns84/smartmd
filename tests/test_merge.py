import pytest

from smart_pdf2md.errors import MergeError
from smart_pdf2md.merge import merge_pages
from smart_pdf2md.models import PageResult


def _page(n: int, md: str = "Nội dung trang") -> PageResult:
    return PageResult(page=n, markdown=md, needs_ocr=False)


def test_merge_single_page():
    merged = merge_pages([_page(0, "Xin chào")])
    assert merged == "<!-- Page 1 -->\n\nXin chào\n"


def test_merge_multiple_pages_order():
    merged = merge_pages([_page(0, "Trang A"), _page(1, "Trang B")])
    assert merged.index("Trang A") < merged.index("Trang B")
    assert "<!-- Page 1 -->" in merged
    assert "<!-- Page 2 -->" in merged


def test_merge_marks_empty_pages():
    merged = merge_pages([_page(0, ""), _page(1, "Có nội dung")])
    assert "<!-- Page 1: OCR rỗng -->" in merged
    assert "<!-- Page 2 -->" in merged


def test_merge_no_markers():
    merged = merge_pages([_page(0, "A"), _page(1, "B")], page_markers=False)
    assert "<!--" not in merged


def test_merge_compact():
    md = "Dòng 1\n\n\n\n\nDòng 2\n\n\n\n\nDòng 3"
    merged = merge_pages([_page(0, md)], compact=True)
    assert "\n\n\n" not in merged


def test_merge_empty_input():
    with pytest.raises(MergeError):
        merge_pages([])


def test_merge_all_empty():
    merged = merge_pages([_page(0, ""), _page(1, "")])
    assert "<!-- Page 1: OCR rỗng -->" in merged
    assert "<!-- Page 2: OCR rỗng -->" in merged
