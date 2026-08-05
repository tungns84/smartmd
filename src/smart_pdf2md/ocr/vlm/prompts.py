from __future__ import annotations

# The "outer code fence" wording at the end is deliberate. An earlier version
# said only "do not wrap the answer in a code fence"; models generalised that
# into "never emit code fences at all" and returned every code listing as prose.
DEFAULT_OCR_PROMPT = """Transcribe this document page to Markdown.

Fidelity
- Reproduce the text exactly, in its original language. Never translate or paraphrase.
- Preserve every diacritic exactly, including Vietnamese tone marks.

Structure
- Choose heading levels from the document's logical hierarchy, not from font size. Cover text, publisher names and pull quotes set in large type are body text, not headings.
- Put code, configuration and terminal commands in a fenced code block tagged with the language (```python, ```bash, ```yaml, ```json). Keep line breaks and indentation exactly as printed.
- Callout labels and margin annotations pointing into a listing are not part of the code. Place them after the block as separate italic lines.
- Use a GitHub-flavoured Markdown table only for a real tabular grid. Never force a diagram, flowchart or figure into a table.
- For figures, diagrams, screenshots and photos, transcribe the printed caption only. Do not describe or invent their contents.

Omit
- Running headers, running footers and page numbers.

Return the page's Markdown on its own: no commentary, and no outer code fence wrapping the whole answer."""


def ocr_prompt(profile: str = "default") -> str:
    # Profiles share the same prompt today; postprocess differs by profile.
    _ = profile
    return DEFAULT_OCR_PROMPT
