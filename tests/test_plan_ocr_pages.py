"""Cycle 3b: pure OCR routing plan_ocr_pages()."""

from __future__ import annotations

import pytest

from smart_pdf2md.converter import MIN_NATIVE_CHARS, plan_ocr_pages


def test_text_based_returns_empty():
    assert (
        plan_ocr_pages(
            pdf_type="text_based",
            page_count=3,
            pages_needing_ocr=[1, 2],
            page_native_chars=[10, 10, 10],
            force_ocr=False,
        )
        == []
    )


def test_force_ocr_returns_every_page():
    assert plan_ocr_pages(
        pdf_type="text_based",
        page_count=3,
        pages_needing_ocr=[],
        page_native_chars=[500, 500, 500],
        force_ocr=True,
    ) == [1, 2, 3]


@pytest.mark.parametrize(
    "chars,expect_sparse",
    [
        (MIN_NATIVE_CHARS - 1, True),
        (MIN_NATIVE_CHARS, False),
        (MIN_NATIVE_CHARS + 50, False),
    ],
)
def test_sparse_native_page_added_when_mixed_or_scanned(chars, expect_sparse):
    result = plan_ocr_pages(
        pdf_type="mixed",
        page_count=2,
        pages_needing_ocr=[2],
        page_native_chars=[chars, 0],
        force_ocr=False,
    )
    if expect_sparse:
        assert result == [1, 2]
    else:
        assert result == [2]


def test_sparse_native_not_added_when_text_based():
    assert (
        plan_ocr_pages(
            pdf_type="text_based",
            page_count=1,
            pages_needing_ocr=[],
            page_native_chars=[5],
            force_ocr=False,
        )
        == []
    )


def test_selected_pages_filters_result():
    assert plan_ocr_pages(
        pdf_type="scanned",
        page_count=5,
        pages_needing_ocr=[1, 2, 3, 4, 5],
        page_native_chars=[0, 0, 0, 0, 0],
        force_ocr=False,
        selected_pages=[2, 4],
    ) == [2, 4]
