from __future__ import annotations

"""
API key management for axor-cli.

Priority order (highest to lowest):
    1. --api-key CLI flag          (one-off, never saved)
    2. ADAPTER_API_KEY env var     (e.g. ANTHROPIC_API_KEY)
    3. ~/.axor/config.toml         (persistent, 0600 permissions)
    4. None -> prompt via /auth

~/.axor/config.toml format:
    [claude]
    api_key = "sk-ant-..."

    [openai]
    api_key = "sk-..."
"""

import getpass
import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # fallback
    except ImportError:
        tomllib = None  # type: ignore

logger = logging.getLogger(__name__)

# Configuration paths
CONFIG_DIR = Path.home() / ".axor"
CONFIG_FILE = CONFIG_DIR / "config.toml"

# File permissions for config (owner read/write only)
CONFIG_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600

# Environment variable names per adapter
_ENV_VARS: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


# ============================================================================
# Public API
# ============================================================================


def resolve_api_key(adapter: str, flag_key: str | None = None) -> str | None:
    """
    Resolve API key using priority chain.
    
    Priority order:
        1. CLI flag (flag_key parameter)
        2. Environment variable (ADAPTER_API_KEY)
        3. Config file (~/.axor/config.toml)
    
    Args:
        adapter: Name of the adapter (e.g., "claude", "openai")
        flag_key: Optional API key from CLI flag (highest priority)
    
    Returns:
        API key string or None if not found
    """
    # 1. CLI flag has highest priority
    if flag_key:
        return flag_key

    # 2. Check environment variable
    key = _get_key_from_env(adapter)
    if key:
        return key

    # 3. Check config file
    key = load_from_config(adapter)
    if key:
        # Set in environment so adapter executables can pick it up
        _set_key_in_env(adapter, key)
        return key

    return None


def load_from_config(adapter: str) -> str | None:
    """
    Load API key from ~/.axor/config.toml.
    
    Args:
        adapter: Name of the adapter section in config
    
    Returns:
        API key string or None if not found
    """
    if not CONFIG_FILE.exists():
        return None

    if tomllib is None:
        logger.warning("TOML support unavailable (install tomli for Python <3.11)")
        return None

    try:
        config = _read_config_file()
        return config.get(adapter, {}).get("api_key")
    except Exception as e:
        logger.warning("Failed to read %s: %s", CONFIG_FILE, e)
        return None


def save_to_config(adapter: str, api_key: str) -> None:
    """
    Save API key to ~/.axor/config.toml with 0600 permissions.
    
    Args:
        adapter: Name of the adapter section
        api_key: API key to save
    """
    existing = _load_existing_config()
    
    if adapter not in existing:
        existing[adapter] = {}
    existing[adapter]["api_key"] = api_key
    
    _write_config(existing)


def clear_from_config(adapter: str) -> bool:
    """
    Remove adapter key from config.
    
    Args:
        adapter: Name of the adapter section to remove
    
    Returns:
        True if key existed and was removed, False otherwise
    """
    if not CONFIG_FILE.exists():
        return False

    if tomllib is None:
        logger.warning("TOML support unavailable — cannot clear config")
        return False

    try:
        existing = _read_config_file()
    except Exception as e:
        logger.warning("Failed to read config: %s", e)
        return False

    if adapter not in existing:
        return False

    del existing[adapter]
    _write_config(existing)
    return True


def prompt_and_save(adapter: str) -> str | None:
    """
    Interactively prompt for API key and optionally save to config.
    
    Args:
        adapter: Name of the adapter
    
    Returns:
        The entered API key or None if user cancelled
    """
    env_var_name = _get_env_var_name(adapter)
    
    _print_prompt_header(adapter, env_var_name)
    
    key = _prompt_for_key(adapter)
    if not key:
        return None
    
    _offer_to_save_key(adapter, key)
    _set_key_in_env(adapter, key)
    
    return key


# ============================================================================
# Private helpers - Environment variable handling
# ============================================================================


def _get_env_var_name(adapter: str) -> str:
    """Get the environment variable name for an adapter."""
    return _ENV_VARS.get(adapter, f"{adapter.upper()}_API_KEY")


def _get_key_from_env(adapter: str) -> str | None:
    """Get API key from environment variable."""
    env_var = _ENV_VARS.get(adapter)
    if env_var:
        return os.environ.get(env_var)
    return None


def _set_key_in_env(adapter: str, key: str) -> None:
    """Set API key in environment variable."""
    env_var = _ENV_VARS.get(adapter)
    if env_var:
        os.environ[env_var] = key


# ============================================================================
# Private helpers - Config file I/O
# ============================================================================


def _read_config_file() -> dict[str, Any]:
    """Read and parse the config file."""
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)  # type: ignore


def _load_existing_config() -> dict[str, Any]:
    """Load existing config or return empty dict if not available."""
    if not CONFIG_FILE.exists() or tomllib is None:
        return {}
    
    try:
        return _read_config_file()
    except Exception as e:
        logger.warning("Failed to read existing config: %s", e)
        return {}


def _escape_toml_value(val: str) -> str:
    """Escape a string for TOML double-quoted value."""
    return val.replace("\\", "\\\\").replace('"', '\\"')


def _serialize_config_to_toml(data: dict[str, Any]) -> str:
    """Serialize config dict to TOML format."""
    lines: list[str] = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        for key, val in values.items():
            escaped_val = _escape_toml_value(str(val))
            lines.append(f'{key} = "{escaped_val}"')
        lines.append("")
    return "\n".join(lines)


def _write_config(data: dict[str, Any]) -> None:
    """
    Write config dict to file atomically with 0600 permissions.
    
    Uses atomic write pattern: write to temp file with restricted permissions,
    then replace the original file.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    toml_content = _serialize_config_to_toml(data)
    
    # Atomic write: create temp with restricted perms, then replace
    fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".axor_cfg_")
    try:
        # Set permissions before writing content
        os.fchmod(fd, CONFIG_FILE_MODE)
        with os.fdopen(fd, "w") as f:
            f.write(toml_content)
        os.replace(tmp_path, CONFIG_FILE)
    except Exception:
        # Clean up temp file on error
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# ============================================================================
# Private helpers - Interactive prompts
# ============================================================================


def _print_prompt_header(adapter: str, env_var_name: str) -> None:
    """Print header for interactive prompt."""
    print(f"\n  No API key found for '{adapter}'.")
    print(f"  (checked: --api-key flag, {env_var_name} env var, {CONFIG_FILE})\n")


def _prompt_for_key(adapter: str) -> str | None:
    """
    Prompt user for API key.
    
    Returns:
        Entered key or None if cancelled/empty
    """
    try:
        key = getpass.getpass(
            f"  {adapter.capitalize()} API key (hidden): "
        ).strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return None

    if not key:
        print("  No key entered.")
        return None
    
    return key


def _should_save_key() -> bool:
    """Ask user if they want to save the key."""
    try:
        response = input(
            "  Save to ~/.axor/config.toml for future sessions? [Y/n]: "
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return False
    
    return response in ("", "y", "yes")


def _offer_to_save_key(adapter: str, key: str) -> None:
    """Offer to save the key to config and execute the save if accepted."""
    if _should_save_key():
        try:
            save_to_config(adapter, key)
            print(f"  Saved to {CONFIG_FILE} (permissions: 600)")
        except Exception as e:
            print(f"  Could not save: {e}")
    else:
        print("  Key not saved — valid for this session only.")
