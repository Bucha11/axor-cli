"""Shared fixtures for axor-cli tests."""
from __future__ import annotations

import sys
import os
from pathlib import Path

import pytest

# ensure axor-core and axor-claude importable from source
for _candidate in [
    os.path.join(os.path.dirname(__file__), "..", "..", "axor-core"),
    os.path.join(os.path.dirname(__file__), "..", "..", "axor-claude"),
]:
    _abs = os.path.abspath(_candidate)
    if os.path.isdir(_abs) and _abs not in sys.path:
        sys.path.insert(0, _abs)


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """
    Redirect ~/.axor/config.toml to a temp dir for test isolation.
    Returns the temp config directory Path.
    """
    import axor_cli.auth as auth_mod
    config_dir  = tmp_path / ".axor"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"

    monkeypatch.setattr(auth_mod, "CONFIG_DIR",  config_dir)
    monkeypatch.setattr(auth_mod, "CONFIG_FILE", config_file)

    return config_dir


from unittest.mock import MagicMock
import sys

@pytest.fixture(autouse=True)
def mock_anthropic_sdk():
    """
    Mock the anthropic SDK for tests that don't need real API calls.
    Prevents ImportError when anthropic package is not installed.
    """
    if 'anthropic' not in sys.modules:
        mock = MagicMock()
        mock.AsyncAnthropic = MagicMock(return_value=MagicMock())
        sys.modules['anthropic'] = mock
        yield mock
        del sys.modules['anthropic']
    else:
        yield sys.modules['anthropic']
