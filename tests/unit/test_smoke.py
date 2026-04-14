from __future__ import annotations

from importlib.metadata import version


def test_package_imports() -> None:
    import axor_cli

    assert hasattr(axor_cli, "__version__")


def test_console_script_version() -> None:
    assert version("axor-cli") == "0.1.0"
