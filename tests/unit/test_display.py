"""Tests for axor_cli.display — terminal output helpers."""
from __future__ import annotations

import os
import threading
import time

import pytest


def test_no_color_env_disables_colors(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    # reimport to pick up env change
    from axor_cli import display
    monkeypatch.setattr(display, "_COLOR", display._supports_color())
    assert display._COLOR is False


def test_spinner_starts_and_stops(monkeypatch):
    from axor_cli import display
    from axor_cli.display import Spinner
    monkeypatch.setattr(display, "_COLOR", True)
    s = Spinner(prefix="test ")
    s.start()
    time.sleep(0.1)
    assert s._thread is not None
    s.stop()
    # thread should be joined and cleared
    assert s._thread is None


def test_spinner_stop_event_is_set():
    from axor_cli.display import Spinner
    s = Spinner()
    s.start()
    time.sleep(0.05)
    s.stop()
    assert s._stop_event.is_set()


def test_spinner_double_stop_safe():
    from axor_cli.display import Spinner
    s = Spinner()
    s.start()
    s.stop()
    s.stop()  # should not raise


def test_dim_returns_string():
    from axor_cli.display import dim
    result = dim("hello")
    assert "hello" in result


def test_format_args_truncates():
    from axor_cli.display import _format_args
    args = {"a": "x" * 50, "b": "y", "c": "z"}
    result = _format_args(args)
    assert "…" in result  # 3 args → shows 2 + ellipsis
