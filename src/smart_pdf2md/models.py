from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PageResult:
    page: int
    markdown: str
    needs_ocr: bool = False
    ocr_reason: Optional[str] = None
    source: str = "native"


@dataclass
class ConversionResult:
    pdf_type: str
    confidence: float
    page_count: int
    pages: list[PageResult] = field(default_factory=list)
    pages_needing_ocr: list[int] = field(default_factory=list)
    markdown: str = ""
    processing_time_ms: int = 0
    has_encoding_issues: bool = False
    title: Optional[str] = None
