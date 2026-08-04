from pathlib import Path

import pytest
from typer.testing import CliRunner

from smart_pdf2md.cli import app

FIXTURES = Path(__file__).parent / "fixtures" / "input"
runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "v0.1.0" in result.stdout


def test_cli_analyze_text_based():
    result = runner.invoke(app, [str(FIXTURES / "WB-1.pdf"), "--analyze"])
    assert result.exit_code == 0
    assert "text_based" in result.stdout
    assert "8" in result.stdout


def test_cli_analyze_mixed():
    result = runner.invoke(app, [str(FIXTURES / "Thông-tư-89-2026-TT-BTC.pdf"), "--analyze"])
    assert result.exit_code == 0
    assert "Total pages" in result.stdout


def test_cli_convert_writes_file(tmp_path):
    out = tmp_path / "ket-qua.md"
    result = runner.invoke(app, [str(FIXTURES / "WB-1.pdf"), "-o", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "<!-- Page 1 -->" in content
    assert "Thời lượng" in content


def test_cli_convert_stdout():
    result = runner.invoke(app, [str(FIXTURES / "WB-1.pdf")])
    assert result.exit_code == 0
    assert "<!-- Page 1 -->" in result.stdout


def test_cli_missing_file(tmp_path):
    result = runner.invoke(app, [str(tmp_path / "none.pdf"), "--analyze"])
    assert result.exit_code == 1
    assert "Lỗi" in result.stderr


def test_cli_no_input():
    result = runner.invoke(app, [])
    assert result.exit_code == 2