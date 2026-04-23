from __future__ import annotations

"""
Terminal display helpers for axor-cli.

Handles:
  - Streaming text output (print as chunks arrive)
  - Status lines (policy, tokens, tools)
  - Spinner for thinking state
  - Colored output (degrades gracefully if no color support)
"""

import sys
import os
import time
import threading


# ── Color support ──────────────────────────────────────────────────────────────

def _supports_color() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    return os.environ.get("TERM", "") != "dumb"

_COLOR = _supports_color()

def _c(code: str, text: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def dim(text: str)   -> str: return _c("2", text)
def bold(text: str)  -> str: return _c("1", text)
def green(text: str) -> str: return _c("32", text)
def yellow(text: str)-> str: return _c("33", text)
def red(text: str)   -> str: return _c("31", text)
def cyan(text: str)  -> str: return _c("36", text)
def blue(text: str)  -> str: return _c("34", text)


# ── Header ─────────────────────────────────────────────────────────────────────

def print_header(adapter: str, model: str, version: str = "0.1.0") -> None:
    print()
    print(bold(f"axor") + f" v{version} " +
          dim("│") + f" adapter: {cyan(adapter)} " +
          dim("│") + f" model: {dim(model)}")
    print(dim("Type a task, a /command, or 'exit' to quit."))
    print(dim("  /auth        — set API key"))
    print(dim("  /cost        — token usage"))
    print(dim("  /policy      — last execution policy"))
    print(dim("  /compact     — compress context"))
    print(dim("  /status      — session overview"))
    print(dim("  /help        — all commands"))
    print()


# ── Spinner ────────────────────────────────────────────────────────────────────

class Spinner:
    """
    Non-blocking spinner for "thinking" state.
    Shows while waiting for first stream token.
    Cleared as soon as text starts arriving.
    """

    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not _COLOR:
            sys.stdout.write(dim("thinking...\n"))
            sys.stdout.flush()
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None
        if _COLOR:
            sys.stdout.write("\r\033[K")   # clear spinner line
            sys.stdout.flush()

    def _spin(self) -> None:
        i = 0
        while not self._stop_event.is_set():
            frame = self._FRAMES[i % len(self._FRAMES)]
            sys.stdout.write(f"\r{dim(self._prefix)}{dim(frame)} ")
            sys.stdout.flush()
            self._stop_event.wait(timeout=0.08)
            i += 1


# ── Streaming output ───────────────────────────────────────────────────────────

def stream_text(text: str) -> None:
    """Print a text chunk as it arrives from the stream."""
    sys.stdout.write(text)
    sys.stdout.flush()


def print_tool_call(tool: str, args: dict, approved: bool) -> None:
    if approved:
        args_str = _format_args(args)
        print(f"\n{dim('  ↳')} {yellow(tool)}{dim('('+ args_str +')')}", end="")
    else:
        print(f"\n{dim('  ✗')} {red(tool)} {dim('(denied)')}", end="")


def print_tool_result(tool: str, result: str, approved: bool) -> None:
    if approved:
        preview = result[:60].replace("\n", " ").strip()
        ellipsis = "…" if len(result) > 60 else ""
        print(f" {dim('→')} {dim(preview + ellipsis)}", end="")


def end_stream() -> None:
    """Called after all stream events."""
    print()   # final newline


# ── Status after completion ────────────────────────────────────────────────────

def print_completion(
    policy: str,
    input_tokens: int,
    output_tokens: int,
    cancelled: bool = False,
) -> None:
    total = input_tokens + output_tokens
    if cancelled:
        status = red("cancelled")
    else:
        status = green("✓ done")

    print(
        f"\n{dim('  ')}{status} "
        f"{dim('│')} policy: {dim(policy)} "
        f"{dim('│')} tokens: {dim(str(total))} "
        f"{dim(f'(in: {input_tokens} out: {output_tokens})')}"
    )


def print_error(msg: str) -> None:
    print(f"\n{red('  ✗')} {msg}")


def print_info(msg: str) -> None:
    print(f"\n{dim('  →')} {msg}")


def print_success(msg: str) -> None:
    print(f"\n{green('  ✓')} {msg}")


# ── Prompt ─────────────────────────────────────────────────────────────────────

def prompt(prefix: str = "> ") -> str:
    """Read user input. Returns stripped string."""
    try:
        return input(bold(prefix)).strip()
    except (KeyboardInterrupt, EOFError):
        return "exit"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format_args(args: dict) -> str:
    if not args:
        return ""
    parts = []
    for k, v in list(args.items())[:2]:   # show max 2 args
        val = str(v)[:30]
        parts.append(f"{k}={val!r}")
    if len(args) > 2:
        parts.append("…")
    return ", ".join(parts)
