from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter

from smart_pdf2md.config import Options
from smart_pdf2md.env import load_app_env
from smart_pdf2md.errors import OcrBackendError, OcrFatalError, PdfReadError
from smart_pdf2md.events import FallbackUsed, PageEmpty, PageFailed, PageRetry
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.base import OcrBackend, notify_page_done
from smart_pdf2md.ocr.opencode_pricing import estimate_cost_usd
from smart_pdf2md.ocr.vlm.dialects import get_dialect
from smart_pdf2md.ocr.vlm.dialects import anthropic as anth_dialect
from smart_pdf2md.ocr.vlm.images import image_to_b64
from smart_pdf2md.ocr.vlm.postprocess import postprocess_markdown
from smart_pdf2md.ocr.vlm.prompts import ocr_prompt
from smart_pdf2md.ocr.vlm.registry import lookup
from smart_pdf2md.ocr.vlm.spec import Capability, ImageLimits, ModelSpec, Pricing
from smart_pdf2md.render import render_pages

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
_DEFAULT_MODEL = "qwen3.6-plus"
_DEFAULT_DIALECT = "anthropic_messages"
_FALLBACK_MODEL = "grok-4.5"
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 2
_BACKOFF_SECONDS = (2.0, 4.0)
_CIRCUIT_CONSECUTIVE = 5
_CIRCUIT_MIN_PAGES = 20
_CIRCUIT_FAIL_RATIO = 0.20
_RENDER_BATCH = 16

# Kept for import compatibility with tests/test_opencode_backend.py
_OCR_PROMPT = ocr_prompt()


def _build_payload(b64: str, model: str, max_tokens: int) -> dict[str, Any]:
    """Thin wrapper — existing tests import this symbol."""
    return anth_dialect.build_payload(b64, model, max_tokens, _OCR_PROMPT)


def _build_openai_payload(b64: str, model: str, max_tokens: int) -> dict[str, Any]:
    from smart_pdf2md.ocr.vlm.dialects import openai as oai_dialect

    return oai_dialect.build_payload(b64, model, max_tokens, _OCR_PROMPT)


def _extract_usage(payload: Any) -> tuple[int, int]:
    """Parse (input_tokens, output_tokens) from Anthropic or OpenAI usage."""
    if not isinstance(payload, dict):
        return 0, 0
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return 0, 0
    if "input_tokens" in usage or "output_tokens" in usage:
        return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    if "prompt_tokens" in usage or "completion_tokens" in usage:
        return (
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
        )
    return 0, 0


def _extract_text(payload: Any) -> str:
    """Anthropic text extract — preserves legacy error messages for tests."""
    if not isinstance(payload, dict):
        raise OcrBackendError("OpenCode VLM response schema lạ (không phải object).")
    content = payload.get("content")
    if not isinstance(content, list):
        raise OcrBackendError(
            "OpenCode VLM response schema lạ (thiếu content[])."
        )
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    if not parts and content:
        raise OcrBackendError(
            "OpenCode VLM response schema lạ (không có block text)."
        )
    return "".join(parts)


def _extract_openai_text(payload: Any) -> str:
    from smart_pdf2md.ocr.vlm.dialects import openai as oai_dialect

    try:
        return oai_dialect.parse_text(payload)
    except OcrBackendError as exc:
        raise OcrBackendError(f"OpenCode VLM (OpenAI) {exc}") from exc


def _postprocess(text: str, profile: str = "default") -> str:
    return postprocess_markdown(text, prompt_profile=profile)


def _response_truncated(data: Any, dialect_name: str) -> bool:
    if not isinstance(data, dict):
        return False
    if dialect_name == "anthropic_messages":
        return data.get("stop_reason") == "max_tokens"
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0].get("finish_reason") == "length"
    return False


def _image_rejected(status: int, body: str) -> bool:
    """True only when the error clearly rejects image/vision content."""
    if status < 400:
        return False
    low = (body or "").lower()
    image_words = (
        "image",
        "vision",
        "multimodal",
        "media type",
        "content block",
    )
    negation = (
        "does not support",
        "not support",
        "unsupported",
        "not allowed",
        "rejected",
        "reject",
    )
    has_image = any(w in low for w in image_words)
    has_neg = any(n in low for n in negation)
    return has_image and has_neg


def _default_spec(model_id: str) -> ModelSpec:
    return ModelSpec(
        id=model_id,
        label=model_id,
        provider="opencode",
        enabled=True,
        capability=Capability(
            dialect=_DEFAULT_DIALECT,
            supports_vision=True,
            max_output_tokens=8192,
            image=ImageLimits(max_side_px=None),
            prompt_profile="default",
            fallback_model=_FALLBACK_MODEL,
        ),
            pricing=Pricing(),
    )


def _is_poppler_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "poppler" in msg or "pdftoppm" in msg or "pdfinfo" in msg


class OpencodeVlmBackend(OcrBackend):
    name = "opencode"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_usd_acc = 0.0
        self._cost_unknown = False
        self._usage_lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._rate_cooldown_until = 0.0

    def _configure_pool(self, concurrency: int) -> None:
        size = max(1, int(concurrency))
        mount = getattr(self._session, "mount", None)
        if not callable(mount):
            return
        adapter = HTTPAdapter(pool_connections=size, pool_maxsize=size)
        mount("https://", adapter)
        mount("http://", adapter)

    def _wait_rate_cooldown(self) -> None:
        with self._rate_lock:
            until = self._rate_cooldown_until
        delay = until - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def _trip_rate_cooldown(self, seconds: float = 5.0) -> None:
        with self._rate_lock:
            self._rate_cooldown_until = max(
                self._rate_cooldown_until, time.monotonic() + seconds
            )

    def _reset_usage(self) -> None:
        with self._usage_lock:
            self._input_tokens = 0
            self._output_tokens = 0
            self._cost_usd_acc = 0.0
            self._cost_unknown = False

    def _record_usage(self, model: str, payload: Any) -> None:
        inp, out = _extract_usage(payload)
        with self._usage_lock:
            self._input_tokens += inp
            self._output_tokens += out
            if inp == 0 and out == 0:
                return
            est = estimate_cost_usd(model, inp, out)
            if est is None:
                self._cost_unknown = True
            else:
                self._cost_usd_acc += est

    def consume_usage(self) -> tuple[int, int, float | None]:
        """Return and reset (input_tokens, output_tokens, cost_usd)."""
        with self._usage_lock:
            inp, out = self._input_tokens, self._output_tokens
            if not inp and not out:
                cost: float | None = None
            elif self._cost_unknown:
                cost = None
            else:
                cost = self._cost_usd_acc
            self._input_tokens = 0
            self._output_tokens = 0
            self._cost_usd_acc = 0.0
            self._cost_unknown = False
        return inp, out, cost

    def _api_key(self) -> str:
        load_app_env()
        key = (os.environ.get("OPENCODE_API_KEY") or "").strip()
        if not key:
            raise OcrFatalError(
                "Thiếu OPENCODE_API_KEY. Lấy key tại https://opencode.ai/auth "
                "rồi export OPENCODE_API_KEY=... hoặc ghi vào .env "
                "(xem docs/INSTALL.md)."
            )
        return key

    def _base_url(self) -> str:
        load_app_env()
        return (
            os.environ.get("OPENCODE_BASE_URL") or _DEFAULT_BASE_URL
        ).rstrip("/")

    def _map_http_error(self, status: int, body: str) -> OcrBackendError:
        if status == 401:
            return OcrFatalError(
                "OPENCODE_API_KEY không hợp lệ (HTTP 401). "
                "Kiểm tra lại key tại https://opencode.ai/auth."
            )
        if status == 429:
            return OcrBackendError(
                "OpenCode Go hết usage limit (HTTP 429). "
                "Đợi reset hoặc bật 'Use balance' trong console."
            )
        snippet = (body or "")[:400]
        return OcrBackendError(f"OpenCode VLM HTTP {status}: {snippet}")

    def _post_with_retry(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        *,
        page: Optional[int] = None,
        listener=None,
    ) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            self._wait_rate_cooldown()
            try:
                resp = self._session.post(
                    url, headers=headers, json=payload, timeout=120
                )
            except requests.Timeout as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    if listener is not None and page is not None:
                        listener.emit(
                            PageRetry(
                                page=page,
                                attempt=attempt + 1,
                                reason="timeout",
                            )
                        )
                    time.sleep(_BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)])
                    continue
                raise OcrBackendError(
                    f"OpenCode VLM timeout sau {_MAX_RETRIES + 1} lần thử."
                ) from exc
            except requests.RequestException as exc:
                raise OcrBackendError(f"OpenCode VLM network error: {exc}") from exc

            if resp.status_code == 429:
                self._trip_rate_cooldown()
            if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                if listener is not None and page is not None:
                    listener.emit(
                        PageRetry(
                            page=page,
                            attempt=attempt + 1,
                            reason=f"HTTP {resp.status_code}",
                        )
                    )
                time.sleep(_BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)])
                continue
            return resp

        assert last_exc is not None
        raise OcrBackendError(f"OpenCode VLM thất bại: {last_exc}") from last_exc

    def _resolve_spec(self, model: str) -> ModelSpec:
        spec = lookup(model)
        if spec is None:
            return _default_spec(model)
        return spec

    def _call_dialect(
        self,
        dialect_name: str,
        b64: str,
        model: str,
        max_tokens: int,
        api_key: str,
        *,
        prompt: str = _OCR_PROMPT,
        page: Optional[int] = None,
        listener=None,
    ) -> tuple[str, bool]:
        dialect = get_dialect(dialect_name)
        url = f"{self._base_url()}{dialect.ENDPOINT}"
        headers = dialect.auth_headers(api_key)
        payload = dialect.build_payload(b64, model, max_tokens, prompt)
        resp = self._post_with_retry(
            url, headers, payload, page=page, listener=listener
        )
        if resp.status_code >= 400:
            body = resp.text or ""
            if _image_rejected(resp.status_code, body):
                raise _ImageRejected(body)
            raise self._map_http_error(resp.status_code, body)
        try:
            data = resp.json()
        except ValueError as exc:
            raise OcrBackendError("OpenCode VLM trả non-JSON response.") from exc
        self._record_usage(model, data)
        truncated = _response_truncated(data, dialect_name)
        if dialect_name == "anthropic_messages":
            text = _extract_text(data)
        else:
            text = dialect.parse_text(data)
        return text, truncated

    def _ocr_image(
        self,
        image: Any,
        options: Options,
        *,
        page: Optional[int] = None,
        listener=None,
    ) -> tuple[str, int]:
        """OCR one image. Returns (markdown, attempts). Empty string if still blank."""
        api_key = self._api_key()
        quality = int(getattr(options, "vlm_jpeg_quality", 85) or 85)
        requested = int(getattr(options, "vlm_max_tokens", 8192) or 8192)
        model = str(getattr(options, "vlm_model", None) or _DEFAULT_MODEL)
        spec = self._resolve_spec(model)

        if not spec.capability.supports_vision:
            raise OcrFatalError(
                f"Model {model!r} không hỗ trợ vision/image OCR."
            )

        max_tokens = min(requested, int(spec.capability.max_output_tokens))
        limits = spec.capability.image
        b64 = image_to_b64(image, quality=quality, limits=limits)
        dialect_name = spec.capability.dialect or _DEFAULT_DIALECT
        allow_fallback = bool(getattr(options, "allow_vlm_fallback", True))
        fallback_model = None
        if allow_fallback:
            candidate = spec.capability.fallback_model or _FALLBACK_MODEL
            fb_spec = lookup(candidate) if candidate else None
            # Never fall back to a missing/disabled model (e.g. grok-4.5 off).
            if fb_spec is not None and fb_spec.enabled:
                fallback_model = candidate
        profile = spec.capability.prompt_profile
        attempts = 0

        def _run(
            *,
            use_model: str,
            use_dialect: str,
            use_max: int,
            use_profile: str,
        ) -> tuple[str, bool]:
            nonlocal attempts
            attempts += 1
            raw, truncated = self._call_dialect(
                use_dialect,
                b64,
                use_model,
                use_max,
                api_key,
                prompt=ocr_prompt(use_profile),
                page=page,
                listener=listener,
            )
            return _postprocess(raw, use_profile), truncated

        try:
            text, truncated = _run(
                use_model=model,
                use_dialect=dialect_name,
                use_max=max_tokens,
                use_profile=profile,
            )
        except _ImageRejected as exc:
            if not allow_fallback or not fallback_model:
                raise OcrFatalError(
                    f"Model rejected image and VLM fallback is disabled: {exc}"
                ) from exc
            logger.warning(
                "Model %s rejected image (%s); falling back to %s",
                model,
                str(exc)[:200],
                fallback_model,
            )
            if listener is not None and page is not None:
                listener.emit(
                    FallbackUsed(
                        page=page,
                        requested_model=model,
                        actual_model=fallback_model,
                    )
                )
            fb_spec = self._resolve_spec(fallback_model)
            fb_dialect = fb_spec.capability.dialect or "openai_chat"
            fb_max = min(max_tokens, int(fb_spec.capability.max_output_tokens))
            profile = fb_spec.capability.prompt_profile
            text, truncated = _run(
                use_model=fallback_model,
                use_dialect=fb_dialect,
                use_max=fb_max,
                use_profile=profile,
            )
            return text, attempts

        if text.strip():
            return text, attempts

        # Targeted empty-page recovery.
        if truncated:
            higher = min(
                int(spec.capability.max_output_tokens),
                max(max_tokens * 2, max_tokens + 4096),
            )
            if higher > max_tokens:
                if listener is not None and page is not None:
                    listener.emit(
                        PageRetry(
                            page=page,
                            attempt=attempts,
                            reason=f"empty+max_tokens → {higher}",
                        )
                    )
                text, truncated = _run(
                    use_model=model,
                    use_dialect=dialect_name,
                    use_max=higher,
                    use_profile=profile,
                )
                if text.strip():
                    return text, attempts

        if allow_fallback and fallback_model and fallback_model != model:
            if listener is not None and page is not None:
                listener.emit(
                    FallbackUsed(
                        page=page,
                        requested_model=model,
                        actual_model=fallback_model,
                    )
                )
                listener.emit(
                    PageRetry(
                        page=page,
                        attempt=attempts,
                        reason="empty → fallback model",
                    )
                )
            fb_spec = self._resolve_spec(fallback_model)
            fb_dialect = fb_spec.capability.dialect or "openai_chat"
            fb_max = min(
                max(max_tokens, int(getattr(options, "vlm_max_tokens", 8192) or 8192)),
                int(fb_spec.capability.max_output_tokens),
            )
            fb_profile = fb_spec.capability.prompt_profile
            text, _ = _run(
                use_model=fallback_model,
                use_dialect=fb_dialect,
                use_max=fb_max,
                use_profile=fb_profile,
            )
            if text.strip():
                return text, attempts

        return "", attempts

    def _check_circuit(
        self,
        *,
        consecutive: int,
        failed: int,
        processed: int,
    ) -> None:
        if consecutive >= _CIRCUIT_CONSECUTIVE:
            raise OcrFatalError(
                f"OCR circuit breaker: {_CIRCUIT_CONSECUTIVE} trang lỗi liên tiếp."
            )
        if (
            processed >= _CIRCUIT_MIN_PAGES
            and failed / processed > _CIRCUIT_FAIL_RATIO
        ):
            pct = failed / processed * 100
            raise OcrFatalError(
                f"OCR circuit breaker: tỉ lệ lỗi {pct:.0f}% sau {processed} trang."
            )

    def _ocr_one_page(
        self,
        page_number: int,
        image: Any,
        options: Options,
        *,
        listener=None,
    ) -> tuple[str, Optional[str], int]:
        """Returns (markdown, error_reason_or_None, attempts)."""
        try:
            markdown, attempts = self._ocr_image(
                image, options, page=page_number, listener=listener
            )
        except OcrFatalError:
            raise
        except OcrBackendError as exc:
            return "", str(exc), 1
        except PdfReadError as exc:
            if _is_poppler_error(exc):
                raise OcrFatalError(str(exc)) from exc
            return "", str(exc), 1
        if not markdown.strip():
            return "", None, attempts
        return markdown, None, attempts

    def ocr_pages(
        self,
        pages: list[PageResult],
        pdf_path: str,
        options: Options,
        on_page_done=None,
        on_page_start=None,
        *,
        listener=None,
    ) -> dict[int, str]:
        if not pages:
            return {}

        self._reset_usage()
        # Fail fast on missing key / no-vision before rendering
        self._api_key()
        model = str(getattr(options, "vlm_model", None) or _DEFAULT_MODEL)
        spec = self._resolve_spec(model)
        if not spec.capability.supports_vision:
            raise OcrFatalError(
                f"Model {model!r} không hỗ trợ vision/image OCR."
            )

        concurrency = max(1, int(getattr(options, "concurrency", 1) or 1))
        self._configure_pool(concurrency)

        target_pages = sorted(p.page + 1 for p in pages)
        results: dict[int, str] = {}
        consecutive_failures = 0
        failed_count = 0
        processed = 0

        if concurrency <= 1:
            for index, page_number in enumerate(target_pages, start=1):
                if on_page_start is not None:
                    on_page_start(page_number, index)
                try:
                    images = render_pages(
                        pdf_path,
                        [page_number],
                        dpi=options.dpi,
                        poppler_path=options.poppler_path,
                    )
                except PdfReadError as exc:
                    if _is_poppler_error(exc):
                        raise OcrFatalError(str(exc)) from exc
                    raise OcrFatalError(str(exc)) from exc
                image = images.get(page_number)
                if image is None:
                    raise OcrFatalError(f"Không render được trang {page_number}")

                markdown, err, attempts = self._ocr_one_page(
                    page_number, image, options, listener=listener
                )
                processed += 1
                if err is not None:
                    failed_count += 1
                    consecutive_failures += 1
                    results[page_number] = ""
                    if listener is not None:
                        listener.emit(PageFailed(page=page_number, reason=err))
                    notify_page_done(on_page_done, page_number, "")
                    self._check_circuit(
                        consecutive=consecutive_failures,
                        failed=failed_count,
                        processed=processed,
                    )
                    continue
                if not markdown.strip():
                    consecutive_failures = 0
                    results[page_number] = ""
                    if listener is not None:
                        listener.emit(
                            PageEmpty(page=page_number, attempts=attempts)
                        )
                    notify_page_done(on_page_done, page_number, "")
                    continue
                consecutive_failures = 0
                results[page_number] = markdown
                notify_page_done(on_page_done, page_number, markdown)
            return results

        # Parallel path: render in batches, OCR with a thread pool inside each batch.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        page_index = {p: i for i, p in enumerate(target_pages, start=1)}
        state_lock = threading.Lock()

        for batch_start in range(0, len(target_pages), _RENDER_BATCH):
            batch = target_pages[batch_start : batch_start + _RENDER_BATCH]
            try:
                images = render_pages(
                    pdf_path,
                    batch,
                    dpi=options.dpi,
                    poppler_path=options.poppler_path,
                )
            except PdfReadError as exc:
                if _is_poppler_error(exc):
                    raise OcrFatalError(str(exc)) from exc
                raise OcrFatalError(str(exc)) from exc

            def _work(page_number: int) -> tuple[int, str, Optional[str], int]:
                if on_page_start is not None:
                    on_page_start(page_number, page_index[page_number])
                image = images.get(page_number)
                if image is None:
                    raise OcrFatalError(f"Không render được trang {page_number}")
                md, err, attempts = self._ocr_one_page(
                    page_number, image, options, listener=listener
                )
                return page_number, md, err, attempts

            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {pool.submit(_work, p): p for p in batch}
                for fut in as_completed(futures):
                    try:
                        page_number, markdown, err, attempts = fut.result()
                    except OcrFatalError:
                        for other in futures:
                            other.cancel()
                        raise
                    with state_lock:
                        processed += 1
                        if err is not None:
                            failed_count += 1
                            consecutive_failures += 1
                            results[page_number] = ""
                            if listener is not None:
                                listener.emit(
                                    PageFailed(page=page_number, reason=err)
                                )
                            notify_page_done(on_page_done, page_number, "")
                            self._check_circuit(
                                consecutive=consecutive_failures,
                                failed=failed_count,
                                processed=processed,
                            )
                            continue
                        if not markdown.strip():
                            consecutive_failures = 0
                            results[page_number] = ""
                            if listener is not None:
                                listener.emit(
                                    PageEmpty(page=page_number, attempts=attempts)
                                )
                            notify_page_done(on_page_done, page_number, "")
                            continue
                        consecutive_failures = 0
                        results[page_number] = markdown
                        notify_page_done(on_page_done, page_number, markdown)

        return results


class _ImageRejected(Exception):
    """Internal: endpoint rejected the image content."""
