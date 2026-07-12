"""Ops and browser accessor config tests."""

from __future__ import annotations

from sevn.config.workspace_config import browser_settings, parse_workspace_config


def test_browser_settings_reads_skills_browser() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "skills": {
                "browser": {
                    "profile_dir": "~/custom-profile",
                    "idle_close_seconds": 600,
                    "headless": True,
                }
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    settings = browser_settings(cfg)
    assert settings.profile_dir == "~/custom-profile"
    assert settings.idle_close_seconds == 600
    assert settings.headless is True
    assert browser_settings(None).idle_close_seconds == 0
