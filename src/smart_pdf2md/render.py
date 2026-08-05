import os
from pathlib import Path
from typing import Optional

from pdf2image import convert_from_path

from smart_pdf2md.errors import PdfReadError

_IMAGE_CACHE: dict = {}


def resolve_poppler_path(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return explicit
    env = os.environ.get("PDF2MD_POPPLER_DIR") or os.environ.get("POPPLER_PATH")
    if env:
        return env
    repo = Path(__file__).resolve().parents[3]
    for root in (Path.cwd(), repo):
        candidates = sorted((root / "tools" / "poppler").glob("poppler-*/Library/bin"))
        if candidates:
            return str(candidates[-1])
    return None


def page_count_from_poppler(
    pdf_path: str | Path,
    *,
    poppler_path: Optional[str] = None,
) -> Optional[int]:
    """Page count via poppler ``pdfinfo`` — works when pdf-inspector returns 0."""
    try:
        from pdf2image import pdfinfo_from_path
    except ImportError:
        return None
    pop = resolve_poppler_path(poppler_path)
    try:
        info = pdfinfo_from_path(str(pdf_path), poppler_path=pop)
    except Exception:
        return None
    try:
        pages = int(info.get("Pages") or 0)
    except (TypeError, ValueError):
        return None
    return pages if pages > 0 else None


def _contiguous_groups(page_numbers: list[int]) -> list[list[int]]:
    groups: list[list[int]] = []
    for page in sorted(set(page_numbers)):
        if groups and page == groups[-1][-1] + 1:
            groups[-1].append(page)
        else:
            groups.append([page])
    return groups


def render_pages(
    pdf_path: str,
    page_numbers: list[int],
    dpi: int = 200,
    poppler_path: Optional[str] = None,
) -> dict[int, object]:
    pop = resolve_poppler_path(poppler_path)
    rendered: dict[int, object] = {}
    for group in _contiguous_groups(page_numbers):
        try:
            images = convert_from_path(
                pdf_path,
                dpi=dpi,
                first_page=group[0],
                last_page=group[-1],
                poppler_path=pop,
            )
        except Exception as exc:
            raise PdfReadError(f"Không render được trang {group[0]}-{group[-1]}: {exc}") from exc
        for offset, image in enumerate(images):
            page_number = group[0] + offset
            if page_number in page_numbers:
                rendered[page_number] = image
    return rendered
