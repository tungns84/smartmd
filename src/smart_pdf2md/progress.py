from typing import Callable, Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

PageDoneCallback = Callable[[int, int], None]


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

    def _cb(page: int, char_count: int) -> None:
        if not show_progress:
            return
        console.print(f"  [green]✓[/] Page {page} ({char_count:,} ký tự)")

    return _cb
