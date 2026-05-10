from __future__ import annotations

"""
Terminal display helpers for axor-cli.

Handles:
  - Streaming text output (print as chunks arrive)
  - Status lines (policy, tokens, tools)
  - Spinner for thinking state
  - Colored output (degrades gracefully if no color support)
"""

import asyncio
import difflib
import re as _re
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


def print_diff(old: str, new: str, path: str = "") -> None:
    """Print a compact unified diff for edit/write operations."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    label = f" {dim(path)}" if path else ""
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    if not diff:
        return
    print(f"\n{dim('  diff')}{label}")
    for line in diff[2:]:  # skip ---/+++ header lines
        line = line.rstrip("\n")
        if line.startswith("+"):
            print(f"  {green(line)}")
        elif line.startswith("-"):
            print(f"  {red(line)}")
        elif line.startswith("@@"):
            print(f"  {dim(line)}")
        else:
            print(f"  {dim(line)}")


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
    ctx_pct: int | None = None,
) -> None:
    total = input_tokens + output_tokens
    if cancelled:
        status = red("cancelled")
    else:
        status = green("✓ done")

    ctx_part = ""
    if ctx_pct is not None:
        color = red if ctx_pct >= 90 else (yellow if ctx_pct >= 70 else dim)
        ctx_part = f" {dim('│')} ctx: {color(f'{ctx_pct}%')}"

    print(
        f"\n{dim('  ')}{status} "
        f"{dim('│')} policy: {dim(policy)} "
        f"{dim('│')} tokens: {dim(str(total))} "
        f"{dim(f'(in: {input_tokens} out: {output_tokens})')}"
        f"{ctx_part}"
    )


def print_error(msg: str) -> None:
    print(f"\n{red('  ✗')} {msg}")


def print_info(msg: str) -> None:
    print(f"\n{dim('  →')} {msg}")


def print_success(msg: str) -> None:
    print(f"\n{green('  ✓')} {msg}")


def print_hook_block(tool: str, reason: str) -> None:
    print(f"\n{red('  ✗ hook blocked')} {yellow(tool)}: {dim(reason)}")


# ── Markdown renderer ─────────────────────────────────────────────────────────

class MarkdownRenderer:
    """
    Line-buffered terminal markdown renderer for streaming LLM output.

    Usage:
        r = MarkdownRenderer()
        r.feed(chunk)   # call for each streamed text chunk
        r.flush()       # call once at end to drain any buffered content
    """

    _FENCE        = _re.compile(r'^```')
    _HEADING      = _re.compile(r'^(#{1,6}) (.*)')
    _BULLET       = _re.compile(r'^(\s*)([-*+]|\d+\.) (.*)')
    _QUOTE        = _re.compile(r'^> (.*)')
    _HR           = _re.compile(r'^(---+|\*\*\*+|___+)\s*$')
    _BOLD_ITALIC  = _re.compile(r'\*\*\*(.+?)\*\*\*')
    _BOLD         = _re.compile(r'\*\*(.+?)\*\*')
    _ITALIC_STAR  = _re.compile(r'\*(.+?)\*')
    _ITALIC_UNDER = _re.compile(r'(?<!\w)_(.+?)_(?!\w)')
    _INLINE_CODE  = _re.compile(r'`([^`\n]+)`')

    def __init__(self) -> None:
        self._buf: str = ""
        self._in_code: bool = False
        self._code_lang: str = ""
        self._code_lines: list[str] = []

    def feed(self, chunk: str) -> None:
        self._buf += chunk
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._process_line(line)

    def flush(self) -> None:
        if self._buf:
            self._process_line(self._buf)
            self._buf = ""
        if self._in_code:
            self._emit_code_block()
            self._in_code = False

    # ── internal ──────────────────────────────────────────────────────────────

    def _process_line(self, raw: str) -> None:
        if self._in_code:
            if raw.strip().startswith("```"):
                self._emit_code_block()
                self._in_code = False
            else:
                self._code_lines.append(raw)
        else:
            stripped = raw.strip()
            if stripped.startswith("```"):
                self._in_code = True
                self._code_lang = stripped[3:].strip()
                self._code_lines = []
            else:
                sys.stdout.write(self._format_line(raw) + "\n")
                sys.stdout.flush()

    def _emit_code_block(self) -> None:
        lang = self._code_lang
        label = f" {lang} " if lang else " "
        width = max(42, len(label) + 4)
        bar = "─" * (width - len(label) - 1)
        header = f"  ┌{label}{bar}┐"
        footer = f"  └{'─' * (width - 1)}┘"
        sys.stdout.write("\n" + dim(header) + "\n")
        for line in self._code_lines:
            sys.stdout.write(f"  {dim('│')} {line}\n")
        sys.stdout.write(dim(footer) + "\n\n")
        sys.stdout.flush()
        self._code_lines = []
        self._code_lang = ""

    def _format_line(self, line: str) -> str:
        if not _COLOR:
            return line
        # headings
        m = self._HEADING.match(line)
        if m:
            level = len(m.group(1))
            text = self._inline(m.group(2))
            if level == 1:
                return "\n" + bold(green(text))
            if level == 2:
                return "\n" + bold(cyan(text))
            return bold(text)
        # horizontal rule
        if self._HR.match(line):
            return dim("  " + "─" * 50)
        # bullet / numbered list
        m = self._BULLET.match(line)
        if m:
            indent, _, content = m.group(1), m.group(2), m.group(3)
            return indent + dim("• ") + self._inline(content)
        # blockquote
        m = self._QUOTE.match(line)
        if m:
            return dim("  ▎ ") + self._inline(m.group(1))
        return self._inline(line)

    def _inline(self, text: str) -> str:
        if not _COLOR:
            return text
        text = self._BOLD_ITALIC.sub(lambda m: bold(m.group(1)), text)
        text = self._BOLD.sub(lambda m: bold(m.group(1)), text)
        text = self._ITALIC_STAR.sub(lambda m: _c("3", m.group(1)), text)
        text = self._ITALIC_UNDER.sub(lambda m: _c("3", m.group(1)), text)
        text = self._INLINE_CODE.sub(lambda m: cyan(m.group(1)), text)
        return text


# ── Tool approval ──────────────────────────────────────────────────────────────

# Tools that run silently without asking the user.
_AUTO_APPROVE = frozenset({"read", "search", "glob", "fetch", "spawn_child", "todo_write", "todo_read"})


async def prompt_approval(tool_name: str, args: dict) -> bool:
    """
    Ask the user to approve a tool call. Returns True to allow, False to deny.
    read/search/glob/spawn_child are auto-approved (non-destructive).
    """
    if tool_name in _AUTO_APPROVE:
        return True

    args_str = _format_args(args)
    label = f"{yellow(tool_name)}{dim('(' + args_str + ')')}"
    prompt_str = f"  {label}  {dim('[y/N]')} "

    try:
        response = await asyncio.to_thread(input, prompt_str)
        return response.strip().lower() in ("y", "yes", "")
    except (KeyboardInterrupt, EOFError):
        print()
        return False


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
