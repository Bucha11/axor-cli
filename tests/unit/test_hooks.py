from __future__ import annotations

import logging

from axor_cli import hooks


def _write_project_hook(root):
    settings_dir = root / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        '{"hooks":{"SessionStart":[{"command":"echo project"}]}}',
        encoding="utf-8",
    )


def test_project_hooks_skipped_by_default(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(hooks, "_USER_SETTINGS", tmp_path / "missing-user-settings.json")
    monkeypatch.delenv("AXOR_TRUST_PROJECT_HOOKS", raising=False)
    _write_project_hook(tmp_path)

    with caplog.at_level(logging.WARNING, logger="axor.cli.hooks"):
        config = hooks.load_hooks(cwd=tmp_path)

    assert config.is_empty()
    assert any("Skipping project hooks" in msg for msg in caplog.messages)


def test_project_hooks_can_be_trusted_by_env(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "_USER_SETTINGS", tmp_path / "missing-user-settings.json")
    monkeypatch.setenv("AXOR_TRUST_PROJECT_HOOKS", "1")
    _write_project_hook(tmp_path)

    config = hooks.load_hooks(cwd=tmp_path)

    assert len(config.session_start) == 1
    assert config.session_start[0].command == "echo project"


def test_project_hooks_can_be_trusted_explicitly(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "_USER_SETTINGS", tmp_path / "missing-user-settings.json")
    monkeypatch.delenv("AXOR_TRUST_PROJECT_HOOKS", raising=False)
    _write_project_hook(tmp_path)

    config = hooks.load_hooks(cwd=tmp_path, trust_project_hooks=True)

    assert len(config.session_start) == 1
