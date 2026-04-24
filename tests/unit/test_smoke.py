from __future__ import annotations

from importlib.metadata import version


def test_package_imports() -> None:
    import axor_cli

    assert hasattr(axor_cli, "__version__")


def test_console_script_version() -> None:
    """Installed metadata must match the in-package __version__ string.

    Guards against releases that bump pyproject.toml without bumping
    axor_cli/_version.py (or vice versa).
    """
    import axor_cli
    assert version("axor-cli") == axor_cli.__version__
