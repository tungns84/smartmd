"""Golden master cho output CLI.

Đây là lưới an toàn cho việc refactor core: mọi thay đổi bên trong pipeline phải
giữ nguyên từng ký tự CLI in ra. Test này phải xanh TRƯỚC khi sửa ``src/``, và
phải còn xanh sau khi phần trình bày được rút ra khỏi ``converter.py``.

Chia hai loại có chủ ý:

- Đường ``text_based`` chạy PDF thật và classifier thật, khoá luôn định dạng
  dòng phân tích và dòng lưu file.
- Đường OCR thay ``extract_pages`` và backend bằng đồ giả, nên nhanh và không
  phụ thuộc nội dung PDF, nhưng vẫn đi qua đúng code trình bày cần khoá.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import rich.console
from typer.testing import CliRunner

from smart_pdf2md import cli as cli_mod
from smart_pdf2md import converter as conv
from smart_pdf2md import progress as progress_mod
from smart_pdf2md.cli import app
from smart_pdf2md.models import PageResult

from fakes import FakeOcrBackend, make_analysis, make_extract_pages
from golden import assert_golden, normalize_cli_output

TEXT_PDF = Path(__file__).parent / "fixtures" / "input" / "WB-1.pdf"
GOLDEN_WIDTH = 100

runner = CliRunner()


@pytest.fixture(autouse=True)
def pinned_console_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ghim hình dạng console để golden không phụ thuộc môi trường chạy.

    Biến ``COLUMNS`` không đủ, và cả bốn tham số dưới đây đều cần thiết, mỗi cái
    chặn một nguồn nhiễu đã đo được:

    - ``width`` một mình vô tác dụng: Rich chỉ dùng chiều rộng đã set khi CẢ
      ``width`` và ``height`` có giá trị, nếu không nó rơi xuống dò kích thước
      terminal và cho ra 80.
    - ``legacy_windows`` phải tắt, vì Rich trừ 1 cột khi phát hiện console
      Windows kiểu cũ, làm Windows ra 99 còn Linux ra 100.
    - ``force_terminal`` phải tắt, để biến môi trường như ``FORCE_COLOR`` không
      bật mã ANSI vào output.
    """
    original = rich.console.Console

    class PinnedConsole(original):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("width", GOLDEN_WIDTH)
            kwargs.setdefault("height", 50)
            kwargs.setdefault("legacy_windows", False)
            kwargs.setdefault("force_terminal", False)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(rich.console, "Console", PinnedConsole)
    # converter.py het import Console sau Cycle 3, nen raising=False.
    monkeypatch.setattr(progress_mod, "Console", PinnedConsole, raising=False)
    monkeypatch.setattr(conv, "Console", PinnedConsole, raising=False)
    monkeypatch.setattr(cli_mod, "Console", PinnedConsole, raising=False)
    monkeypatch.setattr(cli_mod, "console", PinnedConsole(highlight=False))
    monkeypatch.setattr(
        cli_mod, "err_console", PinnedConsole(stderr=True, highlight=False)
    )


@pytest.fixture
def work_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chuyển cwd vào ``tmp_path`` để mọi đường dẫn trên output đều ngắn."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def text_doc(work_dir: Path) -> str:
    """Bản sao PDF ``text_based`` với tên ngắn, tương đối so với cwd."""
    if not TEXT_PDF.is_file():
        pytest.skip("thiếu fixture WB-1.pdf")
    shutil.copyfile(TEXT_PDF, work_dir / "doc.pdf")
    return "doc.pdf"


@pytest.fixture
def scan_doc(work_dir: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """PDF giả cộng pipeline giả, để khoá phần trình bày của đường OCR."""
    (work_dir / "scan.pdf").write_bytes(b"%PDF-golden-contract")
    pages = [
        PageResult(page=0, markdown="Trang mot co san noi dung native " * 6, needs_ocr=False),
        PageResult(page=1, markdown="", needs_ocr=True),
        PageResult(page=2, markdown="", needs_ocr=True),
    ]
    analysis = make_analysis(
        pdf_type="mixed", page_count=3, pages_needing_ocr=[2, 3], confidence=0.5
    )
    monkeypatch.setattr(conv, "extract_pages", make_extract_pages(pages, analysis))
    monkeypatch.setattr(
        conv,
        "get_ocr_backend",
        lambda name: FakeOcrBackend(usage=(2500, 1200, 0.0042)),
    )
    return "scan.pdf"


def test_console_shape_is_pinned() -> None:
    """Bảo vệ giả định của mọi golden bên dưới.

    Nếu bản Rich mới đổi cách suy ra chiều rộng, test này fail thẳng vào nguyên
    nhân thay vì để năm golden cùng lệch vì lý do không rõ ràng.
    """
    assert cli_mod.console.width == GOLDEN_WIDTH
    assert cli_mod.console.is_terminal is False


def test_text_based_convert_to_file_output_contract(text_doc: str) -> None:
    result = runner.invoke(app, [text_doc, "-o", "out.md"])
    assert result.exit_code == 0
    assert_golden("text_based_to_file", normalize_cli_output(result.stdout))


def test_analyze_table_output_contract(text_doc: str) -> None:
    result = runner.invoke(app, [text_doc, "--analyze"])
    assert result.exit_code == 0
    assert_golden("analyze_table", normalize_cli_output(result.stdout))


def test_quiet_mode_output_contract(text_doc: str) -> None:
    result = runner.invoke(app, [text_doc, "-o", "out.md", "--quiet"])
    assert result.exit_code == 0
    assert_golden("quiet_stdout", normalize_cli_output(result.stdout))
    assert_golden("quiet_stderr", normalize_cli_output(result.stderr))


def test_ocr_path_output_contract(scan_doc: str) -> None:
    result = runner.invoke(app, [scan_doc, "-o", "out.md"])
    assert result.exit_code == 0
    assert_golden("ocr_first_run", normalize_cli_output(result.stdout))


def test_ocr_path_resume_from_cache_output_contract(scan_doc: str) -> None:
    first = runner.invoke(app, [scan_doc, "-o", "one.md"])
    assert first.exit_code == 0

    second = runner.invoke(app, [scan_doc, "-o", "two.md"])
    assert second.exit_code == 0
    assert_golden("ocr_resume_from_cache", normalize_cli_output(second.stdout))
