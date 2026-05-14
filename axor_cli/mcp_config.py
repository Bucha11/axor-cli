from __future__ import annotations

"""
MCP server configuration loader for axor-cli.

Reads [[mcp.servers]] from ~/.axor/config.toml.

Example config:

    [[mcp.servers]]
    name    = "github"
    command = "npx"
    args    = ["-y", "@modelcontextprotocol/server-github"]
    env     = {GITHUB_PERSONAL_ACCESS_TOKEN = "ghp_..."}

    [[mcp.servers]]
    name    = "filesystem"
    command = "npx"
    args    = ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_FILE = Path.home() / ".axor" / "config.toml"

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore


def load_mcp_servers() -> list[dict[str, Any]]:
    """
    Return list of MCP server config dicts from ~/.axor/config.toml.
    Each dict has: name, command, args (list), env (dict).
    Returns [] when the section is absent or config is unreadable.
    """
    if tomllib is None or not CONFIG_FILE.exists():
        return []

    try:
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        logger.warning("Could not read MCP config from %s: %s", CONFIG_FILE, e)
        return []

    raw = data.get("mcp", {}).get("servers", [])
    servers: list[dict[str, Any]] = []
    for s in raw:
        if not s.get("name") or not s.get("command"):
            logger.warning("MCP server entry missing 'name' or 'command', skipping: %s", s)
            continue
        servers.append({
            "name":    s["name"],
            "command": s["command"],
            "args":    s.get("args", []),
            "env":     s.get("env", {}),
        })
    return servers
