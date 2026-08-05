"""Cycle 5: Anthropic / OpenAI dialect payloads and parsers."""

from __future__ import annotations

import pytest

from smart_pdf2md.errors import OcrBackendError
from smart_pdf2md.ocr.vlm.dialects import get_dialect
from smart_pdf2md.ocr.vlm.dialects import anthropic as anth
from smart_pdf2md.ocr.vlm.dialects import openai as oai


def test_anthropic_build_payload_has_image_then_text_block():
    payload = anth.build_payload("abc123", "qwen3.6-plus", 1024, "Transcribe")
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["data"] == "abc123"
    assert content[1]["type"] == "text"
    assert content[1]["text"] == "Transcribe"
    assert payload["model"] == "qwen3.6-plus"
    assert payload["max_tokens"] == 1024


def test_anthropic_auth_header_is_x_api_key():
    headers = anth.auth_headers("secret-key")
    assert headers["x-api-key"] == "secret-key"
    assert "Authorization" not in headers


def test_openai_build_payload_uses_image_url_data_uri():
    payload = oai.build_payload("abc123", "grok-4.5", 2048, "Hi")
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"] == "data:image/jpeg;base64,abc123"
    assert content[1]["type"] == "text"


def test_openai_auth_header_is_bearer():
    headers = oai.auth_headers("secret-key")
    assert headers["Authorization"] == "Bearer secret-key"


@pytest.mark.parametrize("mod", [anth, oai])
def test_parse_text_joins_text_blocks(mod):
    if mod is anth:
        data = {"content": [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]}
    else:
        data = {"choices": [{"message": {"content": "A B"}}]}
    text = mod.parse_text(data)
    assert "A" in text and "B" in text


@pytest.mark.parametrize("mod", [anth, oai])
def test_parse_usage_maps_native_field_names(mod):
    if mod is anth:
        data = {"usage": {"input_tokens": 11, "output_tokens": 22}}
    else:
        data = {"usage": {"prompt_tokens": 11, "completion_tokens": 22}}
    assert mod.parse_usage(data) == (11, 22)


@pytest.mark.parametrize("mod", [anth, oai])
def test_bad_schema_raises_ocr_backend_error(mod):
    with pytest.raises(OcrBackendError):
        mod.parse_text({"nope": True})


def test_registry_of_dialects_rejects_unknown_name():
    with pytest.raises(OcrBackendError):
        get_dialect("no-such-dialect")
