from pathlib import Path
import sys
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from smart_pdf2md import __version__
from smart_pdf2md.classifier import analyze_pdf
from smart_pdf2md.converter import convert_full
from smart_pdf2md.errors import Pdf2MdError

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

app = typer.Typer(
    help="Smart PDF to Markdown — pdf-inspector + Surya local OCR (100% offline)",
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
    ocr_backend: Annotated[str, typer.Option("--ocr-backend", help="Backend OCR (surya)")] = "surya",
    page: Annotated[
        Optional[str],
        typer.Option("--page", help="Chỉ xử lý các trang, ví dụ: 1-5,7,10"),
    ] = None,
    poppler_path: Annotated[
        Optional[Path],
        typer.Option("--poppler-path", help="Thư mục chứa binary poppler (pdftoppm)"),
    ] = None,
    version: Annotated[bool, typer.Option("--version", help="Hiển thị phiên bản")] = False,
) -> None:
    if version:
        console.print(f"pdf2md-smart v{__version__}")
        raise typer.Exit(0)

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

    selected_pages = _parse_pages(page) if page else None

    exit_code = 0
    for path in paths:
        try:
            if not quiet:
                console.print(f"[bold]→[/bold] Đang phân tích PDF bằng pdf-inspector: [cyan]{path}[/cyan]")
            target = str(output) if output is not None else None
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
            )
            if quiet:
                err_console.print(f"OK: {target or '<stdout>'}")
                continue
            console.print(
                f"[bold]→[/bold] PDF type: [yellow]{result.pdf_type}[/yellow] | "
                f"Confidence: [yellow]{result.confidence:.2f}[/yellow] | "
                f"Total pages: [yellow]{result.page_count}[/yellow] | "
                f"Pages need OCR: [yellow]{_format_ocr_pages(result.pages_needing_ocr)}[/yellow]"
            )
            if target is None:
                console.print(result.markdown)
            else:
                console.print(f"✅ Đã lưu: [bold green]{target}[/bold green] ({result.page_count} trang)")
        except (Pdf2MdError, OSError) as exc:
            err_console.print(f"[red]Lỗi:[/red] {exc}")
            exit_code = 1

    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()
