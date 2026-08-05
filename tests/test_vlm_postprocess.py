"""Cycle 5: markdown postprocess."""

from __future__ import annotations

import unicodedata

from smart_pdf2md.ocr.vlm.postprocess import postprocess_markdown


def test_strips_markdown_fence():
    raw = "```markdown\n# Hello\n```"
    assert postprocess_markdown(raw) == "# Hello"


def test_normalizes_to_nfc():
    # cafe with combining acute vs precomposed
    decomposed = "cafe\u0301"
    out = postprocess_markdown(decomposed)
    assert out == unicodedata.normalize("NFC", decomposed)


def test_strips_model_lead_in_when_profile_says_so():
    raw = "Sure! Here is the transcription:\n\n# Title"
    assert postprocess_markdown(raw, prompt_profile="strip_lead_in").startswith("# Title")


def test_strips_reasoning_block():
    raw = "<think>\nThe page has a code listing.\n</think>\n# Title\n\nBody."
    assert postprocess_markdown(raw) == "# Title\n\nBody."


def test_strips_reasoning_block_before_unwrapping_fence():
    raw = "<thinking>plan</thinking>\n```markdown\n# Hello\n```"
    assert postprocess_markdown(raw) == "# Hello"


def test_keeps_think_word_that_is_not_a_tag():
    raw = "Ta think về điều đó.\n\n<!-- think -->"
    assert postprocess_markdown(raw) == raw


def test_leaves_clean_markdown_untouched():
    raw = "# Tiêu đề\n\nĐoạn văn."
    assert postprocess_markdown(raw) == raw
