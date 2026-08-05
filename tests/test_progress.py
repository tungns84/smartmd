from smart_pdf2md.converter import format_elapsed
from smart_pdf2md.progress import ocr_progress


def test_ocr_progress_noop_when_hidden():
    with ocr_progress(3, backend="opencode", model="qwen3.6-plus", show=False) as hooks:
        hooks.on_start(1, 1)
        hooks.on_done(1, 10)
        hooks.on_start(2, 2)
        hooks.on_done(2, 20)


def test_ocr_progress_noop_when_total_zero():
    with ocr_progress(0, backend="paddleocr", show=True) as hooks:
        hooks.on_start(1, 1)
        hooks.on_done(1, 5)


def test_ocr_progress_advances_with_show(capsys):
    with ocr_progress(2, backend="opencode", model="qwen3.6-plus", show=True) as hooks:
        hooks.on_start(3, 1)
        hooks.on_done(3, 100)
        hooks.on_start(5, 2)
        hooks.on_done(5, 200)
    captured = capsys.readouterr()
    assert "Page 3" in captured.out
    assert "Page 5" in captured.out
    assert "100" in captured.out


def test_format_elapsed():
    assert format_elapsed(0) == "0s"
    assert format_elapsed(999) == "0s"
    assert format_elapsed(12_000) == "12s"
    assert format_elapsed(135_000) == "2m15s"
