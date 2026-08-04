import os
from pathlib import Path

import pytest

from smart_pdf2md import convert_full
from smart_pdf2md.errors import OcrBackendError

FIXTURES = os.path.join("tests", "fixtures", "input")
THONG_TU = os.path.join(FIXTURES, "Thông-tư-89-2026-TT-BTC.pdf")

pytestmark = pytest.mark.skipif(
    not os.environ.get("PDF2MD_OCR_E2E"),
    reason="E2E OCR test cần llama-server đang chạy. Set PDF2MD_OCR_E2E=1 và SURYA_INFERENCE_URL=...",
)


@pytest.mark.skipif(not os.path.exists(THONG_TU), reason="thiếu fixture")
def test_ocr_merge_native_and_ocr(tmp_path):
    out = tmp_path / "mixed.md"
    result = convert_full(
        THONG_TU,
        output=out,
        pages=[1, 2],
        show_progress=False,
        dpi=150,
    )
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "<!-- Page 1 -->" in content
    assert "<!-- Page 2 -->" in content
    assert len(result.pages) == 2
    assert result.pages[0].source == "native"
    assert result.pages[1].source == "ocr"
    assert len(result.pages[1].markdown) > 500


def test_missing_server_raises_clear_error(monkeypatch):
    monkeypatch.delenv("SURYA_INFERENCE_URL", raising=False)
    monkeypatch.delenv("LLAMA_CPP_BINARY", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    from smart_pdf2md.ocr.surya_backend import SuryaBackend
    from smart_pdf2md.models import PageResult
    from smart_pdf2md.config import Options

    class FakePath(type(Path())):
        def is_file(self):
            return False

    monkeypatch.setattr("smart_pdf2md.ocr.surya_backend.Path", FakePath)
    with pytest.raises(OcrBackendError):
        SuryaBackend().ocr_pages(
            [PageResult(page=0, markdown="")],
            "x.pdf",
            Options(show_progress=False),
        )
