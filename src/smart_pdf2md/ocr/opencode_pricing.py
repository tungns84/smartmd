"""OpenCode Go model rates — shim over ``ocr.vlm.registry`` builtins.

``_GO_RATES`` and ``estimate_cost_usd`` keep the historical first-tier behavior
so existing callers/tests stay stable. Tier-aware pricing lives in
``smart_pdf2md.ocr.vlm.registry.estimate_cost_usd``.
"""

from __future__ import annotations

from smart_pdf2md.ocr.vlm.registry import list_models


def _go_rates_from_registry() -> dict[str, tuple[float, float]]:
    rates: dict[str, tuple[float, float]] = {}
    for spec in list_models():
        if not spec.pricing.tiers:
            continue
        tier = spec.pricing.tiers[0]
        rates[spec.id] = (tier.input_usd_per_1m, tier.output_usd_per_1m)
    return rates


# model_id -> (input_usd_per_1m, output_usd_per_1m)
_GO_RATES: dict[str, tuple[float, float]] = _go_rates_from_registry()


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    """Estimate USD cost using the first pricing tier (legacy Go rates)."""
    rates = _GO_RATES.get((model or "").strip().lower())
    if rates is None:
        return None
    in_rate, out_rate = rates
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
