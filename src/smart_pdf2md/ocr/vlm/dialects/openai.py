from __future__ import annotations

from typing import Any

from smart_pdf2md.errors import OcrBackendError

NAME = "openai_chat"
ENDPOINT = "/chat/completions"


def auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
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
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }


def parse_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise OcrBackendError("OpenAI response is not a JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise OcrBackendError("OpenAI response missing choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise OcrBackendError("OpenAI response missing message")
    content = message.get("content")
    if isinstance(content, str) and content:
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts)
    raise OcrBackendError("OpenAI response has no text content")


def parse_usage(payload: Any) -> tuple[int, int]:
    if not isinstance(payload, dict):
        return 0, 0
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return 0, 0
    return int(usage.get("prompt_tokens") or 0), int(
        usage.get("completion_tokens") or 0
    )
