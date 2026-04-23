"""Tests for axor_cli.auth — API key management."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from axor_cli import auth as auth_mod


# ── resolve_api_key priority chain ────────────────────────────────────────────


def test_flag_key_has_highest_priority(tmp_home, monkeypatch):
    """CLI flag wins over env var and config file."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    auth_mod.save_to_config("claude", "config-key")

    result = auth_mod.resolve_api_key("claude", flag_key="flag-key")
    assert result == "flag-key"


def test_env_var_wins_over_config(tmp_home, monkeypatch):
    """Env var wins over config file."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    auth_mod.save_to_config("claude", "config-key")

    result = auth_mod.resolve_api_key("claude")
    assert result == "env-key"


def test_config_file_used_when_no_env(tmp_home, monkeypatch):
    """Config file used when no flag and no env var."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    auth_mod.save_to_config("claude", "config-key")

    result = auth_mod.resolve_api_key("claude")
    assert result == "config-key"


def test_returns_none_when_nothing_found(tmp_home, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = auth_mod.resolve_api_key("claude")
    assert result is None


# ── save / load / clear ───────────────────────────────────────────────────────


def test_save_and_load_roundtrip(tmp_home):
    auth_mod.save_to_config("claude", "sk-test-123")
    loaded = auth_mod.load_from_config("claude")
    assert loaded == "sk-test-123"


def test_save_creates_config_dir(tmp_home):
    # remove the dir created by fixture
    config_dir = auth_mod.CONFIG_DIR
    config_file = auth_mod.CONFIG_FILE
    if config_file.exists():
        config_file.unlink()
    if config_dir.exists():
        config_dir.rmdir()

    auth_mod.save_to_config("claude", "sk-new")
    assert config_file.exists()


def test_clear_removes_adapter(tmp_home):
    auth_mod.save_to_config("claude", "sk-remove")
    assert auth_mod.load_from_config("claude") == "sk-remove"

    cleared = auth_mod.clear_from_config("claude")
    assert cleared is True
    assert auth_mod.load_from_config("claude") is None


def test_clear_nonexistent_returns_false(tmp_home):
    assert auth_mod.clear_from_config("nonexistent") is False


def test_multiple_adapters_coexist(tmp_home):
    auth_mod.save_to_config("claude", "sk-claude")
    auth_mod.save_to_config("openai", "sk-openai")

    assert auth_mod.load_from_config("claude") == "sk-claude"
    assert auth_mod.load_from_config("openai") == "sk-openai"


# ── TOML escaping ─────────────────────────────────────────────────────────────


def test_key_with_quotes_survives_roundtrip(tmp_home):
    """API key containing double quotes should not corrupt config."""
    key = 'sk-test-with"quotes"inside'
    auth_mod.save_to_config("claude", key)
    loaded = auth_mod.load_from_config("claude")
    assert loaded == key


def test_key_with_backslash_survives_roundtrip(tmp_home):
    key = "sk-test-with\\backslash"
    auth_mod.save_to_config("claude", key)
    loaded = auth_mod.load_from_config("claude")
    assert loaded == key


# ── File permissions ──────────────────────────────────────────────────────────


def test_config_file_has_600_permissions(tmp_home):
    auth_mod.save_to_config("claude", "sk-secret")
    mode = auth_mod.CONFIG_FILE.stat().st_mode & 0o777
    assert mode == 0o600


# ── load_from_config edge cases ───────────────────────────────────────────────


def test_load_missing_file_returns_none(tmp_home):
    assert auth_mod.load_from_config("claude") is None


def test_load_corrupted_file_returns_none(tmp_home):
    auth_mod.CONFIG_FILE.write_text("not valid [[[ toml")
    result = auth_mod.load_from_config("claude")
    assert result is None
