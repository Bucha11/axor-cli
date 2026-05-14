from __future__ import annotations

"""
Session persistence for axor-cli REPL.

Saves (task, output) pairs to ~/.axor/sessions/<dir_hash>.jsonl
so the user can resume a previous conversation.

On resume, the last N chars of history are injected as an ExtensionFragment
(kind="fact") so the model has context about what was discussed before.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from axor_core.contracts.extension import ExtensionBundle, ExtensionFragment, ExtensionLoader

log = logging.getLogger("axor.cli.session")

SESSIONS_DIR = Path.home() / ".axor" / "sessions"

# How many chars of history to inject on resume (~3000 = ~750 tokens)
_RESUME_CHARS = 3000


def session_path(cwd: Path | None = None) -> Path:
    cwd = cwd or Path.cwd()
    dir_hash = hashlib.sha256(str(cwd).encode()).hexdigest()[:12]
    return SESSIONS_DIR / f"{dir_hash}.jsonl"


def save_turn(task: str, output: str, cwd: Path | None = None) -> None:
    """Append a completed turn to the session file."""
    path = session_path(cwd)
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts":     datetime.now(timezone.utc).isoformat(),
            "task":   task,
            "output": output,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("could not save session turn: %s", e)


def load_turns(cwd: Path | None = None, max_turns: int = 20) -> list[dict[str, Any]]:
    """Load the last N turns from the session file."""
    path = session_path(cwd)
    if not path.exists():
        return []
    turns: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        turns.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError as e:
        log.warning("could not load session: %s", e)
    return turns[-max_turns:]


def format_history_fragment(turns: list[dict[str, Any]], max_chars: int = _RESUME_CHARS) -> str:
    """Convert turns to a text fragment suitable for context injection."""
    lines: list[str] = ["Previous conversation (most recent last):"]
    for t in turns:
        ts = t.get("ts", "")[:16].replace("T", " ")
        task_text   = t.get("task", "").strip()
        output_text = t.get("output", "").strip()
        lines.append(f"\n[{ts}] User: {task_text}")
        lines.append(f"Assistant: {output_text[:500]}{'...' if len(output_text) > 500 else ''}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = "...(earlier history truncated)\n" + text[-max_chars:]
    return text


class SessionHistoryLoader(ExtensionLoader):
    """Injects previous session history as a context fragment on resume."""

    def __init__(self, cwd: Path | None = None) -> None:
        self._cwd = cwd or Path.cwd()

    async def load(self) -> ExtensionBundle:
        turns = load_turns(self._cwd)
        if not turns:
            return ExtensionBundle()
        text = format_history_fragment(turns)
        fragment = ExtensionFragment(
            name="session_history",
            context_fragment=text,
            required_tools=(),
            policy_overrides={},
            source=str(session_path(self._cwd)),
        )
        return ExtensionBundle(fragments=(fragment,))
