from abc import ABC, abstractmethod
from typing import Optional

from smart_pdf2md.config import Options
from smart_pdf2md.errors import OcrBackendError
from smart_pdf2md.models import PageResult


class OcrBackend(ABC):
    name: str = ""

    @abstractmethod
    def ocr_pages(
        self,
        pages: list[PageResult],
        pdf_path: str,
        options: Options,
        on_page_done=None,
    ) -> dict[int, str]:
        raise NotImplementedError


def get_ocr_backend(name: str) -> OcrBackend:
    if name == "surya":
        try:
            from smart_pdf2md.ocr.surya_backend import SuryaBackend
        except ImportError as exc:
            raise OcrBackendError(
                "OCR backend 'surya' chưa sẵn sàng. Chạy 'uv add surya-ocr' "
                "và làm theo docs/INSTALL.md (cần llama.cpp hoặc vllm)."
            ) from exc
        return SuryaBackend()
    raise OcrBackendError(f"OCR backend không hỗ trợ: {name!r}")