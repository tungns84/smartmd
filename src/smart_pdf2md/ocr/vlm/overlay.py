from __future__ import annotations

import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

from smart_pdf2md.ocr.vlm.spec import ModelSpec, Pricing, PricingTier

logger = logging.getLogger(__name__)

# Capability keys that overlays must not change.
_CAPABILITY_KEYS = frozenset(
    {
        "dialect",
        "supports_vision",
        "max_output_tokens",
        "image",
        "prompt_profile",
        "fallback_model",
        "capability",
    }
)


def _load_toml_module():
    try:
        import tomllib  # py311+

        return tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore

            return tomllib
        except ImportError:
            return None


def _parse_tiers(raw_tiers: Any) -> Optional[tuple[PricingTier, ...]]:
    if not isinstance(raw_tiers, list) or not raw_tiers:
        return None
    tiers: list[PricingTier] = []
    for item in raw_tiers:
        if not isinstance(item, dict):
            return None
        try:
            up_to = int(item.get("up_to_input_tokens", 0))
            inp = float(item["input_usd_per_1m"])
            out = float(item["output_usd_per_1m"])
        except (KeyError, TypeError, ValueError):
            return None
        if inp < 0 or out < 0:
            logger.warning("Overlay pricing rejected: negative rate %s", item)
            return None
        tiers.append(PricingTier(up_to, inp, out))
    return tuple(tiers)


def _apply_commercial(base: ModelSpec, patch: dict[str, Any]) -> ModelSpec:
    label = str(patch["label"]) if "label" in patch else base.label
    enabled = bool(patch["enabled"]) if "enabled" in patch else base.enabled
    pricing = base.pricing
    pricing_raw = patch.get("pricing")
    if isinstance(pricing_raw, dict) and "tiers" in pricing_raw:
        parsed = _parse_tiers(pricing_raw["tiers"])
        if parsed is not None:
            pricing = Pricing(tiers=parsed)
    return ModelSpec(
        id=base.id,
        label=label,
        provider=base.provider,
        enabled=enabled,
        capability=base.capability,
        pricing=pricing,
    )


def apply_overlay(
    builtin: dict[str, ModelSpec],
) -> tuple[dict[str, ModelSpec], str]:
    """Merge PDF2MD_MODEL_REGISTRY TOML into a copy of builtin models.

    Returns (models, overlay_digest). Digest is empty when no overlay applied.
    """
    models = {k: deepcopy(v) for k, v in builtin.items()}
    path_raw = (os.environ.get("PDF2MD_MODEL_REGISTRY") or "").strip()
    # #region agent log
    try:
        import json as _json, time as _time
        _p = Path(path_raw) if path_raw else None
        _payload = _json.dumps({"sessionId":"ade562","hypothesisId":"A_C","location":"overlay.py:apply_overlay","message":"overlay entry","data":{"path_raw":path_raw,"cwd":os.getcwd(),"path_is_file":bool(_p and _p.is_file()),"path_resolved":str(_p.resolve()) if _p and path_raw else None,"env_has_key":"PDF2MD_MODEL_REGISTRY" in os.environ,"listdir_app":sorted(os.listdir("/app"))[:40] if os.path.isdir("/app") else None},"timestamp":int(_time.time()*1000)})+"\n"
        for _log in ("debug-ade562.log", "/data/web/debug-ade562.log"):
            try:
                Path(_log).parent.mkdir(parents=True, exist_ok=True)
                with open(_log, "a", encoding="utf-8") as _f:
                    _f.write(_payload)
            except Exception:
                pass
    except Exception:
        pass
    # #endregion
    if not path_raw:
        return models, ""

    path = Path(path_raw)
    if not path.is_file():
        logger.warning("PDF2MD_MODEL_REGISTRY not found: %s", path)
        # #region agent log
        try:
            import json as _json, time as _time
            _payload = _json.dumps({"sessionId":"ade562","hypothesisId":"A","location":"overlay.py:missing_file","message":"overlay file missing","data":{"path":str(path),"cwd":os.getcwd()},"timestamp":int(_time.time()*1000)})+"\n"
            for _log in ("debug-ade562.log", "/data/web/debug-ade562.log"):
                try:
                    Path(_log).parent.mkdir(parents=True, exist_ok=True)
                    with open(_log, "a", encoding="utf-8") as _f:
                        _f.write(_payload)
                except Exception:
                    pass
        except Exception:
            pass
        # #endregion
        return models, ""

    tomllib = _load_toml_module()
    if tomllib is None:
        logger.warning(
            "No TOML parser available (tomllib/tomli); skipping model registry overlay"
        )
        return models, ""

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Malformed model registry TOML (%s): %s", path, exc)
        return models, ""

    raw_models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(raw_models, dict):
        return models, path.read_bytes().hex()[:32]

    for model_id, patch in raw_models.items():
        if not isinstance(patch, dict):
            continue
        key = str(model_id).strip().lower()
        for banned in _CAPABILITY_KEYS:
            if banned in patch:
                logger.warning(
                    "Overlay ignored capability field %r for model %s",
                    banned,
                    key,
                )

        if key in models:
            models[key] = _apply_commercial(models[key], patch)
            continue

        inherits = patch.get("inherits")
        if not inherits:
            logger.warning(
                "Overlay new model %s rejected: missing inherits", key
            )
            continue
        parent = models.get(str(inherits).strip().lower())
        if parent is None:
            logger.warning(
                "Overlay new model %s rejected: unknown inherits %r",
                key,
                inherits,
            )
            continue
        cloned = ModelSpec(
            id=key,
            label=parent.label,
            provider=parent.provider,
            enabled=parent.enabled,
            capability=parent.capability,
            pricing=parent.pricing,
        )
        models[key] = _apply_commercial(cloned, patch)

    digest = hashlib_file(path)
    return models, digest


def hashlib_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
