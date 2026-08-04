from pathlib import Path

import pytest

from smart_pdf2md.config import Options
from smart_pdf2md.errors import OcrBackendError
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.surya_backend import (
    SuryaBackend,
    html_to_markdown,
)


def test_html_to_markdown_heading_bold_italic_underline():
    html = "<p><b><u>BỘ TÀI CHÍNH</u></b></p><p><b>CỘNG HOÀ</b> <i>việt nam</i></p>"
    assert "BỘ TÀI CHÍNH" in html_to_markdown(html)
    assert "**" in html_to_markdown(html)
    assert "*" in html_to_markdown(html)


def test_html_to_markdown_br_becomes_newline():
    assert html_to_markdown("<p>Dòng 1<br/>Dòng 2</p>") == "Dòng 1\nDòng 2"


def test_html_to_markdown_table_cells():
    html = "<table><tr><td>A</td><td>B</td></tr></table>"
    md = html_to_markdown(html)
    assert "A" in md
    assert "B" in md
    assert "|" in md


def test_html_to_markdown_multiple_paragraphs_separated():
    md = html_to_markdown("<p>Đoạn một.</p><p>Đoạn hai.</p>")
    assert "Đoạn một." in md
    assert "Đoạn hai." in md


def test_html_to_markdown_empty():
    assert html_to_markdown("") == ""


def test_surya_backend_missing_binary_raises(monkeypatch, tmp_path):
    class FakePath(type(Path())):
        def is_file(self):
            return False

    monkeypatch.delenv("LLAMA_CPP_BINARY", raising=False)
    monkeypatch.delenv("SURYA_INFERENCE_URL", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr("smart_pdf2md.ocr.surya_backend.Path", FakePath)

    backend = SuryaBackend()
    page = PageResult(page=0, markdown="")
    with pytest.raises(OcrBackendError, match="llama-server"):
        backend.ocr_pages([page], str(tmp_path / "x.pdf"), Options(show_progress=False))