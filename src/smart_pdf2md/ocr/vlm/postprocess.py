from __future__ import annotations

import re
import unicodedata

# Reasoning models emit their chain of thought before the transcription.
_THINK_RE = re.compile(r"<(think|thinking)>[\s\S]*?</\1>", re.IGNORECASE)
_STRAY_THINK_TAG_RE = re.compile(r"</?(?:think|thinking)>", re.IGNORECASE)

_FENCE_RE = re.compile(
    r"^\s*```(?:markdown|md)?\s*\n([\s\S]*?)\n```\s*$",
    re.IGNORECASE,
)

_LEAD_IN_RE = re.compile(
    r"^(?:sure[!.,]?\s*)?(?:here (?:is|are) (?:the )?(?:transcription|markdown|result)[:\s]*)+",
    re.IGNORECASE,
)


def postprocess_markdown(text: str, *, prompt_profile: str = "default") -> str:
    raw = (text or "").strip()
    raw = _STRAY_THINK_TAG_RE.sub("", _THINK_RE.sub("", raw)).strip()
    match = _FENCE_RE.match(raw)
    if match:
        raw = match.group(1).strip()
    raw = unicodedata.normalize("NFC", raw)
    if prompt_profile == "strip_lead_in":
        raw = _LEAD_IN_RE.sub("", raw).lstrip()
    return raw
