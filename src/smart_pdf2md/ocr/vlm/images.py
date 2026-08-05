from __future__ import annotations

import base64
import io
from typing import Any, Optional

from smart_pdf2md.ocr.vlm.spec import ImageLimits


def prepare_image(image: Any, limits: ImageLimits):
    """Convert to RGB and optionally downscale by longest side."""
    mode = getattr(image, "mode", "RGB")
    rgb = image.convert("RGB") if mode != "RGB" else image
    max_side = limits.max_side_px
    if max_side is None or max_side <= 0:
        return rgb
    w, h = rgb.size
    longest = max(w, h)
    if longest <= max_side:
        return rgb
    scale = max_side / float(longest)
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return rgb.resize(new_size)


def encode_image_jpeg(image: Any, *, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=int(quality))
    return buf.getvalue()


def image_to_b64(
    image: Any,
    *,
    quality: int = 85,
    limits: Optional[ImageLimits] = None,
) -> str:
    prepared = prepare_image(image, limits or ImageLimits())
    return base64.b64encode(encode_image_jpeg(prepared, quality=quality)).decode(
        "ascii"
    )
