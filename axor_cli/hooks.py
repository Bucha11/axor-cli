from __future__ import annotations

"""
Hook runner for axor-cli.

Reads hooks config from ~/.claude/settings.json and .claude/settings.json
(same format as Claude Code) and fires shell commands at lifecycle events.

Config format (settings.json):

    {
      "hooks": {
        "PreToolUse":  [{"matcher": "bash", "command": "echo pre"}],
        "PostToolUse": [{"command": "echo post $TOOL_RESULT"}],
        "Stop":        [{"command": "notify-send Done"}],
        "SessionStart":[{"command": "npm run build 2>&1 || true"}]
      }
    }

Also supports the nested Claude Code format:
    {"matcher": "bash", "hooks": [{"type": "command", "command": "..."}]}

Event env vars:
    PreToolUse:   TOOL_NAME, TOOL_INPUT (JSON)
    PostToolUse:  TOOL_NAME, TOOL_INPUT (JSON), TOOL_RESULT (string)
    Stop:         AXOR_OUTPUT
    SessionStart: (none)

PreToolUse non-zero exit code blocks the tool call.
All hooks have a 30-second timeout.
"""

import asyncio
import fnmatch
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("axor.cli.hooks")

_USER_SETTINGS    = Path.home() / ".claude" / "settings.json"
_PROJECT_SETTINGS = Path(".claude") / "settings.json"

_HOOK_TIMEOUT = 30  # seconds
_TRUST_PROJECT_HOOKS_ENV = "AXOR_TRUST_PROJECT_HOOKS"


@dataclass
class HookSpec:
    command: str
    matcher: str = ""   # glob pattern for tool_name; empty = match all


@dataclass
class HookConfig:
    pre_tool:      list[HookSpec] = field(default_factory=list)
    post_tool:     list[HookSpec] = field(default_factory=list)
    stop:          list[HookSpec] = field(default_factory=list)
    session_start: list[HookSpec] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.pre_tool or self.post_tool or self.stop or self.session_start)


def load_hooks(
    cwd: Path | None = None,
    *,
    trust_project_hooks: bool | None = None,
) -> HookConfig:
    """
    Load hooks from ~/.claude/settings.json then .claude/settings.json.
    Both files are merged; project settings are loaded last (take precedence
    when two hooks have the same matcher + command).
    """
    cwd = cwd or Path.cwd()
    trust_project = (
        os.environ.get(_TRUST_PROJECT_HOOKS_ENV, "").strip() == "1"
        if trust_project_hooks is None else trust_project_hooks
    )
    config = HookConfig()
    paths = [_USER_SETTINGS]
    project_path = cwd / _PROJECT_SETTINGS
    if project_path.exists():
        if trust_project:
            paths.append(project_path)
        else:
            log.warning(
                "Skipping project hooks from %s. Set %s=1 to trust and enable them.",
                project_path,
                _TRUST_PROJECT_HOOKS_ENV,
            )
    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Could not read hooks from %s: %s", path, exc)
            continue
        _merge(config, data.get("hooks", {}))
    return config


def _merge(config: HookConfig, raw: dict) -> None:
    _event_map = {
        "pretooluse":   "pre_tool",
        "posttooluse":  "post_tool",
        "stop":         "stop",
        "sessionstart": "session_start",
    }
    for key, groups in raw.items():
        attr = _event_map.get(key.lower().replace("_", "").replace("-", ""))
        if attr is None or not isinstance(groups, list):
            continue
        target: list[HookSpec] = getattr(config, attr)
        for group in groups:
            target.extend(_extract_specs(group))


def _extract_specs(group: dict) -> list[HookSpec]:
    matcher = group.get("matcher", "")
    if "command" in group:
        return [HookSpec(command=group["command"], matcher=matcher)]
    return [
        HookSpec(command=entry["command"], matcher=matcher)
        for entry in group.get("hooks", [])
        if entry.get("type") == "command" and "command" in entry
    ]


# ── Runner ─────────────────────────────────────────────────────────────────────

class HookRunner:
    def __init__(self, config: HookConfig) -> None:
        self._cfg = config

    def is_empty(self) -> bool:
        return self._cfg.is_empty()

    def has_pre_tool(self) -> bool:
        return bool(self._cfg.pre_tool)

    def has_post_tool(self) -> bool:
        return bool(self._cfg.post_tool)

    async def run_session_start(self) -> None:
        for spec in self._cfg.session_start:
            await _exec(spec.command, {})

    async def run_pre_tool(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """
        Returns (approved, message).
        approved=False means a hook exited non-zero — the tool call is blocked.
        """
        env = {"TOOL_NAME": tool_name, "TOOL_INPUT": json.dumps(args)}
        for spec in self._cfg.pre_tool:
            if spec.matcher and not fnmatch.fnmatch(tool_name.lower(), spec.matcher.lower()):
                continue
            rc, stdout = await _exec(spec.command, env)
            if rc != 0:
                return False, stdout.strip() or f"hook exited {rc}"
        return True, ""

    async def run_post_tool(self, tool_name: str, args: dict, result: Any) -> None:
        result_str = result if isinstance(result, str) else json.dumps(result)
        env = {
            "TOOL_NAME":   tool_name,
            "TOOL_INPUT":  json.dumps(args),
            "TOOL_RESULT": result_str,
        }
        for spec in self._cfg.post_tool:
            if spec.matcher and not fnmatch.fnmatch(tool_name.lower(), spec.matcher.lower()):
                continue
            await _exec(spec.command, env)

    async def run_stop(self, output: str) -> None:
        env = {"AXOR_OUTPUT": output}
        for spec in self._cfg.stop:
            await _exec(spec.command, env)


# Environment variables that must never leak into hook or skill subprocesses.
# Hooks are defined in user/project settings files that may be committed to
# version control — passing secrets to them is a supply-chain exfil vector.
_SECRET_ENV_PATTERNS = (
    "KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "PASSWD",
    "AUTH", "PRIVATE", "ANTHROPIC", "OPENAI", "AZURE",
)


def _sanitize_env(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    """Return a copy of base env with secret-looking variables stripped, then
    extra_env overlaid. extra_env (axor-controlled event vars) is always kept."""
    upper = {k.upper(): k for k in base}
    safe = {
        k: v for k, v in base.items()
        if not any(pat in k.upper() for pat in _SECRET_ENV_PATTERNS)
    }
    safe.update(extra)
    return safe


async def _exec(command: str, extra_env: dict[str, str]) -> tuple[int, str]:
    """Run a hook shell command. Returns (returncode, stdout+stderr)."""
    env = _sanitize_env(os.environ.copy(), extra_env)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=_HOOK_TIMEOUT)
        return proc.returncode or 0, stdout_bytes.decode(errors="replace")
    except asyncio.TimeoutError:
        log.warning("Hook timed out (%ds): %s", _HOOK_TIMEOUT, command)
        return 1, f"hook timed out after {_HOOK_TIMEOUT}s"
    except Exception as exc:
        log.warning("Hook error (%s): %s", command, exc)
        return 1, str(exc)
