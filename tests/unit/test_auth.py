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


# ── escape / corruption ──────────────────────────────────────────────────────


def test_key_with_newline_survives_roundtrip(tmp_home):
    """Regression: previously a `\\n` in the key produced a TOML file that
    parsed as a broken multi-line string, bricking the config until manual fix.
    """
    weird = "sk-line1\nline2\rline3\twith-tab"
    auth_mod.save_to_config("claude", weird)
    assert auth_mod.load_from_config("claude") == weird


def test_key_with_nul_byte_survives_roundtrip(tmp_home):
    """NUL is invalid in TOML basic strings; must be \\u-escaped."""
    weird = "sk-with\x00nul"
    auth_mod.save_to_config("claude", weird)
    assert auth_mod.load_from_config("claude") == weird


def test_key_with_control_chars_survives_roundtrip(tmp_home):
    weird = "sk-\x01\x02\x1ftest"
    auth_mod.save_to_config("claude", weird)
    assert auth_mod.load_from_config("claude") == weird


def test_save_refuses_to_overwrite_unparseable_config(tmp_home):
    """If the existing config is corrupt, refuse to save — overwriting
    silently would drop other adapters' keys.
    """
    auth_mod.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    auth_mod.CONFIG_FILE.write_text("[[ this is broken")
    with pytest.raises(auth_mod.ConfigCorruptError):
        auth_mod.save_to_config("claude", "sk-new")
    # File contents preserved.
    assert "[[ this is broken" in auth_mod.CONFIG_FILE.read_text()
