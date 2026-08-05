"""Cycle 5: image downscale / encode helpers."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from smart_pdf2md.ocr.vlm.images import encode_image_jpeg, prepare_image
from smart_pdf2md.ocr.vlm.spec import ImageLimits


def _img(w: int, h: int, mode: str = "RGB") -> Image.Image:
    return Image.new(mode, (w, h), color=(10, 20, 30) if mode == "RGB" else 128)


def test_downscales_when_longest_side_exceeds_limit():
    out = prepare_image(_img(4000, 2000), ImageLimits(max_side_px=1000))
    assert max(out.size) == 1000


def test_keeps_size_when_under_limit():
    out = prepare_image(_img(800, 600), ImageLimits(max_side_px=1000))
    assert out.size == (800, 600)


def test_preserves_aspect_ratio():
    out = prepare_image(_img(2000, 1000), ImageLimits(max_side_px=1000))
    assert out.size == (1000, 500)


def test_converts_non_rgb_to_rgb():
    out = prepare_image(_img(100, 100, mode="L"), ImageLimits(max_side_px=None))
    assert out.mode == "RGB"


def test_respects_jpeg_quality():
    img = _img(64, 64)
    low = encode_image_jpeg(img, quality=10)
    high = encode_image_jpeg(img, quality=95)
    assert len(low) < len(high)
    # round-trip decodable
    Image.open(BytesIO(low)).verify()


def test_no_limit_means_no_resize():
    out = prepare_image(_img(3000, 3000), ImageLimits(max_side_px=None))
    assert out.size == (3000, 3000)
