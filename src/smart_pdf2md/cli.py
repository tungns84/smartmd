from pathlib import Path
import sys
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from smart_pdf2md import __version__
from smart_pdf2md.classifier import analyze_pdf
from smart_pdf2md.converter import convert_full, format_elapsed
from smart_pdf2md.env import get_vlm_model, load_app_env
from smart_pdf2md.errors import Pdf2MdError
from smart_pdf2md.events import FanOutListener
from smart_pdf2md.quality import ReportCollector, build_report, write_report

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

load_app_env()

app = typer.Typer(
    help="Smart PDF to Markdown — pdf-inspector + OpenCode Go VLM (PaddleOCR offline)",
    no_args_is_help=True,
)
console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)


def _parse_pages(spec: str) -> list[int]:
    pages: set[int] = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_str, _, end_str = token.partition("-")
            try:
                start, end = int(start_str), int(end_str)
            except ValueError:
                raise typer.Exit(2)
            if start < 1 or end < start:
                raise typer.Exit(2)
            pages.update(range(start, end + 1))
        else:
            try:
                pages.add(int(token))
            except ValueError:
                raise typer.Exit(2)
    if not pages:
        raise typer.Exit(2)
    return sorted(pages)


def _format_ocr_pages(pages: list[int]) -> str:
    if len(pages) <= 20:
        return str(pages)
    head = ", ".join(str(p) for p in pages[:10])
    return f"[{head}, ... {len(pages)} trang]"


def _format_ocr_cost_note(result) -> str:
    if not (result.ocr_input_tokens or result.ocr_output_tokens):
        return ""
    tok = (
        f"in {_format_token_count(result.ocr_input_tokens)} / "
        f"out {_format_token_count(result.ocr_output_tokens)}"
    )
    if result.ocr_cost_usd is not None:
        return f" | ~${result.ocr_cost_usd:.4f} ({tok})"
    return f" | {tok}"


def _format_token_count(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _print_analysis(path: str, quiet: bool) -> None:
    result = analyze_pdf(path)
    if quiet:
        err_console.print(
            f"PDF type: {result.pdf_type} | Confidence: {result.confidence:.2f} | "
            f"Pages: {result.page_count} | OCR pages: {_format_ocr_pages(result.pages_needing_ocr)}"
        )
        return
    table = Table(title=str(path), show_header=False)
    table.add_column("Hạng mục", style="cyan", no_wrap=True)
    table.add_column("Giá trị")
    table.add_row("PDF type", result.pdf_type)
    table.add_row("Confidence", f"{result.confidence:.2f}")
    table.add_row("Total pages", str(result.page_count))
    table.add_row("Pages need OCR", _format_ocr_pages(result.pages_needing_ocr))
    table.add_row("Encoding issues", str(result.has_encoding_issues))
    table.add_row("Recommendation", result.recommendation)
    console.print(table)


@app.command()
def main(
    input_path: Annotated[
        Optional[list[Path]],
        typer.Argument(help="Một hoặc nhiều file PDF", show_default=False),
    ] = None,
    output: Annotated[
        Optional[Path], typer.Option("--output", "-o", help="File Markdown đầu ra")
    ] = None,
    languages: Annotated[str, typer.Option("--lang", help="Ngôn ngữ ưu tiên, ví dụ: vi,en")] = "vi,en",
    dpi: Annotated[int, typer.Option("--dpi", help="DPI khi render trang cho OCR")] = 200,
    analyze: Annotated[bool, typer.Option("--analyze", help="Chỉ phân loại, không convert")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", help="Chế độ im lặng")] = False,
    compact: Annotated[bool, typer.Option("--compact", help="Nén markdown (bỏ dòng trống thừa)")] = False,
    force_ocr: Annotated[bool, typer.Option("--force-ocr", help="Ép OCR toàn bộ")] = False,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help="Tắt đọc/ghi cache OCR (mặc định: resume từ cache khi chạy lại)",
        ),
    ] = False,
    ocr_backend: Annotated[
        str, typer.Option("--ocr-backend", help="Backend OCR (opencode|paddleocr)")
    ] = "opencode",
    vlm_model: Annotated[
        Optional[str],
        typer.Option(
            "--vlm-model",
            help="Model OpenCode Go VLM (mặc định từ .env / OPENCODE_VLM_MODEL)",
        ),
    ] = None,
    page: Annotated[
        Optional[str],
        typer.Option("--page", help="Chỉ xử lý các trang, ví dụ: 1-5,7,10"),
    ] = None,
    poppler_path: Annotated[
        Optional[Path],
        typer.Option("--poppler-path", help="Thư mục chứa binary poppler (pdftoppm)"),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Exit khác 0 khi có trang OCR rỗng hoặc lỗi",
        ),
    ] = False,
    no_strip_headers: Annotated[
        bool,
        typer.Option(
            "--no-strip-headers",
            help="Không xoá running header/footer lặp lại giữa các trang",
        ),
    ] = False,
    concurrency: Annotated[
        int,
        typer.Option(
            "--concurrency",
            help="Số luồng OCR song song trong mỗi lô render (mặc định 4)",
        ),
    ] = 4,
    report: Annotated[
        Optional[Path],
        typer.Option("--report", help="Ghi báo cáo chất lượng JSON ra file"),
    ] = None,
    version: Annotated[bool, typer.Option("--version", help="Hiển thị phiên bản")] = False,
) -> None:
    if version:
        console.print(f"pdf2md-smart v{__version__}")
        raise typer.Exit(0)

    load_app_env()
    resolved_vlm_model = vlm_model or get_vlm_model()

    lang_list = [lang.strip() for lang in languages.split(",") if lang.strip()]
    paths = list(input_path or [])
    if not paths and not version:
        err_console.print("Cần ít nhất một file PDF")
        raise typer.Exit(2)

    if analyze:
        for path in paths:
            try:
                _print_analysis(str(path), quiet)
            except Pdf2MdError as exc:
                err_console.print(f"[red]Lỗi:[/red] {exc}")
                raise typer.Exit(1)
        return

    if len(paths) > 1 and output is not None:
        err_console.print("--output chỉ dùng được khi convert 1 file")
        raise typer.Exit(2)

    if concurrency < 1:
        err_console.print("--concurrency phải >= 1")
        raise typer.Exit(2)

    selected_pages = _parse_pages(page) if page else None

    exit_code = 0
    for path in paths:
        try:
            if not quiet:
                console.print(f"[bold]→[/bold] Đang phân tích PDF bằng pdf-inspector: [cyan]{path}[/cyan]")
            target = str(output) if output is not None else None
            report_collector: ReportCollector | None = None
            listener = None
            if report is not None:
                report_collector = ReportCollector()
                if not quiet:
                    from smart_pdf2md.progress import RichConversionListener

                    listener = FanOutListener(
                        RichConversionListener(), report_collector
                    )
                else:
                    listener = report_collector
            result = convert_full(
                str(path),
                output=target,
                languages=lang_list,
                dpi=dpi,
                compact=compact,
                force_ocr=force_ocr,
                show_progress=not quiet,
                pages=selected_pages,
                ocr_backend=ocr_backend,
                poppler_path=str(poppler_path) if poppler_path else None,
                vlm_model=resolved_vlm_model,
                use_cache=not no_cache,
                strip_headers=not no_strip_headers,
                concurrency=concurrency,
                listener=listener,
            )
            failed_pages = [
                p.page + 1 for p in result.pages if p.ocr_error
            ]
            if result.empty_pages or failed_pages:
                warn_bits = []
                if result.empty_pages:
                    warn_bits.append(
                        f"{len(result.empty_pages)} trang rỗng "
                        f"({_format_ocr_pages(result.empty_pages)})"
                    )
                if failed_pages:
                    warn_bits.append(
                        f"{len(failed_pages)} trang lỗi "
                        f"({_format_ocr_pages(failed_pages)})"
                    )
                msg = " | ".join(warn_bits)
                if quiet:
                    err_console.print(f"WARN: {msg}")
                else:
                    err_console.print(f"[yellow]![/] Cảnh báo OCR: {msg}")
                if strict:
                    exit_code = 1

            if report is not None and report_collector is not None:
                quality = build_report(result, report_collector)
                write_report(report, quality)
                if not quiet and quality.issue_count:
                    console.print(
                        f"[bold]→[/bold] Quality report: [yellow]{quality.issue_count}[/yellow] "
                        f"issues → [cyan]{report}[/cyan]"
                    )
                elif not quiet:
                    console.print(
                        f"[bold]→[/bold] Quality report: không phát hiện issue → [cyan]{report}[/cyan]"
                    )

            if quiet:
                err_console.print(f"OK: {target or '<stdout>'}")
                continue
            if target is None:
                console.print(result.markdown)
            else:
                cache_note = ""
                if result.cache_hits or result.cache_misses:
                    cache_note = (
                        f" | cache {result.cache_hits} hit / {result.cache_misses} miss"
                    )
                cost_note = _format_ocr_cost_note(result)
                console.print(
                    f"✅ Đã lưu: [bold green]{target}[/bold green] "
                    f"({result.page_count} trang) — {format_elapsed(result.elapsed_ms)}"
                    f"{cache_note}{cost_note}"
                )

        except (Pdf2MdError, OSError) as exc:
            err_console.print(f"[red]Lỗi:[/red] {exc}")
            exit_code = 1

    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()
