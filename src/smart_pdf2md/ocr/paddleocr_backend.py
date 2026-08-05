from __future__ import annotations

import logging
import statistics
from typing import Any

import numpy as np

from smart_pdf2md.config import Options
from smart_pdf2md.errors import OcrBackendError
from smart_pdf2md.models import PageResult
from smart_pdf2md.ocr.base import OcrBackend, notify_page_done
from smart_pdf2md.render import render_pages

logger = logging.getLogger(__name__)

_MISSING_ENGINE_MSG = (
    "PaddleOCR chưa sẵn sàng. Cài paddlepaddle (CPU) rồi uv sync — "
    "xem docs/INSTALL.md."
)

_PARAGRAPH_GAP_FACTOR = 1.5


def _lang_from_options(options: Options) -> str:
    langs = getattr(options, "languages", None) or []
    for lang in langs:
        token = str(lang).strip().lower()
        if token:
            return token
    return "vi"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _box_upper_left_height(box: Any) -> tuple[float, float, float]:
    """Parse rec_boxes [[x1,y1,x2,y2]] or rec_polys into (upper, left, height)."""
    pts = _as_list(box)
    if not pts:
        return 0.0, 0.0, 0.0

    # Axis-aligned [x1, y1, x2, y2]
    if len(pts) == 4 and all(isinstance(v, (int, float)) for v in pts):
        x1, y1, x2, y2 = (float(v) for v in pts)
        return y1, x1, max(0.0, y2 - y1)

    # Polygon [[x,y], ...]
    xs: list[float] = []
    ys: list[float] = []
    for p in pts:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            xs.append(float(p[0]))
            ys.append(float(p[1]))
        elif isinstance(p, (int, float)):
            # Flat [x1,y1,x2,y2,...]
            continue
    if len(pts) >= 4 and not xs and all(isinstance(v, (int, float)) for v in pts):
        flat = [float(v) for v in pts]
        xs = flat[0::2]
        ys = flat[1::2]
    if not xs or not ys:
        return 0.0, 0.0, 0.0
    return min(ys), min(xs), max(0.0, max(ys) - min(ys))


def _extract_res_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        if isinstance(item.get("res"), dict):
            return item["res"]
        return item
    json_attr = getattr(item, "json", None)
    if isinstance(json_attr, dict):
        if isinstance(json_attr.get("res"), dict):
            return json_attr["res"]
        return json_attr
    return {}


def _predict_to_regions(result: Any) -> list[dict[str, Any]]:
    """Normalize PaddleOCR 3.x predict output → [{text, upper, left, height}]."""
    items: list[Any]
    if result is None:
        return []
    if isinstance(result, list):
        items = result
    else:
        items = [result]

    regions: list[dict[str, Any]] = []
    for item in items:
        res = _extract_res_dict(item)
        texts = _as_list(
            res.get("rec_texts")
            if res
            else getattr(item, "rec_texts", None)
        )
        boxes = _as_list(
            res.get("rec_boxes")
            if res and res.get("rec_boxes") is not None
            else (
                res.get("rec_polys")
                if res
                else getattr(item, "rec_boxes", None)
                or getattr(item, "rec_polys", None)
            )
        )
        if not texts and hasattr(item, "rec_texts"):
            texts = _as_list(getattr(item, "rec_texts", None))
        if not boxes and hasattr(item, "rec_boxes"):
            boxes = _as_list(getattr(item, "rec_boxes", None))
        if not boxes and hasattr(item, "rec_polys"):
            boxes = _as_list(getattr(item, "rec_polys", None))

        for idx, text in enumerate(texts):
            line = str(text or "").strip()
            if not line:
                continue
            box = boxes[idx] if idx < len(boxes) else None
            upper, left, height = _box_upper_left_height(box)
            regions.append(
                {
                    "text": line,
                    "upper": upper,
                    "left": left,
                    "height": height,
                }
            )
    return regions


def _regions_to_markdown(regions: list[dict[str, Any]]) -> str:
    cleaned = [r for r in regions if str(r.get("text", "")).strip()]
    cleaned.sort(
        key=lambda r: (round(float(r["upper"]), 3), round(float(r["left"]), 3))
    )
    if not cleaned:
        return ""

    heights = [float(r.get("height") or 0.0) for r in cleaned if float(r.get("height") or 0.0) > 0]
    median_h = statistics.median(heights) if heights else 0.0
    gap_threshold = (
        _PARAGRAPH_GAP_FACTOR * median_h if median_h > 0 else float("inf")
    )

    lines: list[str] = [str(cleaned[0]["text"]).strip()]
    for prev, curr in zip(cleaned, cleaned[1:]):
        gap = float(curr["upper"]) - float(prev["upper"])
        if gap > gap_threshold:
            lines.append("")
        lines.append(str(curr["text"]).strip())
    return "\n".join(lines)


class PaddleOcrBackend(OcrBackend):
    name = "paddleocr"

    def __init__(self) -> None:
        self._engine: Any = None

    def _get_engine(self, options: Options) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OcrBackendError(_MISSING_ENGINE_MSG) from exc

        lang = _lang_from_options(options)
        # PP-OCRv6 needs paddlepaddle >= 3.1 (3.0 hits PIR strides error).
        paddle_ver = None
        try:
            import paddle

            paddle_ver = getattr(paddle, "__version__", "?")
        except Exception:  # noqa: BLE001
            paddle_ver = None
        paddle_ok = False
        try:
            parts = [int(x) for x in str(paddle_ver or "0").split(".")[:2]]
            paddle_ok = tuple(parts + [0, 0])[:2] >= (3, 1)
        except ValueError:
            paddle_ok = False
        if not paddle_ok:
            raise OcrBackendError(
                f"Cần paddlepaddle>=3.1.0 (đang có {paddle_ver}). "
                "Cài lại theo docs/INSTALL.md — PP-OCRv6 không chạy trên 3.0.0."
            )
        init_kwargs = {
            "lang": lang,
            "text_detection_model_name": "PP-OCRv6_medium_det",
            "text_recognition_model_name": "PP-OCRv6_medium_rec",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
        try:
            self._engine = PaddleOCR(**init_kwargs)
        except Exception as exc:  # noqa: BLE001 — wrap engine init failures
            raise OcrBackendError(
                f"Không khởi tạo được PaddleOCR: {exc}. Xem docs/INSTALL.md."
            ) from exc
        return self._engine

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

        engine = self._get_engine(options)
        target_pages = sorted(p.page + 1 for p in pages)

        results: dict[int, str] = {}
        for index, page_number in enumerate(target_pages, start=1):
            # Update progress before render so large batches are not stuck at 0/N.
            if on_page_start is not None:
                on_page_start(page_number, index)
            images = render_pages(
                pdf_path,
                [page_number],
                dpi=options.dpi,
                poppler_path=options.poppler_path,
            )
            image = images.get(page_number)
            if image is None:
                raise OcrBackendError(f"Không render được trang {page_number}")

            rgb = image.convert("RGB") if getattr(image, "mode", "RGB") != "RGB" else image
            img = np.asarray(rgb)
            try:
                pred = engine.predict(img)
            except Exception as exc:  # noqa: BLE001
                raise OcrBackendError(
                    f"PaddleOCR lỗi khi OCR trang {page_number}: {exc}"
                ) from exc

            regions = _predict_to_regions(pred)
            markdown = _regions_to_markdown(regions)
            results[page_number] = markdown
            notify_page_done(on_page_done, page_number, markdown)

        return results
