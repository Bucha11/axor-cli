from __future__ import annotations

import logging

from axor_cli import permissions


def test_load_permissions_warns_on_malformed_project_settings(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(permissions, "_USER_SETTINGS", tmp_path / "missing-user-settings.json")
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text("{not-json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="axor.cli.permissions"):
        config = permissions.load_permissions(cwd=tmp_path)

    assert config.is_empty()
    assert any("Could not read permissions" in msg for msg in caplog.messages)
