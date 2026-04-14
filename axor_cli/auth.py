from __future__ import annotations

"""
API key management for axor-cli.

Priority order (highest to lowest):
    1. --api-key CLI flag          (one-off, never saved)
    2. ADAPTER_API_KEY env var     (e.g. ANTHROPIC_API_KEY)
    3. ~/.axor/config.toml         (persistent, 0600 permissions)
    4. None → prompt via /auth

~/.axor/config.toml format:
    [claude]
    api_key = "sk-ant-..."

    [openai]
    api_key = "sk-..."
"""

import os
import stat
import getpass
from pathlib import Path
from typing import Any

try:
    import tomllib                        # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib           # fallback
    except ImportError:
        tomllib = None                    # type: ignore

CONFIG_DIR  = Path.home() / ".axor"
CONFIG_FILE = CONFIG_DIR / "config.toml"

# env var names per adapter
_ENV_VARS = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def resolve_api_key(adapter: str, flag_key: str | None = None) -> str | None:
    """
    Resolve API key using priority chain.
    Returns key string or None if not found.
    """
    # 1. CLI flag
    if flag_key:
        return flag_key

    # 2. env var
    env_var = _ENV_VARS.get(adapter)
    if env_var:
        key = os.environ.get(env_var)
        if key:
            return key

    # 3. config file
    key = load_from_config(adapter)
    if key:
        # also set in env so axor-claude/axor-openai can pick it up
        if env_var:
            os.environ[env_var] = key
        return key

    return None


def load_from_config(adapter: str) -> str | None:
    """Load API key from ~/.axor/config.toml."""
    if not CONFIG_FILE.exists():
        return None

    if tomllib is None:
        return None

    try:
        with open(CONFIG_FILE, "rb") as f:
            config: dict[str, Any] = tomllib.load(f)
        return config.get(adapter, {}).get("api_key")
    except Exception:
        return None


def _write_config(data: dict[str, Any]) -> None:
    """Write config dict to file atomically with 0600 permissions."""
    import tempfile
    lines = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        for key, val in values.items():
            lines.append(f'{key} = "{val}"')
        lines.append("")

    # atomic write via temp file
    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".axor_cfg_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines))
        os.replace(tmp, CONFIG_FILE)
        CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_to_config(adapter: str, api_key: str) -> None:
    """Save API key to ~/.axor/config.toml with 0600 permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if CONFIG_FILE.exists() and tomllib is not None:
        try:
            with open(CONFIG_FILE, "rb") as f:
                existing = tomllib.load(f)
        except Exception:
            existing = {}

    if adapter not in existing:
        existing[adapter] = {}
    existing[adapter]["api_key"] = api_key
    _write_config(existing)


def clear_from_config(adapter: str) -> bool:
    """Remove adapter key from config. Returns True if key existed."""
    if not CONFIG_FILE.exists() or tomllib is None:
        return False

    try:
        with open(CONFIG_FILE, "rb") as f:
            existing: dict[str, Any] = tomllib.load(f)
    except Exception:
        return False

    if adapter not in existing:
        return False

    del existing[adapter]
    _write_config(existing)
    return True


def prompt_and_save(adapter: str) -> str | None:
    """
    Interactively prompt for API key.
    Offers to save to config file.
    Returns the key or None if user cancelled.
    """
    env_var = _ENV_VARS.get(adapter, f"{adapter.upper()}_API_KEY")

    print(f"\n  No API key found for '{adapter}'.")
    print(f"  (checked: --api-key flag, {env_var} env var, {CONFIG_FILE})\n")

    try:
        key = getpass.getpass(f"  {adapter.capitalize()} API key (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return None

    if not key:
        print("  No key entered.")
        return None

    # offer to save
    try:
        save = input("  Save to ~/.axor/config.toml for future sessions? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        save = "n"

    if save in ("", "y", "yes"):
        try:
            save_to_config(adapter, key)
            print(f"  ✓ Key saved to {CONFIG_FILE} (permissions: 600)")
        except Exception as e:
            print(f"  ✗ Could not save: {e}")
    else:
        print("  Key not saved — valid for this session only.")

    # set in env for adapter to pick up
    env_var_name = _ENV_VARS.get(adapter)
    if env_var_name:
        os.environ[env_var_name] = key

    return key
