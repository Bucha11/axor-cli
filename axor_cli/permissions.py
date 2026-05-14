from __future__ import annotations

"""
Tool permissions loader for axor-cli.

Reads permissions from ~/.claude/settings.json and .claude/settings.json
(same files as hooks — same format as Claude Code).

Config format:

    {
      "permissions": {
        "allow": ["Read", "Bash(npm *)", "Fetch"],
        "deny":  ["Bash(rm *)", "Bash(git push --force*)", "Write(/etc/*)"]
      }
    }

Rule format:  ToolName  or  ToolName(glob_pattern)
  ToolName      — case-insensitive, matches the tool's name field
  glob_pattern  — matched against the tool's primary argument:
                    Bash  → command
                    Read / Write / Edit → path / file_path
                    Fetch → url
                    (all others → first string value in args dict)

Priority:
  1. Blanket deny (no pattern)   → tool removed from session entirely
  2. Pattern deny                → call blocked at approval time
  3. Blanket allow               → counteracts a blanket deny (re-adds tool)
     (allow-list is mainly useful together with deny rules)

Both files are merged; project settings are loaded last.
"""

import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_USER_SETTINGS    = Path.home() / ".claude" / "settings.json"
_PROJECT_SETTINGS = Path(".claude") / "settings.json"

_RULE_RE = re.compile(r'^(\w+)(?:\((.+)\))?$')


@dataclass
class PermRule:
    tool:    str         # lowercase tool name
    pattern: str | None  # None = blanket rule; else glob matched on primary arg


@dataclass
class PermissionsConfig:
    allow: list[PermRule] = field(default_factory=list)
    deny:  list[PermRule] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.allow and not self.deny

    def filter_tools(self, tools: tuple[str, ...]) -> tuple[str, ...]:
        """
        Remove tools that are blanket-denied (deny with no pattern).
        Blanket-allows re-add tools that would otherwise be removed.
        """
        blanket_deny  = {r.tool for r in self.deny  if r.pattern is None}
        blanket_allow = {r.tool for r in self.allow if r.pattern is None}
        denied = blanket_deny - blanket_allow
        return tuple(t for t in tools if t.lower() not in denied)

    def is_denied(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """
        Check whether a specific tool call is denied by a pattern rule.
        Returns (True, reason_string) when denied, (False, "") otherwise.

        Called at approval time — blanket denials are already filtered out
        at session-build, so only pattern rules are checked here.
        """
        name = tool_name.lower()
        primary = _primary_arg(name, args)

        for rule in self.deny:
            if rule.tool != name or rule.pattern is None:
                continue
            if fnmatch.fnmatch(primary.lower(), rule.pattern.lower()):
                return True, f"denied by settings: {rule.tool}({rule.pattern})"

        # pattern allow acts as exception to a blanket deny (already handled in
        # filter_tools) — nothing extra to do at call time
        return False, ""


# ── Loader ─────────────────────────────────────────────────────────────────────

def load_permissions(cwd: Path | None = None) -> PermissionsConfig:
    """
    Load permissions from ~/.claude/settings.json then .claude/settings.json.
    Rules from both files are merged (project appended after user).
    """
    cwd = cwd or Path.cwd()
    config = PermissionsConfig()
    for path in [_USER_SETTINGS, cwd / _PROJECT_SETTINGS]:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        perms = data.get("permissions", {})
        for raw in perms.get("allow", []):
            rule = _parse_rule(raw)
            if rule:
                config.allow.append(rule)
        for raw in perms.get("deny", []):
            rule = _parse_rule(raw)
            if rule:
                config.deny.append(rule)
    return config


def _parse_rule(raw: str) -> PermRule | None:
    m = _RULE_RE.match(raw.strip())
    if not m:
        return None
    return PermRule(tool=m.group(1).lower(), pattern=m.group(2) or None)


def _primary_arg(tool_name: str, args: dict) -> str:
    """Return the 'primary' argument string to match patterns against."""
    if tool_name == "bash":
        return str(args.get("command", ""))
    if tool_name in ("read", "write", "edit"):
        return str(args.get("path") or args.get("file_path") or args.get("filename") or "")
    if tool_name == "fetch":
        return str(args.get("url") or args.get("uri") or "")
    if tool_name == "search":
        return str(args.get("pattern") or args.get("path") or "")
    # fallback: first string value in args
    for v in args.values():
        if isinstance(v, str):
            return v
    return ""
