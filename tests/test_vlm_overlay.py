"""Cycle 4: TOML overlay for commercial fields only."""

from __future__ import annotations

import logging

from smart_pdf2md.ocr.vlm import registry as reg


def test_overlay_absent_falls_back_to_builtin(monkeypatch):
    monkeypatch.delenv("PDF2MD_MODEL_REGISTRY", raising=False)
    reg.reload_registry()
    assert reg.lookup("grok-4.5") is not None


def test_overlay_overrides_pricing_only(tmp_path, monkeypatch):
    path = tmp_path / "reg.toml"
    path.write_text(
        '[models."mimo-v2.5"]\n'
        "label = \"MiMo Cheap\"\n"
        "[[models.mimo-v2.5.pricing.tiers]]\n"
        "up_to_input_tokens = 0\n"
        "input_usd_per_1m = 0.01\n"
        "output_usd_per_1m = 0.02\n",
        encoding="utf-8",
    )
    # Use nested table form that's easier:
    path.write_text(
        """
[models."mimo-v2.5"]
label = "MiMo Cheap"
enabled = true

[[models."mimo-v2.5".pricing.tiers]]
up_to_input_tokens = 0
input_usd_per_1m = 0.01
output_usd_per_1m = 0.02
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2MD_MODEL_REGISTRY", str(path))
    reg.reload_registry()
    try:
        spec = reg.lookup("mimo-v2.5")
        assert spec is not None
        assert spec.label == "MiMo Cheap"
        assert reg.estimate_cost_usd("mimo-v2.5", 1_000_000, 0) == 0.01
        # capability untouched
        assert spec.capability.dialect == "openai_chat"
    finally:
        monkeypatch.delenv("PDF2MD_MODEL_REGISTRY", raising=False)
        reg.reload_registry()


def test_overlay_cannot_change_dialect(tmp_path, monkeypatch, caplog):
    path = tmp_path / "reg.toml"
    path.write_text(
        """
[models."mimo-v2.5"]
dialect = "anthropic_messages"
label = "Hacked"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2MD_MODEL_REGISTRY", str(path))
    with caplog.at_level(logging.WARNING):
        reg.reload_registry()
    try:
        spec = reg.lookup("mimo-v2.5")
        assert spec is not None
        assert spec.capability.dialect == "openai_chat"
        assert spec.label == "Hacked"
        assert any("dialect" in r.message.lower() for r in caplog.records)
    finally:
        monkeypatch.delenv("PDF2MD_MODEL_REGISTRY", raising=False)
        reg.reload_registry()


def test_overlay_new_model_via_inherits(tmp_path, monkeypatch):
    path = tmp_path / "reg.toml"
    path.write_text(
        """
[models."my-grok-clone"]
inherits = "grok-4.5"
label = "Grok Clone"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2MD_MODEL_REGISTRY", str(path))
    reg.reload_registry()
    try:
        spec = reg.lookup("my-grok-clone")
        assert spec is not None
        assert spec.capability.dialect == "openai_chat"
        assert spec.label == "Grok Clone"
    finally:
        monkeypatch.delenv("PDF2MD_MODEL_REGISTRY", raising=False)
        reg.reload_registry()


def test_overlay_new_model_without_inherits_is_rejected(tmp_path, monkeypatch, caplog):
    path = tmp_path / "reg.toml"
    path.write_text(
        """
[models."brand-new"]
label = "Nope"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2MD_MODEL_REGISTRY", str(path))
    with caplog.at_level(logging.WARNING):
        reg.reload_registry()
    try:
        assert reg.lookup("brand-new") is None
    finally:
        monkeypatch.delenv("PDF2MD_MODEL_REGISTRY", raising=False)
        reg.reload_registry()


def test_malformed_toml_logs_and_uses_builtin(tmp_path, monkeypatch, caplog):
    path = tmp_path / "reg.toml"
    path.write_text("{{{not toml", encoding="utf-8")
    monkeypatch.setenv("PDF2MD_MODEL_REGISTRY", str(path))
    with caplog.at_level(logging.WARNING):
        reg.reload_registry()
    try:
        assert reg.lookup("grok-4.5") is not None
    finally:
        monkeypatch.delenv("PDF2MD_MODEL_REGISTRY", raising=False)
        reg.reload_registry()


def test_negative_price_rejected(tmp_path, monkeypatch, caplog):
    path = tmp_path / "reg.toml"
    path.write_text(
        """
[models."mimo-v2.5"]
[[models."mimo-v2.5".pricing.tiers]]
up_to_input_tokens = 0
input_usd_per_1m = -1
output_usd_per_1m = 0.02
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2MD_MODEL_REGISTRY", str(path))
    with caplog.at_level(logging.WARNING):
        reg.reload_registry()
    try:
        # keeps builtin rate
        assert reg.estimate_cost_usd("mimo-v2.5", 1_000_000, 0) == 0.14
    finally:
        monkeypatch.delenv("PDF2MD_MODEL_REGISTRY", raising=False)
        reg.reload_registry()


def test_missing_toml_parser_skips_overlay(tmp_path, monkeypatch):
    path = tmp_path / "reg.toml"
    path.write_text(
        '[models."mimo-v2.5"]\nlabel = "Should Not Apply"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PDF2MD_MODEL_REGISTRY", str(path))
    monkeypatch.setattr(
        "smart_pdf2md.ocr.vlm.overlay._load_toml_module",
        lambda: None,
    )
    reg.reload_registry()
    try:
        spec = reg.lookup("mimo-v2.5")
        assert spec is not None
        assert spec.label != "Should Not Apply"
    finally:
        monkeypatch.delenv("PDF2MD_MODEL_REGISTRY", raising=False)
        reg.reload_registry()
