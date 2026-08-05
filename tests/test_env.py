"""Tests for .env loading and VLM model resolution."""

from __future__ import annotations

from pathlib import Path

import smart_pdf2md.env as env_mod
from smart_pdf2md.env import get_vlm_model, load_app_env


def _reset_env_loader(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(env_mod, "_LOADED", False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENCODE_VLM_MODEL", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)


def test_get_vlm_model_from_dotenv(monkeypatch, tmp_path: Path) -> None:
    _reset_env_loader(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text(
        "OPENCODE_VLM_MODEL=test-model\nOPENCODE_API_KEY=sk-from-dotenv\n",
        encoding="utf-8",
    )

    load_app_env()
    assert get_vlm_model() == "test-model"


def test_os_env_not_overridden_by_dotenv(monkeypatch, tmp_path: Path) -> None:
    _reset_env_loader(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENCODE_VLM_MODEL", "from-os")
    (tmp_path / ".env").write_text(
        "OPENCODE_VLM_MODEL=from-dotenv\n",
        encoding="utf-8",
    )

    load_app_env()
    assert get_vlm_model() == "from-os"


def test_get_vlm_model_default_when_unset(monkeypatch, tmp_path: Path) -> None:
    _reset_env_loader(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("OPENCODE_API_KEY=sk-x\n", encoding="utf-8")

    assert get_vlm_model() == "qwen3.6-plus"


def test_load_app_env_idempotent(monkeypatch, tmp_path: Path) -> None:
    _reset_env_loader(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text(
        "OPENCODE_VLM_MODEL=first\n",
        encoding="utf-8",
    )
    load_app_env()
    (tmp_path / ".env").write_text(
        "OPENCODE_VLM_MODEL=second\n",
        encoding="utf-8",
    )
    load_app_env()  # should no-op
    assert get_vlm_model() == "first"
