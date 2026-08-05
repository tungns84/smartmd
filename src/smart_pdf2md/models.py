from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PageResult:
    page: int
    markdown: str
    needs_ocr: bool = False
    ocr_reason: Optional[str] = None
    source: str = "native"
    ocr_error: Optional[str] = None


@dataclass
class ConversionResult:
    pdf_type: str
    confidence: float
    page_count: int
    pages: list[PageResult] = field(default_factory=list)
    pages_needing_ocr: list[int] = field(default_factory=list)
    markdown: str = ""
    processing_time_ms: int = 0
    elapsed_ms: int = 0
    has_encoding_issues: bool = False
    title: Optional[str] = None
    cache_hits: int = 0
    cache_misses: int = 0
    ocr_input_tokens: int = 0
    ocr_output_tokens: int = 0
    ocr_cost_usd: Optional[float] = None
    empty_pages: list[int] = field(default_factory=list)
