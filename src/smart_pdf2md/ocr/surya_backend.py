from html.parser import HTMLParser
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from smart_pdf2md.config import Options
from smart_pdf2md.errors import OcrBackendError
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.base import OcrBackend
from smart_pdf2md.render import render_pages

_CHUNK_SIZE = 8

_INSTALL_MSG = (
    "Không tìm thấy llama-server (Surya 2 cần inference backend). "
    "Cài đặt theo docs/INSTALL.md: tải release từ ggml-org/llama.cpp, "
    "rồi đặt 'tools/llama.cpp/llama-server.exe' trong project, "
    "hoặc set env LLAMA_CPP_BINARY, hoặc set SURYA_INFERENCE_URL "
    "trỏ tới llama-server/vllm đang chạy."
)

_EMPHASIS_CLOSE = {"b": "**", "strong": "**", "i": "*", "em": "*", "u": "__"}
_HEADING = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


class _HtmlToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._in_table = False
        self._list_item_open = False

    def _newline(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("p", "div", "tr"):
            self._newline()
            if self._in_table:
                self.parts.append("\n")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._newline()
            self.parts.append("#" * _HEADING[tag] + " ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag in _EMPHASIS_CLOSE:
            self.parts.append(_EMPHASIS_CLOSE[tag])
        elif tag == "li":
            self._newline()
            self.parts.append("- ")
        elif tag in ("td", "th"):
            self.parts.append("| ")
        elif tag == "table":
            self._in_table = True
        elif tag == "ul":
            self._newline()

    def handle_endtag(self, tag: str) -> None:
        if tag in _EMPHASIS_CLOSE:
            self.parts.append(_EMPHASIS_CLOSE[tag])
        elif tag in ("p", "div", "li"):
            self._newline()
        elif tag == "table":
            self._in_table = False
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._in_table:
            self.parts.append(data.strip())
        else:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [line.strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def html_to_markdown(html: str) -> str:
    parser = _HtmlToMarkdown()
    parser.feed(html)
    return parser.text()


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


class SuryaBackend(OcrBackend):
    name = "surya"

    def _resolve_binary(self) -> None:
        if os.environ.get("SURYA_INFERENCE_URL"):
            return
        # Surya's own atexit cleanup (`_stop_process`) can hang forever on
        # Windows when the interpreter shuts down (the SIGTERM poll loop relies
        # on `os.kill(pid, 0)` raising ProcessLookupError, which never happens
        # after TerminateProcess). Keep the spawned llama-server alive and tear
        # it down ourselves via `taskkill`, which runs outside this process.
        os.environ.setdefault("SURYA_INFERENCE_KEEP_ALIVE", "1")
        binary = os.environ.get("LLAMA_CPP_BINARY")
        candidates: list[str] = []
        if binary:
            candidates.append(binary)
        repo = Path(__file__).resolve().parents[3]
        candidates.append(str(Path.cwd() / "tools" / "llama.cpp" / "llama-server.exe"))
        candidates.append(str(repo / "tools" / "llama.cpp" / "llama-server.exe"))

        resolved = next((c for c in candidates if Path(c).is_file()), None)
        if resolved is None and shutil.which("llama-server"):
            return
        if resolved is None:
            raise OcrBackendError(_INSTALL_MSG)
        from surya.settings import settings

        settings.LLAMA_CPP_BINARY = resolved
        os.environ["LLAMA_CPP_BINARY"] = resolved

    @staticmethod
    def _cleanup_spawned_server() -> None:
        """Kill the llama-server we spawned and drop the sentinel.

        With SURYA_INFERENCE_KEEP_ALIVE=1 surya never registers its atexit
        cleanup, so we must stop the server ourselves. taskkill runs outside
        this process, avoiding the Windows interpreter-exit hang.
        """
        if os.environ.get("SURYA_INFERENCE_URL"):
            return
        sentinel = Path.home() / ".cache" / "datalab" / "surya" / "llamacpp_server.json"
        if not sentinel.exists():
            return
        try:
            data = json.loads(sentinel.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        pid = data.get("pid")
        if pid:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=30,
                )
            else:
                try:
                    os.kill(int(pid), 15)
                except (ProcessLookupError, PermissionError, ValueError):
                    pass
        try:
            sentinel.unlink()
        except OSError:
            pass

    def ocr_pages(
        self,
        pages: list[PageResult],
        pdf_path: str,
        options: Options,
        on_page_done=None,
    ) -> dict[int, str]:
        if not pages:
            return {}
        self._resolve_binary()
        try:
            from surya.recognition import RecognitionPredictor
        except ImportError as exc:
            raise OcrBackendError("surya-ocr chưa được cài. Chạy 'uv add surya-ocr'.") from exc

        try:
            return self._run_ocr(
                RecognitionPredictor, pages, pdf_path, options, on_page_done
            )
        finally:
            self._cleanup_spawned_server()

    def _run_ocr(
        self,
        predictor_cls,
        pages: list[PageResult],
        pdf_path: str,
        options: Options,
        on_page_done=None,
    ) -> dict[int, str]:
        predictor = predictor_cls()
        target_pages = sorted(p.page + 1 for p in pages)
        results: dict[int, str] = {}

        for chunk in _chunks(target_pages, _CHUNK_SIZE):
            images = render_pages(
                pdf_path,
                chunk,
                dpi=options.dpi,
                poppler_path=options.poppler_path,
            )
            ordered_pages = sorted(images)
            ordered_images = [images[n] for n in ordered_pages]
            try:
                outputs = predictor(ordered_images, full_page=True)
            except Exception as exc:
                raise OcrBackendError(
                    f"Lỗi khi OCR qua Surya: {exc}. "
                    "Kiểm tra llama-server đang chạy (xem docs/INSTALL.md)."
                ) from exc
            for page_number, output in zip(ordered_pages, outputs):
                html = "".join(block.html for block in output.blocks if block.html)
                markdown = html_to_markdown(html)
                results[page_number] = markdown
                if on_page_done is not None:
                    on_page_done(page_number, len(markdown))

        return results