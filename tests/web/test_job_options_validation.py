"""Cycle 11: job option validation (no DB)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from smart_pdf2md.web.job_options import (
    MAX_PAGE_SPEC_PAGES,
    _coerce_int,
    format_page_selection,
    parse_page_selection,
    validate_job_options,
)


def test_unknown_or_disabled_model_rejected_422():
    with pytest.raises(HTTPException) as exc:
        validate_job_options({"backend": "opencode", "vlm_model": "nope-model"})
    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    "field,raw,lo,hi",
    [
        ("dpi", 10, 72, 600),
        ("dpi", 9999, 72, 600),
        ("vlm_jpeg_quality", 1, 40, 95),
        ("vlm_jpeg_quality", 100, 40, 95),
    ],
)
def test_numeric_options_clamped(field, raw, lo, hi):
    out = validate_job_options(
        {"backend": "opencode", "vlm_model": "qwen3.6-plus", field: raw}
    )
    assert lo <= out[field] <= hi


def test_max_tokens_clamped_to_model_limit():
    out = validate_job_options(
        {
            "backend": "opencode",
            "vlm_model": "qwen3.6-plus",
            "vlm_max_tokens": 999999,
        }
    )
    assert out["vlm_max_tokens"] == 8192


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("1-3,5", [1, 2, 3, 5]),
        (" 5 , 1 , 1 ", [1, 5]),
        ("2-2", [2]),
        ([3, 1], [1, 3]),
    ],
)
def test_page_spec_parsed_and_normalized(spec, expected):
    assert parse_page_selection(spec, page_count=10) == expected


@pytest.mark.parametrize("spec", [None, "", "   ", "all", "ALL"])
def test_blank_or_all_means_every_page(spec):
    assert parse_page_selection(spec, page_count=10) is None


def test_full_selection_collapses_to_every_page():
    assert parse_page_selection("1-4", page_count=4) is None


@pytest.mark.parametrize("spec", ["0", "-2", "3-1", "abc", "1-x", "12"])
def test_invalid_page_spec_rejected_422(spec):
    with pytest.raises(HTTPException) as exc:
        parse_page_selection(spec, page_count=10)
    assert exc.value.status_code == 422


def test_page_count_unknown_skips_range_check():
    assert parse_page_selection("99", page_count=0) == [99]


def test_oversized_range_rejected_when_page_count_unknown():
    with pytest.raises(HTTPException) as exc:
        parse_page_selection(f"1-{MAX_PAGE_SPEC_PAGES + 5}", page_count=0)
    assert exc.value.status_code == 422


def test_beyond_pages_message_is_truncated():
    with pytest.raises(HTTPException) as exc:
        parse_page_selection(
            ",".join(str(p) for p in range(20, 40)),
            page_count=10,
        )
    detail = str(exc.value.detail)
    assert "nữa" in detail
    assert len(detail) < 200


def test_coerce_int_rejects_non_integer():
    with pytest.raises(HTTPException) as exc:
        _coerce_int("x", 1, "dpi")
    assert exc.value.status_code == 422


def test_malformed_dpi_in_validate_job_options():
    with pytest.raises(HTTPException) as exc:
        validate_job_options(
            {"backend": "opencode", "vlm_model": "qwen3.6-plus", "dpi": "bad"}
        )
    assert exc.value.status_code == 422


def test_coerce_int_default_and_bounds():
    assert _coerce_int(None, 7, "dpi") == 7
    assert _coerce_int("", 9, "dpi") == 9
    with pytest.raises(HTTPException) as lo:
        _coerce_int(-1, 0, "credits", lo=0, hi=10)
    assert lo.value.status_code == 422
    with pytest.raises(HTTPException) as hi:
        _coerce_int(11, 0, "credits", lo=0, hi=10)
    assert hi.value.status_code == 422


def test_empty_tokens_and_empty_selection():
    assert parse_page_selection("1,,3", page_count=10) == [1, 3]
    with pytest.raises(HTTPException) as exc:
        parse_page_selection(",,,", page_count=10)
    assert exc.value.status_code == 422


def test_range_rejected_when_end_beyond_known_page_count():
    with pytest.raises(HTTPException) as exc:
        parse_page_selection("1-50", page_count=10)
    assert exc.value.status_code == 422
    assert "1-50" in str(exc.value.detail)


def test_opencode_requires_model_and_paddle_clamps_tokens():
    with pytest.raises(HTTPException) as exc:
        validate_job_options({"backend": "opencode"})
    assert exc.value.status_code == 422
    out = validate_job_options(
        {"backend": "paddleocr", "vlm_max_tokens": 999999}
    )
    assert out["vlm_max_tokens"] == 32768


def test_estimate_cost_unknown_model_returns_none():
    from smart_pdf2md.web.job_options import estimate_job_cost_usd

    assert estimate_job_cost_usd(model="no-such-model", ocr_pages=3) is None
    assert estimate_job_cost_usd(model=None, ocr_pages=3) is None
    assert estimate_job_cost_usd(model="qwen3.6-plus", ocr_pages=0) == 0.0


@pytest.mark.parametrize(
    "pages,expected",
    [(None, "all"), ([], "all"), ([1, 2, 3, 5], "1-3,5"), ([4], "4")],
)
def test_page_selection_formatted_compactly(pages, expected):
    assert format_page_selection(pages) == expected


def test_pages_included_in_validated_options():
    out = validate_job_options(
        {"backend": "opencode", "vlm_model": "qwen3.6-plus", "pages": "2-3"},
        page_count=10,
    )
    assert out["pages"] == [2, 3]


def test_client_supplied_api_key_field_is_ignored():
    out = validate_job_options(
        {
            "backend": "opencode",
            "vlm_model": "mimo-v2.5",
            "api_key": "sk-leaked",
            "OPENCODE_API_KEY": "sk-leaked",
        }
    )
    assert "api_key" not in out
    assert "OPENCODE_API_KEY" not in out
