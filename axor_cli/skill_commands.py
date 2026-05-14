from __future__ import annotations

"""
Skill slash-command discovery for axor-cli.

Scans .claude/skills/*.md for YAML frontmatter that declares a slash command.
When the user types /skillname in the REPL, this module provides the
task or run-command to execute.

Frontmatter format (fenced by ---):

    ---
    description: Run the full test suite
    run: npm test
    ---
    (rest of file is the skill context fragment — injected by GenericSkillLoader)

Fields:
    description  Task description sent to the model when /skillname is typed.
                 If absent, the skill body text is used as the task.
    run          Bash command executed directly (bypasses the model).
                 Takes priority over description when both are present.
    allowed_tools  Comma-separated list of extra tools this skill needs.

If a skill file has no frontmatter, or frontmatter has neither run nor
description, it only acts as a context fragment — no slash command is registered.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("axor.cli.skill_commands")


@dataclass
class SkillCommand:
    name: str          # command name (filename without .md)
    description: str   # human-readable description for /help
    run: str           # bash command to execute directly (takes priority)
    task: str          # task description forwarded to model (fallback)
    source: Path       # path to the skill file


def load_skill_commands(cwd: Path | None = None) -> dict[str, SkillCommand]:
    """
    Return {command_name: SkillCommand} for all skills that declare a command.
    Checks both project (.claude/skills/) and user (~/.claude/skills/) dirs.
    """
    cwd = cwd or Path.cwd()
    commands: dict[str, SkillCommand] = {}

    search_dirs = [
        Path.home() / ".claude" / "skills",
        cwd / ".claude" / "skills",
    ]

    for skills_dir in search_dirs:
        if not skills_dir.is_dir():
            continue
        for path in sorted(skills_dir.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, body = _parse_frontmatter(text)
            run  = meta.get("run", "").strip()
            desc = meta.get("description", "").strip()
            # Only register a command if frontmatter explicitly declares it
            if not run and not desc:
                continue
            name = path.stem.lower()
            commands[name] = SkillCommand(
                name=name,
                description=desc or f"Run skill: {name}",
                run=run,
                task=desc or body[:500].strip() or name,
                source=path,
            )

    return commands


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """
    Extract YAML-like frontmatter from a markdown file.

    Returns (metadata_dict, body_text).
    Only handles flat key: value pairs — no nested YAML needed for skill files.
    """
    text = text.lstrip()
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    frontmatter_block = text[3:end].strip()
    body = text[end + 4:].strip()

    meta: dict[str, str] = {}
    for line in frontmatter_block.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip().lower()] = val.strip()

    return meta, body
