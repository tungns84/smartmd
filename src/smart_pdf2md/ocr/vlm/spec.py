from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ImageLimits:
    max_side_px: Optional[int] = None
    jpeg_quality_default: int = 85


@dataclass(frozen=True)
class PricingTier:
    """``up_to_input_tokens == 0`` means no upper bound (catch-all / only tier)."""

    up_to_input_tokens: int
    input_usd_per_1m: float
    output_usd_per_1m: float


@dataclass(frozen=True)
class Pricing:
    tiers: tuple[PricingTier, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Capability:
    dialect: str
    supports_vision: bool = True
    max_output_tokens: int = 8192
    image: ImageLimits = field(default_factory=ImageLimits)
    prompt_profile: str = "default"
    fallback_model: Optional[str] = None


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    provider: str
    enabled: bool
    capability: Capability
    pricing: Pricing


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
