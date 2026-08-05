"""Harness approval test cho output CLI.

Golden nằm trong ``tests/golden/cli/{name}.approved.txt``. Khi output
lệch, test ghi ``{name}.actual.txt`` cạnh file approved rồi fail, nên lúc nào
cũng có thể so hai file để biết đã đổi cái gì.

Quy trình duyệt golden mới: xem ``{name}.actual.txt``, nếu đúng ý thì đổi tên
thành ``{name}.approved.txt``.
"""

from __future__ import annotations

import re
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden" / "cli"

# format_elapsed() tra "12s" hoac "2m15s"; TimeElapsedColumn cua Rich tra "0:00:01".
_ELAPSED_RE = re.compile(r"\b\d+m\d+s\b|\b\d+s\b")
_CLOCK_RE = re.compile(r"\b\d+:\d{2}:\d{2}\b")


def normalize_cli_output(text: str) -> str:
    """Bỏ phần đổi theo từng lần chạy khỏi output CLI.

    Chỉ còn hai nguồn nhiễu cần xử lý: thời gian chạy, và khoảng trắng Rich đệm
    cuối dòng cho đủ chiều rộng console. Đường dẫn không cần chuẩn hoá vì test
    chuyển thư mục làm việc vào ``tmp_path`` rồi dùng tên file tương đối ngắn -
    đường dẫn tuyệt đối dài sẽ bị Rich ngắt giữa dòng, khiến mọi phép thay chuỗi
    trở nên vô dụng.
    """
    text = _CLOCK_RE.sub("<TIME>", text)
    text = _ELAPSED_RE.sub("<ELAPSED>", text)
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def assert_golden(name: str, text: str) -> None:
    """So ``text`` với golden đã duyệt, ghi file ``.actual.txt`` khi lệch."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    approved_path = GOLDEN_DIR / f"{name}.approved.txt"
    actual_path = GOLDEN_DIR / f"{name}.actual.txt"

    if not approved_path.is_file():
        actual_path.write_text(text, encoding="utf-8")
        raise AssertionError(
            f"Chưa có golden cho {name!r}. Đã ghi {actual_path}. "
            f"Kiểm tra rồi đổi tên thành {approved_path.name} để duyệt."
        )

    approved = approved_path.read_text(encoding="utf-8")
    if text != approved:
        actual_path.write_text(text, encoding="utf-8")
        raise AssertionError(
            f"Output CLI lệch golden {name!r}.\n"
            f"approved: {approved_path}\nactual:   {actual_path}\n"
            "Nếu đổi là cố ý thì thay file approved bằng file actual."
        )

    if actual_path.exists():
        actual_path.unlink()
