from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Options:
    languages: list[str] = field(default_factory=lambda: ["vi", "en"])
    dpi: int = 200
    compact: bool = False
    force_ocr: bool = False
    show_progress: bool = True
    page_markers: bool = True
    ocr_backend: str = "opencode"
    poppler_path: Optional[str] = None
    vlm_model: str = "qwen3.6-plus"
    vlm_jpeg_quality: int = 85
    vlm_max_tokens: int = 8192
    use_cache: bool = True
    allow_vlm_fallback: bool = True
    strip_headers: bool = True
    concurrency: int = 4
