from abc import ABC, abstractmethod

from smart_pdf2md.config import Options
from smart_pdf2md.errors import OcrBackendError
from smart_pdf2md.models import PageResult


def notify_page_done(on_page_done, page: int, markdown: str) -> None:
    """Call ``on_page_done(page, char_count[, markdown])`` with 2- or 3-arg callbacks."""
    if on_page_done is None:
        return
    try:
        on_page_done(page, len(markdown), markdown)
    except TypeError:
        on_page_done(page, len(markdown))


class OcrBackend(ABC):
    name: str = ""

    @abstractmethod
    def ocr_pages(
        self,
        pages: list[PageResult],
        pdf_path: str,
        options: Options,
        on_page_done=None,
        on_page_start=None,
        *,
        listener=None,
    ) -> dict[int, str]:
        raise NotImplementedError


def get_ocr_backend(name: str) -> OcrBackend:
    if name == "opencode":
        from smart_pdf2md.ocr.opencode_backend import OpencodeVlmBackend

        return OpencodeVlmBackend()
    if name == "paddleocr":
        try:
            from smart_pdf2md.ocr.paddleocr_backend import PaddleOcrBackend
        except ImportError as exc:
            raise OcrBackendError(
                "OCR backend 'paddleocr' chưa sẵn sàng. Cài paddlepaddle (CPU) "
                "rồi chạy 'uv sync' (xem docs/INSTALL.md)."
            ) from exc
        return PaddleOcrBackend()
    raise OcrBackendError(f"OCR backend không hỗ trợ: {name!r}")
