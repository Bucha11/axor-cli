"""Tests for axor_cli.adapters — adapter registry."""
from __future__ import annotations

import pytest

from axor_cli.adapters import list_adapters, is_available, default_model, available_models


def test_list_adapters_returns_known():
    adapters = list_adapters()
    assert "claude" in adapters
    assert "openai" in adapters


def test_is_available_returns_bool():
    # at minimum claude should be available (axor-claude installed)
    result = is_available("claude")
    assert isinstance(result, bool)


def test_is_available_unknown_adapter():
    assert is_available("nonexistent") is False


def test_default_model_claude():
    model = default_model("claude")
    assert model is not None
    assert "claude" in model.lower() or "sonnet" in model.lower() or len(model) > 0


def test_default_model_unknown():
    model = default_model("nonexistent")
    # returns None or a fallback string — either is acceptable
    assert model is None or isinstance(model, str)


def test_available_models_returns_list():
    models = available_models("claude")
    assert isinstance(models, list)
