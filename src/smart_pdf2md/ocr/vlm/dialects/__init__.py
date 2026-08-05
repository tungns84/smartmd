from __future__ import annotations

from types import ModuleType

from smart_pdf2md.errors import OcrBackendError
from smart_pdf2md.ocr.vlm.dialects import anthropic, openai

_REGISTRY: dict[str, ModuleType] = {
    anthropic.NAME: anthropic,
    openai.NAME: openai,
}


def get_dialect(name: str) -> ModuleType:
    key = (name or "").strip().lower()
    mod = _REGISTRY.get(key)
    if mod is None:
        raise OcrBackendError(f"Unknown VLM dialect: {name!r}")
    return mod


def list_dialects() -> list[str]:
    return sorted(_REGISTRY)
