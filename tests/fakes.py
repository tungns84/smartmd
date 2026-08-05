"""Test double dùng chung cho nhiều test module.

Mục đích là có OCR deterministic, không gọi mạng, không tốn tiền, để test được
phần trình bày và phần điều phối của pipeline.
"""

from __future__ import annotations

from typing import Callable, Optional

from smart_pdf2md.classifier import AnalysisResult
from smart_pdf2md.events import ConversionEvent
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.base import OcrBackend


class RecordingListener:
    """Gom mọi ConversionEvent vào ``events`` để assert thứ tự."""

    def __init__(self) -> None:
        self.events: list[ConversionEvent] = []
        self.closed = False

    def emit(self, event: ConversionEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        self.closed = True

    def of_type(self, cls: type) -> list[ConversionEvent]:
        return [e for e in self.events if isinstance(e, cls)]


class FakeOcrBackend(OcrBackend):
    """OCR backend trả markdown đóng hộp và ghi lại lời gọi.

    ``calls`` cho biết mỗi lượt ``ocr_pages`` nhận những trang nào, nhờ đó test
    khẳng định được trang nào thật sự đi OCR thay vì lấy từ cache.

    ``usage`` mô phỏng ``consume_usage()`` của backend OpenCode để test được dòng
    chi phí trên CLI. Để ``None`` thì coi như không có token nào.
    """

    name = "fake"

    def __init__(
        self,
        *,
        template: str = "Noi dung OCR trang {page}",
        usage: Optional[tuple[int, int, Optional[float]]] = None,
    ) -> None:
        self.template = template
        self.calls: list[list[int]] = []
        self.started: list[tuple[int, int]] = []
        self._usage = usage

    def ocr_pages(
        self,
        pages,
        pdf_path,
        options,
        on_page_done=None,
        on_page_start=None,
        *,
        listener=None,
    ) -> dict[int, str]:
        self.calls.append([p.page + 1 for p in pages])
        results: dict[int, str] = {}
        for index, page in enumerate(pages, start=1):
            number = page.page + 1
            if on_page_start is not None:
                on_page_start(number, index)
            self.started.append((number, index))
            markdown = self.template.format(page=number)
            results[number] = markdown
            if on_page_done is not None:
                on_page_done(number, len(markdown), markdown)
        return results

    def consume_usage(self) -> tuple[int, int, Optional[float]]:
        if self._usage is None:
            return 0, 0, None
        usage, self._usage = self._usage, None
        return usage


def make_analysis(
    *,
    pdf_type: str = "scanned",
    page_count: int = 2,
    pages_needing_ocr: Optional[list[int]] = None,
    confidence: float = 0.9,
    title: Optional[str] = None,
    has_encoding_issues: bool = False,
    processing_time_ms: int = 1,
) -> AnalysisResult:
    """AnalysisResult tối giản cho test, các trang OCR là 1-indexed."""
    return AnalysisResult(
        pdf_type=pdf_type,
        confidence=confidence,
        page_count=page_count,
        pages_needing_ocr=list(pages_needing_ocr or []),
        has_encoding_issues=has_encoding_issues,
        is_complex_layout=False,
        title=title,
        processing_time_ms=processing_time_ms,
        recommendation="",
    )


def make_extract_pages(
    pages: list[PageResult],
    analysis: AnalysisResult,
) -> Callable[[object], tuple[list[PageResult], AnalysisResult]]:
    """Trả hàm thay thế ``converter.extract_pages``, bỏ qua đường dẫn đầu vào.

    Mỗi lần gọi trả bản sao mới của ``pages`` vì ``convert_full`` ghi trực tiếp
    lên ``PageResult.markdown`` và ``.source``, nếu dùng chung object thì lần
    chạy thứ hai sẽ thấy trạng thái của lần đầu.
    """

    def _extract(_path):
        fresh = [
            PageResult(
                page=p.page,
                markdown=p.markdown,
                needs_ocr=p.needs_ocr,
                ocr_reason=p.ocr_reason,
                source=p.source,
            )
            for p in pages
        ]
        return fresh, analysis

    return _extract
