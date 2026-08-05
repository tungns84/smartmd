"""Load application env from `.env` (python-dotenv) without overriding OS env."""

from __future__ import annotations

import os

from dotenv import find_dotenv, load_dotenv

_LOADED = False
_DEFAULT_VLM_MODEL = "qwen3.6-plus"


def load_app_env() -> None:
    """Load `.env` from cwd (walk up) once. Existing OS env vars win (`override=False`)."""
    global _LOADED
    if _LOADED:
        return
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(dotenv_path=path, override=False)
    _LOADED = True


def get_vlm_model(default: str = _DEFAULT_VLM_MODEL) -> str:
    """Return `OPENCODE_VLM_MODEL` after ensuring `.env` is loaded."""
    load_app_env()
    value = (os.environ.get("OPENCODE_VLM_MODEL") or "").strip()
    return value or default
