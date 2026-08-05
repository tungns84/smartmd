from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from smart_pdf2md.events import (
    AnalysisDone,
    CacheFinal,
    CacheSummary,
    Completed,
    ConversionEvent,
    FallbackUsed,
    HeadersStripped,
    OcrStarted,
    PageDone,
    PageEmpty,
    PageFailed,
    PageRetry,
    PageStarted,
    format_ocr_pages,
)

# on_page_done(page, char_count[, markdown]) — markdown optional for cache save
PageDoneCallback = Callable[..., None]
PageStartCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class OcrProgressHooks:
    on_start: PageStartCallback
    on_done: PageDoneCallback


def make_progress(show: bool, quiet: bool) -> Optional[Progress]:
    if not show or quiet:
        return None
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}[/]"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=Console(highlight=False),
    )


def add_task(progress: Optional[Progress], description: str, total: int) -> Optional[TaskID]:
    if progress is None:
        return None
    return progress.add_task(description, total=total)


def page_done_callback(quiet: bool, show_progress: bool) -> PageDoneCallback:
    console = Console(highlight=False) if not quiet else Console(quiet=True)

    def _cb(page: int, char_count: int, markdown: str | None = None) -> None:
        if not show_progress:
            return
        console.print(f"  [green]✓[/] Page {page} ({char_count:,} ký tự)")

    return _cb


def _noop_start(page: int, index: int) -> None:
    return None


def _noop_done(page: int, char_count: int, markdown: str | None = None) -> None:
    return None


@contextmanager
def ocr_progress(
    total: int,
    *,
    backend: str,
    model: str | None = None,
    show: bool = True,
) -> Iterator[OcrProgressHooks]:
    """Rich progress bar + page start/done hooks for OCR batches."""
    if not show or total <= 0:
        yield OcrProgressHooks(on_start=_noop_start, on_done=_noop_done)
        return

    console = Console(highlight=False)
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}[/]"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        suffix = f" [{backend}]" if backend else ""
        if model:
            suffix = f" [{backend}:{model}]"
        task_id = progress.add_task(f"OCR 0/{total}{suffix}", total=total)
        done_count = {"n": 0}

        def on_start(page: int, index: int) -> None:
            # Parallel OCR: show completion count, not "current page N".
            progress.update(
                task_id,
                description=f"OCR {done_count['n']}/{total}{suffix}",
            )

        def on_done(page: int, char_count: int, markdown: str | None = None) -> None:
            done_count["n"] += 1
            progress.advance(task_id)
            progress.update(
                task_id,
                description=f"OCR {done_count['n']}/{total}{suffix}",
            )
            progress.console.print(
                f"  [green]✓[/] Page {page} ({char_count:,} ký tự)"
            )

        yield OcrProgressHooks(on_start=on_start, on_done=on_done)


class RichConversionListener:
    """CLI presentation listener: console lines + OCR progress bar."""

    def __init__(self) -> None:
        self._console = Console(highlight=False)
        self._ocr_stack = ExitStack()
        self._hooks: Optional[OcrProgressHooks] = None
        self._closed = False

    def _close_ocr_progress(self) -> None:
        """Close progress bar before later lines (matches pre-refactor order)."""
        if self._hooks is None:
            return
        self._hooks = None
        self._ocr_stack.close()
        self._ocr_stack = ExitStack()

    def emit(self, event: ConversionEvent) -> None:
        if isinstance(event, AnalysisDone):
            self._console.print(
                f"[bold]→[/bold] PDF type: [yellow]{event.pdf_type}[/yellow] | "
                f"Confidence: [yellow]{event.confidence:.2f}[/yellow] | "
                f"Total pages: [yellow]{event.total_pages}[/yellow] | "
                f"Pages need OCR: [yellow]{format_ocr_pages(event.ocr_pages)}[/yellow]"
            )
            return
        if isinstance(event, CacheSummary):
            self._console.print(
                f"[bold]→[/bold] Cache hit [yellow]{event.hits}[/yellow] trang, "
                f"OCR còn [yellow]{event.misses}[/yellow] trang"
            )
            for page in event.cached_pages:
                self._console.print(f"  [green]✓[/] Page {page} (cache)")
            return
        if isinstance(event, OcrStarted):
            backend_label = event.backend
            if event.model:
                backend_label = f"{event.backend} ({event.model})"
            self._console.print(
                f"[bold]→[/bold] Đang OCR {event.total} trang bằng {backend_label}..."
            )
            cm = ocr_progress(
                event.total,
                backend=event.backend,
                model=event.model,
                show=True,
            )
            self._hooks = self._ocr_stack.enter_context(cm)
            return
        if isinstance(event, PageStarted):
            if self._hooks is not None:
                self._hooks.on_start(event.page, event.index)
            return
        if isinstance(event, PageDone):
            if self._hooks is not None:
                self._hooks.on_done(event.page, event.char_count)
            return
        if isinstance(event, PageRetry):
            self._console.print(
                f"  [yellow]![/] Page {event.page} retry #{event.attempt}: {event.reason}"
            )
            return
        if isinstance(event, PageEmpty):
            self._console.print(
                f"  [yellow]![/] Page {event.page}: OCR rỗng "
                f"(sau {event.attempts} lần thử)"
            )
            return
        if isinstance(event, PageFailed):
            self._console.print(
                f"  [red]✗[/] Page {event.page}: {event.reason}"
            )
            return
        if isinstance(event, FallbackUsed):
            self._console.print(
                f"  [yellow]![/] Page {event.page}: fallback "
                f"{event.requested_model} → {event.actual_model}"
            )
            return
        if isinstance(event, HeadersStripped):
            patterns = ", ".join(event.patterns[:5]) if event.patterns else "(page numbers)"
            self._console.print(
                f"[bold]→[/bold] Đã xoá running header/footer: "
                f"[yellow]{event.removed_lines}[/yellow] dòng "
                f"(patterns: {patterns})"
            )
            return
        if isinstance(event, CacheFinal):
            self._close_ocr_progress()
            self._console.print(
                f"[bold]→[/bold] Cache: [yellow]{event.hits}[/yellow] hit / "
                f"[yellow]{event.misses}[/yellow] miss"
            )
            return
        if isinstance(event, Completed):
            self._close_ocr_progress()
            return

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_ocr_progress()
