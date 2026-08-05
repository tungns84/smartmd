import inspect
import time
from pathlib import Path
from typing import Optional, Sequence

from smart_pdf2md.cache import OcrPageCache
from smart_pdf2md.classifier import AnalysisResult, analyze_pdf, extract_pages
from smart_pdf2md.config import Options
from smart_pdf2md.env import get_vlm_model, load_app_env
from smart_pdf2md.events import (
    AnalysisDone,
    CacheFinal,
    CacheSummary,
    Completed,
    ConversionEvent,
    ConversionListener,
    HeadersStripped,
    NullListener,
    OcrStarted,
    PageDone,
    PageEmpty,
    PageFailed,
    PageStarted,
)
from smart_pdf2md.headers import strip_running_headers
from smart_pdf2md.merge import merge_pages
from smart_pdf2md.models import ConversionResult, PageResult
from smart_pdf2md.ocr import get_ocr_backend


MIN_NATIVE_CHARS = 120


class _OcrOutcomeCollector:
    """Record PageEmpty / PageFailed while forwarding to the real listener."""

    def __init__(self, inner: ConversionListener) -> None:
        self._inner = inner
        self.empty: dict[int, int] = {}
        self.failed: dict[int, str] = {}

    def emit(self, event: ConversionEvent) -> None:
        if isinstance(event, PageEmpty):
            self.empty[event.page] = event.attempts
        elif isinstance(event, PageFailed):
            self.failed[event.page] = event.reason
        self._inner.emit(event)

    def close(self) -> None:
        self._inner.close()


def plan_ocr_pages(
    *,
    pdf_type: str,
    page_count: int,
    pages_needing_ocr: Sequence[int],
    page_native_chars: Sequence[int],
    force_ocr: bool,
    selected_pages: Optional[Sequence[int]] = None,
) -> list[int]:
    """Pure OCR routing: 1-indexed pages that will call the OCR backend.

    Shared by CLI ``convert_full`` and web credit hold so the two cannot drift.
    ``page_native_chars`` is 0-based by page index; values are native char counts.
    """
    if selected_pages is not None:
        selected = set(selected_pages)
    else:
        selected = set(range(1, page_count + 1))

    if force_ocr:
        return sorted(selected)

    if pdf_type == "text_based":
        return []

    needing = set(pages_needing_ocr) & selected
    for page_num in selected:
        if page_num in needing:
            continue
        idx = page_num - 1
        if idx < 0 or idx >= len(page_native_chars):
            continue
        if page_native_chars[idx] < MIN_NATIVE_CHARS:
            needing.add(page_num)
    return sorted(needing)


def _select_pages(pages: list[PageResult], subset: Optional[list[int]]) -> list[PageResult]:
    if not subset:
        return pages
    wanted = set(subset)
    return [p for p in pages if (p.page + 1) in wanted]


def format_elapsed(ms: int) -> str:
    total_s = max(0, int(ms) // 1000)
    minutes, seconds = divmod(total_s, 60)
    if minutes:
        return f"{minutes}m{seconds}s"
    return f"{seconds}s"


def _resolve_listener(
    listener: Optional[ConversionListener],
    show_progress: bool,
) -> ConversionListener:
    if listener is not None:
        return listener
    if show_progress:
        from smart_pdf2md.progress import RichConversionListener

        return RichConversionListener()
    return NullListener()


def convert_full(
    pdf_path: str | Path,
    output: Optional[str | Path] = None,
    languages: Optional[list[str]] = None,
    dpi: int = 200,
    compact: bool = False,
    force_ocr: bool = False,
    show_progress: bool = True,
    page_markers: bool = True,
    pages: Optional[list[int]] = None,
    ocr_backend: str = "opencode",
    poppler_path: Optional[str] = None,
    vlm_model: Optional[str] = None,
    vlm_jpeg_quality: int = 85,
    vlm_max_tokens: int = 8192,
    use_cache: bool = True,
    strip_headers: bool = True,
    concurrency: int = 4,
    *,
    listener: Optional[ConversionListener] = None,
) -> ConversionResult:
    load_app_env()
    started = time.monotonic()
    active = _resolve_listener(listener, show_progress)
    options = Options(
        languages=languages or ["vi", "en"],
        dpi=dpi,
        compact=compact,
        force_ocr=force_ocr,
        show_progress=show_progress,
        page_markers=page_markers,
        ocr_backend=ocr_backend,
        poppler_path=poppler_path,
        vlm_model=vlm_model or get_vlm_model(),
        vlm_jpeg_quality=vlm_jpeg_quality,
        vlm_max_tokens=vlm_max_tokens,
        use_cache=use_cache,
        strip_headers=strip_headers,
        concurrency=concurrency,
    )

    try:
        all_pages, analysis = extract_pages(pdf_path)
        selected = _select_pages(all_pages, pages)
        if not selected:
            raise ValueError("Không có trang nào khớp với yêu cầu")

        page_native_chars = [len(p.markdown.strip()) for p in all_pages]
        ocr_list = plan_ocr_pages(
            pdf_type=analysis.pdf_type,
            page_count=analysis.page_count,
            pages_needing_ocr=analysis.pages_needing_ocr,
            page_native_chars=page_native_chars,
            force_ocr=options.force_ocr,
            selected_pages=[p.page + 1 for p in selected],
        )
        ocr_pages = set(ocr_list)

        active.emit(
            AnalysisDone(
                pdf_type=analysis.pdf_type,
                confidence=analysis.confidence,
                total_pages=len(selected),
                ocr_pages=ocr_list,
            )
        )

        cache_hits = 0
        cache_misses = 0
        ocr_input_tokens = 0
        ocr_output_tokens = 0
        ocr_cost_usd: Optional[float] = None
        empty_pages: list[int] = []
        outcome = _OcrOutcomeCollector(active)

        if ocr_pages:
            page_cache: Optional[OcrPageCache] = None
            if options.use_cache:
                page_cache = OcrPageCache.for_pdf(pdf_path, options)

            targets = [p for p in selected if (p.page + 1) in ocr_pages]
            cached_pages: list[PageResult] = []
            todo_pages: list[PageResult] = []

            # --force-ocr skips cache reads (always re-OCR) but still writes when enabled.
            if page_cache is not None and not options.force_ocr:
                for page in targets:
                    page_number = page.page + 1
                    cached_md = page_cache.load(page_number)
                    if cached_md is not None:
                        page.markdown = cached_md
                        page.source = "cache"
                        page.needs_ocr = False
                        cached_pages.append(page)
                    else:
                        todo_pages.append(page)
            else:
                todo_pages = list(targets)

            cache_hits = len(cached_pages)
            cache_misses = len(todo_pages)

            if page_cache is not None:
                active.emit(
                    CacheSummary(
                        hits=cache_hits,
                        misses=cache_misses,
                        cached_pages=[p.page + 1 for p in cached_pages],
                    )
                )

            if todo_pages:
                backend = get_ocr_backend(options.ocr_backend)
                model = (
                    options.vlm_model if options.ocr_backend == "opencode" else None
                )
                active.emit(
                    OcrStarted(
                        total=len(todo_pages),
                        backend=options.ocr_backend,
                        model=model,
                    )
                )

                def on_start(page: int, index: int) -> None:
                    outcome.emit(PageStarted(page=page, index=index))

                def on_done(
                    page: int,
                    char_count: int,
                    markdown: str | None = None,
                ) -> None:
                    if (
                        page_cache is not None
                        and markdown is not None
                        and markdown.strip()
                    ):
                        page_cache.save(page, markdown)
                    outcome.emit(PageDone(page=page, char_count=char_count))

                ocr_kwargs = {
                    "on_page_done": on_done,
                    "on_page_start": on_start,
                }
                # Older test doubles omit listener=; only pass when accepted.
                try:
                    if "listener" in inspect.signature(backend.ocr_pages).parameters:
                        ocr_kwargs["listener"] = outcome
                except (TypeError, ValueError):
                    pass
                ocr_results = backend.ocr_pages(
                    todo_pages,
                    str(pdf_path),
                    options,
                    **ocr_kwargs,
                )

                consume = getattr(backend, "consume_usage", None)
                if callable(consume):
                    consumed = consume()
                    ocr_input_tokens = int(consumed[0])
                    ocr_output_tokens = int(consumed[1])
                    if len(consumed) >= 3:
                        ocr_cost_usd = consumed[2]

                # Fallback save for backends/mocks that omit markdown in on_page_done.
                if page_cache is not None:
                    for page_number, md in ocr_results.items():
                        if not (md or "").strip():
                            continue
                        if page_cache.load(page_number) != md:
                            page_cache.save(page_number, md)

                for page in selected:
                    page_number = page.page + 1
                    if page_number in ocr_results:
                        page.markdown = ocr_results[page_number]
                        page.needs_ocr = False
                        if page_number in outcome.failed:
                            page.source = "empty"
                            page.ocr_error = outcome.failed[page_number]
                            empty_pages.append(page_number)
                        elif not (page.markdown or "").strip():
                            page.source = "empty"
                            empty_pages.append(page_number)
                        else:
                            page.source = "ocr"

        if options.strip_headers and len(selected) >= 5:
            stripped = strip_running_headers(selected)
            if stripped.removed_lines:
                selected[:] = stripped.pages
                active.emit(
                    HeadersStripped(
                        patterns=stripped.patterns,
                        removed_lines=stripped.removed_lines,
                    )
                )

        # Also surface empty pages that came from cache pollution healing
        # (cache miss → OCR empty) already tracked; native blanks are left alone.
        for page in selected:
            page_number = page.page + 1
            if (
                page.source in {"ocr", "empty"}
                and not (page.markdown or "").strip()
                and page_number not in empty_pages
            ):
                empty_pages.append(page_number)
                page.source = "empty"

        markdown = merge_pages(
            selected,
            page_markers=options.page_markers,
            compact=options.compact,
        )

        if output is not None:
            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(markdown, encoding="utf-8")

        elapsed_ms = int((time.monotonic() - started) * 1000)
        if cache_hits or cache_misses:
            active.emit(CacheFinal(hits=cache_hits, misses=cache_misses))

        active.emit(
            Completed(
                elapsed_ms=elapsed_ms,
                cache_hits=cache_hits,
                cache_misses=cache_misses,
                ocr_input_tokens=ocr_input_tokens,
                ocr_output_tokens=ocr_output_tokens,
                ocr_cost_usd=ocr_cost_usd,
            )
        )

        return ConversionResult(
            pdf_type=analysis.pdf_type,
            confidence=analysis.confidence,
            page_count=len(selected),
            pages=selected,
            pages_needing_ocr=analysis.pages_needing_ocr,
            markdown=markdown,
            processing_time_ms=analysis.processing_time_ms,
            elapsed_ms=elapsed_ms,
            has_encoding_issues=analysis.has_encoding_issues,
            title=analysis.title,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            ocr_input_tokens=ocr_input_tokens,
            ocr_output_tokens=ocr_output_tokens,
            ocr_cost_usd=ocr_cost_usd,
            empty_pages=sorted(set(empty_pages)),
        )
    finally:
        active.close()


def convert(
    pdf_path: str | Path,
    output: Optional[str | Path] = None,
    languages: Optional[list[str]] = None,
    dpi: int = 200,
    compact: bool = False,
    force_ocr: bool = False,
    show_progress: bool = True,
    page_markers: bool = True,
    pages: Optional[list[int]] = None,
    ocr_backend: str = "opencode",
    poppler_path: Optional[str] = None,
    vlm_model: Optional[str] = None,
    vlm_jpeg_quality: int = 85,
    vlm_max_tokens: int = 8192,
    use_cache: bool = True,
    strip_headers: bool = True,
    concurrency: int = 4,
    *,
    listener: Optional[ConversionListener] = None,
) -> str:
    result = convert_full(
        pdf_path,
        output=output,
        languages=languages,
        dpi=dpi,
        compact=compact,
        force_ocr=force_ocr,
        show_progress=show_progress,
        page_markers=page_markers,
        pages=pages,
        ocr_backend=ocr_backend,
        poppler_path=poppler_path,
        vlm_model=vlm_model,
        vlm_jpeg_quality=vlm_jpeg_quality,
        vlm_max_tokens=vlm_max_tokens,
        use_cache=use_cache,
        strip_headers=strip_headers,
        concurrency=concurrency,
        listener=listener,
    )
    return result.markdown


def analyze(pdf_path: str | Path) -> AnalysisResult:
    return analyze_pdf(pdf_path)
