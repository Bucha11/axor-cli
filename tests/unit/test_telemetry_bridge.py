"""Tests for axor_cli.telemetry bridge."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from axor_cli import telemetry as bridge


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """Redirect HOME + AXOR envs so bridge tests never touch the real FS."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AXOR_NO_BANNER", raising=False)
    monkeypatch.delenv("AXOR_TELEMETRY", raising=False)
    from axor_telemetry import config as tcfg
    monkeypatch.setattr(tcfg, "_CONFIG_PATH", tmp_path / ".axor" / "config.toml")
    monkeypatch.setattr(bridge, "_MARKER_PATH", tmp_path / ".axor" / ".telemetry_notice_shown")
    return tmp_path


def test_current_mode_off_when_no_config():
    assert bridge.current_mode() == "off"


def test_build_pipeline_returns_none_when_off():
    assert bridge.build_pipeline() is None


def test_build_pipeline_returns_pipeline_when_local(monkeypatch, _isolate_home):
    from axor_telemetry import TelemetryConfig, TelemetryMode
    cfg = TelemetryConfig(
        mode=TelemetryMode.LOCAL,
        queue_path=str(_isolate_home / "q.jsonl"),
    )
    cfg.write()
    pipe = bridge.build_pipeline(axor_version="0.9.0")
    assert pipe is not None
    assert pipe.enabled is True


def test_banner_shows_once_and_writes_marker(_isolate_home):
    stream = io.StringIO()
    bridge.maybe_show_first_run_banner(stream=stream)
    out = stream.getvalue()
    assert "telemetry is off" in out
    assert bridge._MARKER_PATH.is_file()
    # second call is a no-op
    stream2 = io.StringIO()
    bridge.maybe_show_first_run_banner(stream=stream2)
    assert stream2.getvalue() == ""


def test_banner_suppressed_by_env(monkeypatch, _isolate_home):
    monkeypatch.setenv("AXOR_NO_BANNER", "1")
    stream = io.StringIO()
    bridge.maybe_show_first_run_banner(stream=stream)
    assert stream.getvalue() == ""
    assert not bridge._MARKER_PATH.is_file()


def test_banner_suppressed_when_telemetry_enabled(_isolate_home):
    from axor_telemetry import TelemetryConfig, TelemetryMode
    TelemetryConfig(mode=TelemetryMode.LOCAL).write()
    stream = io.StringIO()
    bridge.maybe_show_first_run_banner(stream=stream)
    assert stream.getvalue() == ""


def test_slash_status(_isolate_home):
    stream = io.StringIO()
    rc = bridge.handle_slash("/telemetry", stream=stream)
    assert rc == 0
    assert "mode:" in stream.getvalue()


def test_slash_on_writes_config(_isolate_home):
    stream = io.StringIO()
    rc = bridge.handle_slash("/telemetry on", stream=stream)
    assert rc == 0
    assert bridge.current_mode() == "local"


def test_slash_on_remote(_isolate_home):
    stream = io.StringIO()
    rc = bridge.handle_slash("/telemetry on --remote", stream=stream)
    assert rc == 0
    assert bridge.current_mode() == "remote"


def test_slash_off(_isolate_home):
    from axor_telemetry import TelemetryConfig, TelemetryMode
    TelemetryConfig(mode=TelemetryMode.LOCAL).write()
    stream = io.StringIO()
    rc = bridge.handle_slash("/telemetry off", stream=stream)
    assert rc == 0
    assert bridge.current_mode() == "off"


def test_slash_unknown_subcommand_returns_nonzero(_isolate_home):
    stream = io.StringIO()
    rc = bridge.handle_slash("/telemetry zxcv", stream=stream)
    assert rc == 2
    assert "unknown subcommand" in stream.getvalue()
