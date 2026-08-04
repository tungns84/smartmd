import re

from smart_pdf2md.errors import MergeError
from smart_pdf2md.models import PageResult

_MULTI_BLANK_LINES = re.compile(r"\n{3,}")


def merge_pages(
    pages: list[PageResult],
    *,
    page_markers: bool = True,
    compact: bool = False,
) -> str:
    if not pages:
        raise MergeError("Không có trang nào để merge")

    blocks: list[str] = []
    for page in pages:
        markdown = page.markdown.strip()
        if not markdown:
            continue
        if page_markers:
            blocks.append(f"<!-- Page {page.page + 1} -->\n\n{markdown}")
        else:
            blocks.append(markdown)

    if not blocks:
        return ""

    merged = "\n\n".join(blocks)
    if compact:
        merged = _MULTI_BLANK_LINES.sub("\n\n", merged)
    return merged.rstrip() + "\n"
