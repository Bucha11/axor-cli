from __future__ import annotations

"""
Adapter registry for axor-cli.

Adapters are loaded lazily — axor-claude / axor-openai are optional
dependencies. Missing adapter gives a helpful install message.
"""

from typing import Any
from axor_core import GovernedSession, CapabilityExecutor


# Map of adapter name → module path + setup function
_REGISTRY: dict[str, dict[str, Any]] = {
    "claude": {
        "module":   "axor_claude",
        "install":  "pip install axor-claude",
        "env_var":  "ANTHROPIC_API_KEY",
        "models":   ["claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5"],
        "default_model": "claude-sonnet-4-5",
    },
    "openai": {
        "module":   "axor_openai",
        "install":  "pip install axor-openai",
        "env_var":  "OPENAI_API_KEY",
        "models":   ["gpt-4o", "gpt-4o-mini"],
        "default_model": "gpt-4o",
    },
}


def list_adapters() -> list[str]:
    return list(_REGISTRY.keys())


def is_available(adapter: str) -> bool:
    """Check if adapter package is installed."""
    info = _REGISTRY.get(adapter)
    if not info:
        return False
    try:
        __import__(info["module"])
        return True
    except ImportError:
        return False


def get_install_hint(adapter: str) -> str:
    info = _REGISTRY.get(adapter, {})
    return info.get("install", f"pip install axor-{adapter}")


def build_session(
    adapter: str,
    api_key: str | None = None,
    model:   str | None = None,
    tools:   tuple[str, ...] = ("read", "write", "bash", "search", "glob"),
    soft_token_limit: int | None = None,
    system_prompt: str | None = None,
    load_skills: bool = True,
    load_plugins: bool = True,
    telemetry: Any | None = None,
) -> GovernedSession:
    """
    Import the adapter package and build a GovernedSession.
    Raises ImportError with install hint if package not installed.
    """
    info = _REGISTRY.get(adapter)
    if not info:
        available = ", ".join(_REGISTRY.keys())
        raise ValueError(f"Unknown adapter: '{adapter}'. Available: {available}")

    try:
        mod = __import__(info["module"])
    except ImportError:
        raise ImportError(
            f"Adapter '{adapter}' is not installed.\n"
            f"Install it with: {info['install']}"
        )

    # adapters expose make_session() as the standard factory
    if not hasattr(mod, "make_session"):
        raise AttributeError(
            f"Adapter '{adapter}' ({info['module']}) does not expose make_session(). "
            "Check your axor adapter version."
        )

    kwargs: dict[str, Any] = {
        "api_key":     api_key,
        "tools":       tools,
        "load_skills": load_skills,
        "load_plugins": load_plugins,
    }
    if soft_token_limit is not None:
        kwargs["soft_token_limit"] = soft_token_limit

    if telemetry is not None:
        kwargs["telemetry"] = telemetry

    # model and system_prompt are passed to the executor inside make_session
    # adapters should accept **session_kwargs and forward to their executor
    if model:
        kwargs["model"] = model
    if system_prompt:
        kwargs["system_prompt"] = system_prompt

    try:
        return mod.make_session(**kwargs)
    except ImportError as e:
        # adapter's underlying SDK (e.g. anthropic) not installed
        raise ImportError(
            f"Adapter '{adapter}' requires additional dependencies.\n"
            f"  {e}\n"
            f"  Install with: {info['install']}"
        ) from e


def default_model(adapter: str) -> str:
    return _REGISTRY.get(adapter, {}).get("default_model", "unknown")


def available_models(adapter: str) -> list[str]:
    return _REGISTRY.get(adapter, {}).get("models", [])
