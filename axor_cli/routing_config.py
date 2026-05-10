from __future__ import annotations

"""
Routing configuration for openrouter adapter.

Read from ~/.axor/config.toml under [openrouter.routing].
If the section is absent, a default config is written on first use.

Default smart-cascade tier hierarchy (matches axor-openrouter MODEL_REGISTRY):
  Tier 0  flagship  : claude-opus-4-7, gpt-4o, gemini-2.5-pro
  Tier 1  strong    : claude-sonnet-4-6, kimi-k2, deepseek-r1, gemini-2.5-flash
  Tier 2  fast      : deepseek-chat ($0.27), haiku ($0.80)
  Tier 3  cheap     : gpt-4o-mini ($0.15)
  Tier 4  near-free : llama-3.3-70b, mistral-small, qwen3-8b, *:free models

Smart selection: base_tier = COMPLEXITY_TO_TIER[task_signal] + min(depth, 3)
  EXPANSIVE depth=1 → tier 1 → kimi-k2
  MODERATE  depth=1 → tier 2 → deepseek-chat
  FOCUSED   depth=1 → tier 3 → gpt-4o-mini
  depth ≥ prefer_free_at_depth → free model
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import logging
import os
import stat
import tempfile

logger = logging.getLogger(__name__)

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

CONFIG_DIR  = Path.home() / ".axor"
CONFIG_FILE = CONFIG_DIR / "config.toml"
CONFIG_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600

# Default routing config written to ~/.axor/config.toml on first openrouter use.
_DEFAULT_ROUTING_TOML = """\

[openrouter.routing]
# Routing mode: "smart" | "cascade" | "flat"
#
#   smart   — SmartModelSelector picks model per task complexity + depth.
#             Uses axor-core TaskSignal to route cheap tasks to cheap models.
#   cascade — Explicit depth→model mapping (define [[openrouter.routing.tiers]]).
#   flat    — Single model for all nodes (set root_model below).
mode = "smart"

# Root model (depth=0). Pinned in smart mode; used for all nodes in flat mode.
root_model = "anthropic/claude-sonnet-4-6"

# Smart mode: switch to free models at this depth and beyond.
prefer_free_at_depth = 3

# Smart mode: hard ceiling on input token price (USD per 1M). Omit for no limit.
# max_cost_in = 0.30

# Cascade mode: define one tier per depth range.
# Uncomment and set mode = "cascade" to use explicit tiers.
#
# [[openrouter.routing.tiers]]
# min_depth = 0
# max_depth = 0
# model     = "anthropic/claude-sonnet-4-6"
#
# [[openrouter.routing.tiers]]
# min_depth = 1
# model     = "openai/gpt-4o-mini"
"""


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
    prefer_free_at_depth: int = 3
    max_cost_in: float | None = None
    tiers: list[TierConfig] = field(default_factory=list)


def load_routing_config(adapter: str = "openrouter") -> RoutingConfig:
    """
    Load routing config from ~/.axor/config.toml.

    If [openrouter.routing] section is absent, writes defaults and returns them.
    Returns defaults without writing if tomllib is unavailable.
    """
    if tomllib is None:
        return RoutingConfig()

    data: dict[str, Any] = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            logger.warning("Could not read %s: %s", CONFIG_FILE, e)
            return RoutingConfig()

    section: dict[str, Any] = data.get(adapter, {}).get("routing", {})

    if not section:
        _write_default_routing(adapter)
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


def _write_default_routing(adapter: str) -> None:
    """Append default [openrouter.routing] block to ~/.axor/config.toml."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        existing = CONFIG_FILE.read_text(encoding="utf-8") if CONFIG_FILE.exists() else ""

        content = existing.rstrip("\n") + _DEFAULT_ROUTING_TOML

        fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".axor_cfg_")
        try:
            os.fchmod(fd, CONFIG_FILE_MODE)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, CONFIG_FILE)
            logger.info("Wrote default openrouter routing config to %s", CONFIG_FILE)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except Exception as e:
        logger.warning("Could not write default routing config: %s", e)
