"""
axor-cli <-> axor-telemetry bridge.

Keeps axor-telemetry as an optional dependency: everything here no-ops when
the package is not importable. The REPL and startup never see exceptions
from the telemetry path.

Responsibilities:
  - Resolve TelemetryConfig from ~/.axor/config.toml + env.
  - Build a TelemetryPipeline when mode != off.
  - Show a one-time stderr banner if telemetry is off and no marker exists,
    so users discover the opt-in without being prompted mid-session.
  - Run `/telemetry` CLI-side subcommands (status / on / off / preview).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_MARKER_PATH = Path.home() / ".axor" / ".telemetry_notice_shown"


def _is_importable() -> bool:
    try:
        import axor_telemetry  # noqa: F401
        return True
    except ImportError:
        return False


def build_pipeline(axor_version: str = "") -> Any | None:
    """
    Return a TelemetryPipeline instance when mode is enabled, else None.

    Never raises. Returns None on any failure so the CLI can continue
    without telemetry.
    """
    if not _is_importable():
        return None
    try:
        from axor_telemetry import TelemetryConfig, build_pipeline as _build
        cfg = TelemetryConfig.load()
        if not cfg.enabled:
            return None
        return _build(config=cfg, axor_version=axor_version)
    except Exception:
        return None


def current_mode() -> str:
    """Resolved mode string ('off' | 'local' | 'remote' | 'unknown')."""
    if not _is_importable():
        return "unknown"
    try:
        from axor_telemetry import TelemetryConfig
        return TelemetryConfig.load().mode.value
    except Exception:
        return "unknown"


def maybe_show_first_run_banner(stream=sys.stderr) -> None:
    """
    Print a one-line opt-in banner on the first run of the CLI where
    telemetry is off. Controlled by:
      - marker file at ~/.axor/.telemetry_notice_shown (created after shown)
      - AXOR_NO_BANNER=1 env var to suppress unconditionally
      - telemetry mode — only shown when OFF

    Safe to call on every startup — second call is a no-op.
    """
    if os.environ.get("AXOR_NO_BANNER") == "1":
        return
    if not _is_importable():
        return
    try:
        from axor_telemetry import TelemetryConfig
        cfg = TelemetryConfig.load()
    except Exception:
        return
    if cfg.enabled:
        return
    if _MARKER_PATH.is_file():
        return

    stream.write(
        "axor: anonymous telemetry is off. "
        "Run `axor telemetry consent` to help tune the classifier. "
        "(shown once; suppress with AXOR_NO_BANNER=1)\n"
    )
    try:
        _MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MARKER_PATH.write_text("shown\n", encoding="utf-8")
    except OSError:
        # Marker is best-effort — missing write permission just means we
        # may show the banner more than once, not a functional problem.
        return


# ── /telemetry slash command (CLI-local, not governance) ────────────────────


def handle_slash(raw: str, stream=sys.stdout) -> int:
    """
    Dispatch `/telemetry [on|off|status|preview|consent] ...`.

    Returns a shell-style return code for testability. Prints messages to
    `stream`. Does not touch the GovernedSession — config writes take effect
    on next CLI start.
    """
    if not _is_importable():
        stream.write(
            "telemetry is not installed. Install with: pip install axor-telemetry[core]\n"
        )
        return 1

    from axor_telemetry import cli as tcli

    parts = raw.split()
    if len(parts) <= 1:
        return tcli.cmd_status(_ns(), stream=stream)

    sub = parts[1].lower()
    if sub in ("status",):
        return tcli.cmd_status(_ns(), stream=stream)
    if sub == "preview":
        return tcli.cmd_preview(_ns(), stream=stream)
    if sub == "off":
        return tcli.cmd_off(_ns(), stream=stream)
    if sub == "on":
        ns = _ns(remote="--remote" in parts[2:])
        return tcli.cmd_on(ns, stream=stream)
    if sub == "consent":
        # Interactive consent needs stdin — kept for `python -m axor_telemetry consent`.
        stream.write(
            "interactive consent is available via `python -m axor_telemetry consent`.\n"
            "use `/telemetry on` or `/telemetry on --remote` to opt in without prompts.\n"
        )
        return 0
    stream.write(f"unknown subcommand: {sub}\n")
    stream.write("usage: /telemetry [status|on [--remote]|off|preview|consent]\n")
    return 2


class _ns:
    """Minimal argparse.Namespace stand-in for direct cmd_* invocation."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
