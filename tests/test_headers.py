from smart_pdf2md.headers import normalize_line, strip_running_headers
from smart_pdf2md.models import PageResult


def test_normalize_strips_emphasis_digits_and_case():
    assert normalize_line("**Chapter 12**") == "chapter"
    assert normalize_line("  AI Agents in Action  ") == "ai agents in action"


def test_strip_skips_short_documents():
    pages = [
        PageResult(page=i, markdown=f"Header\n\nBody {i}", source="ocr")
        for i in range(3)
    ]
    result = strip_running_headers(pages)
    assert result.removed_lines == 0
    assert result.pages[0].markdown.startswith("Header")


def test_strip_removes_frequent_header_and_page_number():
    pages = []
    for i in range(10):
        # Letter suffix keeps body unique after digit stripping.
        md = (
            f"AI Agents in Action\n\n"
            f"Unique body {chr(65 + i)} with enough text here.\n\n"
            f"More paragraphs so edges are only header/footer.\n\n"
            f"{i + 1}\n"
        )
        pages.append(PageResult(page=i, markdown=md, source="ocr"))
    result = strip_running_headers(pages)
    assert result.removed_lines >= 10
    assert "AI Agents in Action" not in result.pages[0].markdown
    assert "Unique body A" in result.pages[0].markdown


def test_strip_handles_alternating_headers():
    pages = []
    for i in range(10):
        header = "Book Title" if i % 2 == 0 else "Chapter One"
        pages.append(
            PageResult(
                page=i,
                markdown=f"{header}\n\nContent {i}\n",
                source="ocr",
            )
        )
    result = strip_running_headers(pages)
    assert result.removed_lines >= 10
    for page in result.pages:
        assert "Book Title" not in page.markdown
        assert "Chapter One" not in page.markdown
