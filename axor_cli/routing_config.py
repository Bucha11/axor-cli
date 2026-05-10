from __future__ import annotations

"""
Routing configuration for openrouter adapter.

Read from ~/.axor/config.toml under [openrouter.routing].

Example config:

    [openrouter.routing]
    mode = "smart"                        # "smart" | "cascade" | "flat"
    root_model = "anthropic/claude-sonnet-4-6"

    # smart mode
    prefer_free_at_depth = 3
    max_cost_in = 1.0                     # USD/1M input tokens, omit for no limit

    # cascade mode — define tiers as array of tables
    # [[openrouter.routing.tiers]]
    # min_depth = 0
    # max_depth = 0
    # model = "anthropic/claude-sonnet-4-6"
    #
    # [[openrouter.routing.tiers]]
    # min_depth = 1
    # model = "openai/gpt-4o-mini"
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import logging

logger = logging.getLogger(__name__)

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

CONFIG_FILE = Path.home() / ".axor" / "config.toml"


@dataclass
class TierConfig:
    model: str
    min_depth: int = 0
    max_depth: int | None = None
    tier_index: int = 0


@dataclass
class RoutingConfig:
    """
    Resolved routing configuration for the openrouter adapter.

    mode:
      "smart"   — SmartModelSelector picks model per task complexity + depth
      "cascade" — explicit depth→model mapping via tiers list
      "flat"    — single root_model for all nodes
    """
    mode: str = "smart"
    root_model: str | None = None
    # smart options
    prefer_free_at_depth: int = 3
    max_cost_in: float | None = None
    # cascade options
    tiers: list[TierConfig] = field(default_factory=list)


def load_routing_config(adapter: str = "openrouter") -> RoutingConfig:
    """
    Load routing config from ~/.axor/config.toml.
    Returns defaults if file absent or section missing.
    """
    if tomllib is None or not CONFIG_FILE.exists():
        return RoutingConfig()

    try:
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        logger.warning("Could not read %s: %s", CONFIG_FILE, e)
        return RoutingConfig()

    section: dict[str, Any] = data.get(adapter, {}).get("routing", {})
    if not section:
        return RoutingConfig()

    tiers: list[TierConfig] = []
    for i, t in enumerate(section.get("tiers", [])):
        tiers.append(TierConfig(
            model=t["model"],
            min_depth=int(t.get("min_depth", 0)),
            max_depth=int(t["max_depth"]) if t.get("max_depth") is not None else None,
            tier_index=i,
        ))

    return RoutingConfig(
        mode=section.get("mode", "smart"),
        root_model=section.get("root_model"),
        prefer_free_at_depth=int(section.get("prefer_free_at_depth", 3)),
        max_cost_in=float(section["max_cost_in"]) if section.get("max_cost_in") is not None else None,
        tiers=tiers,
    )
