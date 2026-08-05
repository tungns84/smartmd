from smart_pdf2md.ocr.opencode_pricing import estimate_cost_usd


def test_estimate_qwen36_plus_math():
    # 77_600 in @ $0.50/1M + 27_100 out @ $3.00/1M
    cost = estimate_cost_usd("qwen3.6-plus", 77_600, 27_100)
    assert cost is not None
    assert abs(cost - (77_600 * 0.50 + 27_100 * 3.00) / 1_000_000) < 1e-12


def test_estimate_grok_fallback_rates():
    cost = estimate_cost_usd("grok-4.5", 1000, 500)
    assert cost == (1000 * 2.00 + 500 * 6.00) / 1_000_000


def test_estimate_case_insensitive():
    assert estimate_cost_usd("Qwen3.7-Plus", 1_000_000, 0) == 0.40


def test_estimate_unknown_model_returns_none():
    assert estimate_cost_usd("totally-unknown-model", 100, 50) is None


def test_estimate_cheap_candidates():
    assert estimate_cost_usd("mimo-v2.5", 1_000_000, 0) == 0.14
    assert estimate_cost_usd("hy3", 0, 1_000_000) == 0.58
    assert estimate_cost_usd("minimax-m3", 1_000_000, 1_000_000) == 0.30 + 1.20
