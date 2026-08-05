from __future__ import annotations

import hashlib
import json
from typing import Optional

from smart_pdf2md.ocr.vlm.overlay import apply_overlay
from smart_pdf2md.ocr.vlm.spec import (
    Capability,
    ImageLimits,
    ModelSpec,
    Pricing,
    PricingTier,
)

_BUILTIN: dict[str, ModelSpec] = {
    "qwen3.6-plus": ModelSpec(
        id="qwen3.6-plus",
        label="Qwen3.6 Plus",
        provider="opencode",
        enabled=True,
        capability=Capability(
            dialect="anthropic_messages",
            supports_vision=True,
            max_output_tokens=8192,
            image=ImageLimits(max_side_px=2048),
            prompt_profile="default",
            fallback_model="grok-4.5",
        ),
        pricing=Pricing(
            tiers=(
                PricingTier(256_000, 0.50, 3.00),
                PricingTier(0, 1.50, 9.00),
            )
        ),
    ),
    "qwen3.7-plus": ModelSpec(
        id="qwen3.7-plus",
        label="Qwen3.7 Plus",
        provider="opencode",
        enabled=True,
        capability=Capability(
            dialect="anthropic_messages",
            supports_vision=True,
            max_output_tokens=8192,
            image=ImageLimits(max_side_px=2048),
            prompt_profile="default",
            fallback_model="grok-4.5",
        ),
        pricing=Pricing(
            tiers=(
                PricingTier(256_000, 0.40, 1.60),
                PricingTier(0, 1.20, 4.80),
            )
        ),
    ),
    "minimax-m3": ModelSpec(
        id="minimax-m3",
        label="MiniMax M3",
        provider="opencode",
        enabled=True,
        capability=Capability(
            dialect="openai_chat",
            supports_vision=True,
            max_output_tokens=8192,
            image=ImageLimits(max_side_px=2048),
            prompt_profile="default",
            fallback_model=None,
        ),
        pricing=Pricing(tiers=(PricingTier(0, 0.30, 1.20),)),
    ),
    "grok-4.5": ModelSpec(
        id="grok-4.5",
        label="Grok 4.5",
        provider="opencode",
        enabled=True,
        capability=Capability(
            dialect="openai_chat",
            supports_vision=True,
            max_output_tokens=8192,
            image=ImageLimits(max_side_px=2048),
            prompt_profile="default",
            fallback_model=None,
        ),
        pricing=Pricing(tiers=(PricingTier(0, 2.00, 6.00),)),
    ),
    "mimo-v2.5": ModelSpec(
        id="mimo-v2.5",
        label="MiMo v2.5",
        provider="opencode",
        enabled=True,
        capability=Capability(
            dialect="openai_chat",
            supports_vision=True,
            max_output_tokens=8192,
            image=ImageLimits(max_side_px=2048),
            prompt_profile="default",
            fallback_model=None,
        ),
        pricing=Pricing(tiers=(PricingTier(0, 0.14, 0.28),)),
    ),
    "hy3": ModelSpec(
        id="hy3",
        label="HY3",
        provider="opencode",
        enabled=True,
        capability=Capability(
            dialect="openai_chat",
            supports_vision=True,
            max_output_tokens=8192,
            image=ImageLimits(max_side_px=2048),
            prompt_profile="default",
            fallback_model=None,
        ),
        pricing=Pricing(tiers=(PricingTier(0, 0.14, 0.58),)),
    ),
}

_models: dict[str, ModelSpec] = dict(_BUILTIN)
_overlay_digest: str = ""


def _select_tier(pricing: Pricing, input_tokens: int) -> Optional[PricingTier]:
    if not pricing.tiers:
        return None
    bounded = [t for t in pricing.tiers if t.up_to_input_tokens > 0]
    unbounded = [t for t in pricing.tiers if t.up_to_input_tokens == 0]
    for tier in sorted(bounded, key=lambda t: t.up_to_input_tokens):
        if input_tokens <= tier.up_to_input_tokens:
            return tier
    if unbounded:
        return unbounded[0]
    return bounded[-1] if bounded else None


def lookup(model_id: str) -> Optional[ModelSpec]:
    key = (model_id or "").strip().lower()
    if not key:
        return None
    return _models.get(key)


def list_models(*, enabled_only: bool = False) -> list[ModelSpec]:
    specs = list(_models.values())
    if enabled_only:
        specs = [s for s in specs if s.enabled]
    return sorted(specs, key=lambda s: s.id)


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    spec = lookup(model)
    if spec is None:
        return None
    tier = _select_tier(spec.pricing, int(input_tokens))
    if tier is None:
        return None
    return (
        input_tokens * tier.input_usd_per_1m
        + output_tokens * tier.output_usd_per_1m
    ) / 1_000_000


def registry_fingerprint() -> str:
    payload = {
        "overlay": _overlay_digest,
        "models": {
            mid: {
                "label": s.label,
                "enabled": s.enabled,
                "dialect": s.capability.dialect,
                "fallback": s.capability.fallback_model,
                "tiers": [
                    {
                        "up_to": t.up_to_input_tokens,
                        "in": t.input_usd_per_1m,
                        "out": t.output_usd_per_1m,
                    }
                    for t in s.pricing.tiers
                ],
            }
            for mid, s in sorted(_models.items())
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def reload_registry() -> None:
    global _models, _overlay_digest
    merged, digest = apply_overlay(_BUILTIN)
    _models = merged
    _overlay_digest = digest
    # #region agent log
    try:
        import json as _json, time as _time, os as _os
        from pathlib import Path as _Path
        _payload = _json.dumps({"sessionId":"ade562","hypothesisId":"B_C","location":"registry.py:reload_registry","message":"registry reloaded","data":{"overlay_digest":digest,"enabled":sorted(s.id for s in _models.values() if s.enabled),"disabled":sorted(s.id for s in _models.values() if not s.enabled),"count_enabled":sum(1 for s in _models.values() if s.enabled)},"timestamp":int(_time.time()*1000)})+"\n"
        for _log in ("debug-ade562.log", "/data/web/debug-ade562.log"):
            try:
                _Path(_log).parent.mkdir(parents=True, exist_ok=True)
                with open(_log, "a", encoding="utf-8") as _f:
                    _f.write(_payload)
            except Exception:
                pass
    except Exception:
        pass
    # #endregion


# Apply overlay (if any) at import time.
reload_registry()
