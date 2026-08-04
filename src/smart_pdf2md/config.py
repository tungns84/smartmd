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
    ocr_backend: str = "surya"
    poppler_path: Optional[str] = None