"""Cycle 4: VLM model registry lookup, pricing tiers, fingerprint."""

from __future__ import annotations

from smart_pdf2md.ocr.opencode_pricing import _GO_RATES, estimate_cost_usd
from smart_pdf2md.ocr.vlm import registry as reg


def test_lookup_returns_spec_for_each_builtin_model():
    for model_id in _GO_RATES:
        spec = reg.lookup(model_id)
        assert spec is not None
        assert spec.id == model_id


def test_unknown_model_returns_none():
    assert reg.lookup("totally-unknown-model") is None


def test_estimate_cost_matches_legacy_go_rates():
    # Under the first-tier threshold, registry matches legacy shim rates.
    for model_id in _GO_RATES:
        legacy = estimate_cost_usd(model_id, 10_000, 2_000)
        via_reg = reg.estimate_cost_usd(model_id, 10_000, 2_000)
        assert via_reg == legacy


def test_pricing_tier_selected_by_input_tokens():
    # qwen3.6-plus has ≤256K and >256K tiers in registry
    low = reg.estimate_cost_usd("qwen3.6-plus", 1000, 0)
    high = reg.estimate_cost_usd("qwen3.6-plus", 300_000, 0)
    assert low is not None and high is not None
    assert high > low


def test_unknown_model_cost_is_none():
    assert reg.estimate_cost_usd("no-such-model", 100, 50) is None


def test_capability_defaults_are_conservative():
    spec = reg.lookup("qwen3.6-plus")
    assert spec is not None
    assert spec.capability.supports_vision is True
    assert spec.capability.max_output_tokens >= 8192
    assert spec.capability.dialect in {"anthropic_messages", "openai_chat"}


def test_fingerprint_changes_when_overlay_changes(tmp_path, monkeypatch):
    base = reg.registry_fingerprint()
    overlay = tmp_path / "models.toml"
    overlay.write_text(
        '[models."qwen3.6-plus"]\nlabel = "Qwen Renamed"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2MD_MODEL_REGISTRY", str(overlay))
    reg.reload_registry()
    try:
        assert reg.registry_fingerprint() != base
    finally:
        monkeypatch.delenv("PDF2MD_MODEL_REGISTRY", raising=False)
        reg.reload_registry()
