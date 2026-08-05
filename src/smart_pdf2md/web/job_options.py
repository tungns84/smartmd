from __future__ import annotations

from typing import Any, Optional, Sequence

from fastapi import HTTPException, status

from smart_pdf2md.ocr.vlm.registry import lookup

MAX_PAGE_SPEC_PAGES = 10_000


def clamp_int(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


def _coerce_int(
    value: Any,
    default: int,
    field: str,
    *,
    lo: Optional[int] = None,
    hi: Optional[int] = None,
) -> int:
    """Parse an int for form/JSON fields; invalid values become 422 (not 500)."""
    if value is None or value == "":
        n = default
    else:
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} must be an integer",
            ) from None
    if lo is not None and n < lo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} must be >= {lo}",
        )
    if hi is not None and n > hi:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} must be <= {hi}",
        )
    return n


def _bad_pages(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


def parse_page_selection(value: Any, page_count: int = 0) -> Optional[list[int]]:
    """Parse ``"1-3,5,8"`` into sorted 1-indexed pages, same syntax as CLI --page.

    Returns ``None`` for "every page" (empty, ``"all"``, or a spec covering the
    whole document) so callers keep their existing no-subset code paths.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        tokens = [str(item) for item in value]
    else:
        text = str(value).strip()
        if not text or text.lower() == "all":
            return None
        tokens = text.split(",")

    pages: set[int] = set()
    for raw in tokens:
        token = raw.strip()
        if not token:
            continue
        if "-" in token:
            start_text, _, end_text = token.partition("-")
            try:
                start, end = int(start_text), int(end_text)
            except ValueError:
                raise _bad_pages(f"Khoảng trang không hợp lệ: {token}") from None
            if start < 1 or end < start:
                raise _bad_pages(f"Khoảng trang không hợp lệ: {token}")
            # Reject oversized ranges before materialising them (DoS).
            if page_count > 0:
                if end > page_count:
                    raise _bad_pages(
                        f"Tài liệu có {page_count} trang, yêu cầu {start}-{end}"
                    )
            elif end - start >= MAX_PAGE_SPEC_PAGES:
                raise _bad_pages(
                    f"Khoảng trang quá lớn (tối đa {MAX_PAGE_SPEC_PAGES} trang): {token}"
                )
            pages.update(range(start, end + 1))
        else:
            try:
                page = int(token)
            except ValueError:
                raise _bad_pages(f"Số trang không hợp lệ: {token}") from None
            if page < 1:
                raise _bad_pages(f"Số trang không hợp lệ: {token}")
            pages.add(page)

    if not pages:
        raise _bad_pages("Chưa chọn trang")
    if page_count > 0:
        beyond = sorted(p for p in pages if p > page_count)
        if beyond:
            shown = ", ".join(str(p) for p in beyond[:10])
            more = f" (+{len(beyond) - 10} nữa)" if len(beyond) > 10 else ""
            raise _bad_pages(f"Tài liệu có {page_count} trang, yêu cầu {shown}{more}")
        if len(pages) == page_count:
            return None
    return sorted(pages)


def format_page_selection(pages: Optional[Sequence[int]]) -> str:
    """Collapse a page list back into a compact ``1-3,5`` spec for display."""
    if not pages:
        return "all"
    ordered = sorted(set(pages))
    groups: list[str] = []
    start = previous = ordered[0]
    for page in ordered[1:]:
        if page == previous + 1:
            previous = page
            continue
        groups.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    groups.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(groups)


def validate_job_options(
    payload: dict[str, Any],
    *,
    page_count: int = 0,
) -> dict[str, Any]:
    """Validate/clamp client job options. Ignores client-supplied API keys."""
    backend = str(payload.get("backend") or "opencode")
    model = payload.get("vlm_model") or payload.get("model")
    dpi = clamp_int(_coerce_int(payload.get("dpi", 200), 200, "dpi"), 72, 600)
    jpeg_quality = clamp_int(
        _coerce_int(payload.get("vlm_jpeg_quality", 85), 85, "vlm_jpeg_quality"),
        40,
        95,
    )
    force_ocr = bool(payload.get("force_ocr", False))
    use_cache = bool(payload.get("use_cache", True))
    max_tokens = _coerce_int(
        payload.get("vlm_max_tokens", 8192), 8192, "vlm_max_tokens"
    )

    if backend == "opencode":
        if not model:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cần chọn mô hình VLM cho opencode",
            )
        spec = lookup(str(model))
        if spec is None or not spec.enabled:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Mô hình không tồn tại hoặc đã tắt: {model}",
            )
        max_tokens = clamp_int(max_tokens, 256, int(spec.capability.max_output_tokens))
    else:
        max_tokens = clamp_int(max_tokens, 256, 32768)

    # Explicitly drop any client-supplied secrets
    return {
        "backend": backend,
        "vlm_model": str(model) if model else None,
        "dpi": dpi,
        "vlm_jpeg_quality": jpeg_quality,
        "vlm_max_tokens": max_tokens,
        "force_ocr": force_ocr,
        "use_cache": use_cache,
        "allow_vlm_fallback": bool(payload.get("allow_vlm_fallback", True)),
        "pages": parse_page_selection(payload.get("pages"), page_count),
    }


def estimate_job_cost_usd(
    *,
    model: Optional[str],
    ocr_pages: int,
    avg_input_tokens: int = 3000,
    avg_output_tokens: int = 1200,
) -> Optional[float]:
    if not model or ocr_pages <= 0:
        return 0.0 if ocr_pages == 0 else None
    from smart_pdf2md.ocr.vlm.registry import estimate_cost_usd

    per = estimate_cost_usd(model, avg_input_tokens, avg_output_tokens)
    if per is None:
        return None
    return per * ocr_pages
