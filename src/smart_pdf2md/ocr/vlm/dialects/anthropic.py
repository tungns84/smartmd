from __future__ import annotations

from typing import Any

from smart_pdf2md.errors import OcrBackendError

NAME = "anthropic_messages"
ENDPOINT = "/messages"
_ANTHROPIC_VERSION = "2023-06-01"


def auth_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def build_payload(
    b64: str,
    model: str,
    max_tokens: int,
    prompt: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }


def parse_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise OcrBackendError("Anthropic response is not a JSON object")
    content = payload.get("content")
    if not isinstance(content, list):
        raise OcrBackendError("Anthropic response missing content list")
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    if not parts:
        raise OcrBackendError("Anthropic response has no text blocks")
    return "".join(parts)


def parse_usage(payload: Any) -> tuple[int, int]:
    if not isinstance(payload, dict):
        return 0, 0
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return 0, 0
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
