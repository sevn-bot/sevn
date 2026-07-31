"""Thermos follow-ups for W12 isolation semantics."""

from __future__ import annotations


def test_explicit_empty_skills_list_denies_all_skills() -> None:
    from sevn.config.routing import resolve_routing_profile_bundle
    from sevn.config.workspace_config import WorkspaceConfig

    cfg = WorkspaceConfig.minimal(routing={"profiles": {"safe": {"skills": []}}})
    bundle = resolve_routing_profile_bundle(cfg, profile_name="safe")
    assert bundle.skill_allowlist == frozenset()


def test_absent_skills_key_means_no_restriction() -> None:
    from sevn.config.routing import _skill_allowlist_for_profile
    from sevn.config.sections.routing import RoutingWorkspaceSectionConfig

    section = RoutingWorkspaceSectionConfig(
        profiles={"open": {"model": "openai/gpt-4o"}},
    )
    entry = section.profiles["open"]
    assert _skill_allowlist_for_profile(section, "open", entry) is None


def test_secrets_scope_prefixes_logical_keys_during_turn() -> None:
    from sevn.config.routing import prefix_secrets_logical_key
    from sevn.security.secrets.routing_scope import (
        bind_routing_secrets_scope,
        current_routing_secrets_scope,
        reset_routing_secrets_scope,
        scoped_secret_logical_key,
    )

    assert prefix_secrets_logical_key("research", "api.token") == "research/api.token"
    token = bind_routing_secrets_scope("research")
    try:
        assert current_routing_secrets_scope() == "research"
        assert scoped_secret_logical_key("k") == "research/k"
    finally:
        reset_routing_secrets_scope(token)
    assert current_routing_secrets_scope() is None
