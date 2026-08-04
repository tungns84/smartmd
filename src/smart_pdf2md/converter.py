from pathlib import Path
from typing import Optional

from smart_pdf2md.classifier import AnalysisResult, analyze_pdf, extract_pages
from smart_pdf2md.config import Options
from smart_pdf2md.merge import merge_pages
from smart_pdf2md.models import ConversionResult, PageResult
from smart_pdf2md.ocr import get_ocr_backend
from smart_pdf2md.progress import page_done_callback


def _pages_needing_ocr(analysis: AnalysisResult, options: Options) -> set[int]:
    if options.force_ocr:
        return set(range(1, analysis.page_count + 1))
    return set(analysis.pages_needing_ocr)


MIN_NATIVE_CHARS = 120


def _sparse_native_pages(
    all_pages: list[PageResult],
    analysis: AnalysisResult,
    selected: list[PageResult],
) -> set[int]:
    if analysis.pdf_type in {"text_based"}:
        return set()
    selected_numbers = {p.page + 1 for p in selected}
    sparse: set[int] = set()
    for page in all_pages:
        if (page.page + 1) not in selected_numbers:
            continue
        if page.needs_ocr or page.source == "ocr":
            continue
        if len(page.markdown.strip()) < MIN_NATIVE_CHARS:
            sparse.add(page.page + 1)
    return sparse


def _select_pages(pages: list[PageResult], subset: Optional[list[int]]) -> list[PageResult]:
    if not subset:
        return pages
    wanted = set(subset)
    return [p for p in pages if (p.page + 1) in wanted]


def convert_full(
    pdf_path: str | Path,
    output: Optional[str | Path] = None,
    languages: Optional[list[str]] = None,
    dpi: int = 200,
    compact: bool = False,
    force_ocr: bool = False,
    show_progress: bool = True,
    page_markers: bool = True,
    pages: Optional[list[int]] = None,
    ocr_backend: str = "surya",
    poppler_path: Optional[str] = None,
) -> ConversionResult:
    options = Options(
        languages=languages or ["vi", "en"],
        dpi=dpi,
        compact=compact,
        force_ocr=force_ocr,
        show_progress=show_progress,
        page_markers=page_markers,
        ocr_backend=ocr_backend,
        poppler_path=poppler_path,
    )

    all_pages, analysis = extract_pages(pdf_path)
    selected = _select_pages(all_pages, pages)
    if not selected:
        raise ValueError("Không có trang nào khớp với yêu cầu")
    ocr_pages = _pages_needing_ocr(analysis, options) & {p.page + 1 for p in selected}
    ocr_pages |= _sparse_native_pages(all_pages, analysis, selected)

    if ocr_pages:
        backend = get_ocr_backend(options.ocr_backend)
        targets = [p for p in selected if (p.page + 1) in ocr_pages]
        on_done = page_done_callback(
            quiet=not show_progress,
            show_progress=show_progress,
        )
        ocr_results = backend.ocr_pages(
            targets,
            str(pdf_path),
            options,
            on_page_done=on_done,
        )
        for page in selected:
            page_number = page.page + 1
            if page_number in ocr_results:
                page.markdown = ocr_results[page_number]
                page.source = "ocr"
                page.needs_ocr = False

    markdown = merge_pages(
        selected,
        page_markers=options.page_markers,
        compact=options.compact,
    )

    if output is not None:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown, encoding="utf-8")

    return ConversionResult(
        pdf_type=analysis.pdf_type,
        confidence=analysis.confidence,
        page_count=len(selected),
        pages=selected,
        pages_needing_ocr=analysis.pages_needing_ocr,
        markdown=markdown,
        processing_time_ms=analysis.processing_time_ms,
        has_encoding_issues=analysis.has_encoding_issues,
        title=analysis.title,
    )


def convert(
    pdf_path: str | Path,
    output: Optional[str | Path] = None,
    languages: Optional[list[str]] = None,
    dpi: int = 200,
    compact: bool = False,
    force_ocr: bool = False,
    show_progress: bool = True,
    page_markers: bool = True,
    pages: Optional[list[int]] = None,
    ocr_backend: str = "surya",
    poppler_path: Optional[str] = None,
) -> str:
    result = convert_full(
        pdf_path,
        output=output,
        languages=languages,
        dpi=dpi,
        compact=compact,
        force_ocr=force_ocr,
        show_progress=show_progress,
        page_markers=page_markers,
        pages=pages,
        ocr_backend=ocr_backend,
        poppler_path=poppler_path,
    )
    return result.markdown


def analyze(pdf_path: str | Path) -> AnalysisResult:
    return analyze_pdf(pdf_path)