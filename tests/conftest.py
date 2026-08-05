"""Fixture dùng chung, cô lập test khỏi trạng thái của máy dev.

Hai nguồn rò rỉ đã được xác nhận gây fail thật:

1. Cache OCR mặc định nằm ở ``%LOCALAPPDATA%\\smart-pdf2md\\cache``. Máy nào đã
   convert fixture rồi thì ``convert_full`` đọc được cache, ``get_ocr_backend``
   không bao giờ được gọi, và test khẳng định backend bị gọi sẽ fail.
2. ``.env`` ở gốc repo được ``load_app_env()`` nạp vào ``os.environ`` ngay lúc
   import ``smart_pdf2md.cli``. Model VLM của lập trình viên vì thế lọt vào
   output CLI, làm test phụ thuộc máy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import smart_pdf2md.env as env_mod

FIXTURES = Path(__file__).parent / "fixtures" / "input"

_OPENCODE_VARS = ("OPENCODE_API_KEY", "OPENCODE_VLM_MODEL", "OPENCODE_BASE_URL")


@pytest.fixture(autouse=True)
def isolate_ocr_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Trỏ cache OCR vào ``tmp_path`` để mỗi test khởi đầu với cache trống."""
    root = tmp_path / "ocr-cache"
    monkeypatch.setenv("PDF2MD_CACHE_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def isolate_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chặn ``.env`` của máy dev, cho mọi test thấy môi trường OpenCode trống.

    ``load_app_env()`` chỉ đọc ``.env`` một lần rồi bật cờ ``_LOADED``. Ép cờ này
    lên ``True`` nên các lần gọi sau là no-op, không nạp lại ``.env`` sau khi
    fixture đã xoá biến. ``tests/test_env.py`` tự đặt ``_LOADED = False`` trong
    thân test nên không bị ảnh hưởng.
    """
    for name in _OPENCODE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(env_mod, "_LOADED", True)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def text_pdf() -> Path:
    """PDF ``text_based`` 8 trang, không trang nào cần OCR."""
    path = FIXTURES / "WB-1.pdf"
    if not path.is_file():
        pytest.skip("thiếu fixture WB-1.pdf")
    return path


@pytest.fixture
def mixed_pdf() -> Path:
    """PDF ``mixed`` có cả trang native và trang cần OCR."""
    path = FIXTURES / "Thông-tư-89-2026-TT-BTC.pdf"
    if not path.is_file():
        pytest.skip("thiếu fixture Thông-tư-89-2026-TT-BTC.pdf")
    return path
