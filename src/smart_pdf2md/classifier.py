from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pdf_inspector

from smart_pdf2md.errors import PdfReadError
from smart_pdf2md.models import PageResult

PDF_TYPE_LABELS = {
    "text_based": "text_based",
    "scanned": "scanned",
    "image_based": "image_based",
    "mixed": "mixed",
}

_RECOMMENDATIONS = {
    "text_based": "Dùng native extraction (không cần OCR)",
    "scanned": "Dùng OCR toàn bộ",
    "image_based": "Dùng OCR toàn bộ",
    "mixed": "Native cho trang text, OCR cho trang còn lại",
}


@dataclass
class AnalysisResult:
    pdf_type: str
    confidence: float
    page_count: int
    pages_needing_ocr: list[int]
    has_encoding_issues: bool
    is_complex_layout: bool
    title: Optional[str]
    processing_time_ms: int
    recommendation: str

    @classmethod
    def from_pdf_result(cls, result: pdf_inspector.PdfResult) -> "AnalysisResult":
        return cls(
            pdf_type=result.pdf_type,
            confidence=result.confidence,
            page_count=result.page_count,
            pages_needing_ocr=list(result.pages_needing_ocr),
            has_encoding_issues=result.has_encoding_issues,
            is_complex_layout=result.is_complex_layout,
            title=result.title,
            processing_time_ms=result.processing_time_ms,
            recommendation=_RECOMMENDATIONS.get(result.pdf_type, ""),
        )


def analyze_pdf(path: str | Path) -> AnalysisResult:
    try:
        result = pdf_inspector.process_pdf(str(path))
    except Exception as exc:
        raise PdfReadError(f"Không thể đọc PDF {path}: {exc}") from exc
    return AnalysisResult.from_pdf_result(result)


def extract_pages(path: str | Path) -> tuple[list[PageResult], AnalysisResult]:
    analysis = analyze_pdf(path)
    try:
        result = pdf_inspector.extract_pages_markdown(str(path))
    except Exception as exc:
        raise PdfReadError(f"Không thể trích xuất PDF {path}: {exc}") from exc

    ocr_pages = set(result.pages_needing_ocr)
    pages: list[PageResult] = []
    for page in result.pages:
        if page.needs_ocr:
            ocr_pages.add(page.page + 1)
        pages.append(
            PageResult(
                page=page.page,
                markdown=page.markdown or "",
                needs_ocr=page.needs_ocr,
                ocr_reason=page.ocr_reason,
                source="native",
            )
        )

    analysis.pages_needing_ocr = sorted(ocr_pages)
    return pages, analysis
