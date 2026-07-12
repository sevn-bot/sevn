"""Onboarding Second Brain vault capability manifest tests."""

from __future__ import annotations

from sevn.onboarding.capabilities_manifest import load_manifest


def test_manifest_includes_vault_path_controls() -> None:
    manifest = load_manifest()
    ids = {cap.capability_id for cap in manifest.capabilities}
    assert "memory.second_brain.vault_path" in ids
    assert "memory.second_brain.vault_browse" in ids


def test_vault_path_capability_is_text_control() -> None:
    manifest = load_manifest()
    cap = next(
        c for c in manifest.capabilities if c.capability_id == "memory.second_brain.vault_path"
    )
    assert cap.control == "text"
    assert "second_brain.paths.vault" in cap.config_paths


def test_install_action_second_brain_bootstrap() -> None:
    manifest = load_manifest()
    cap = next(c for c in manifest.capabilities if c.capability_id == "memory.second_brain")
    assert cap.install_actions[0].kind == "second_brain_bootstrap"
