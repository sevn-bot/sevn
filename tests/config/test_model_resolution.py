"""Tests for unified main-model resolution (`src/sevn/config/model_resolution.py`)."""

from __future__ import annotations

import pytest

from sevn.agent.triager.errors import TriagerUnavailable
from sevn.config.model_resolution import (
    ModelSlot,
    fill_missing_model_slots_from_triager,
    is_minimax_catalog_model,
    maybe_split_unified_model_on_config_set,
    model_slot_for_config_dot_path,
    resolve_main_model_id,
    resolve_minimax_anthropic_base_url,
    resolve_model_slot,
    resolve_transport_for_model_id,
    resolve_wire_model_id,
    use_main_model_for_all,
    workspace_has_minimax_catalog_model,
)
from sevn.config.workspace_config import (
    LcmWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)


def test_use_main_model_defaults_true() -> None:
    assert (
        use_main_model_for_all(
            WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            )
        )
        is True
    )


def test_use_main_model_explicit_false() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        providers={"use_main_model_for_all": False, "tier_default": {"triager": "openai/gpt-4o"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert use_main_model_for_all(cfg) is False


def test_resolve_main_model_id() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        providers={"tier_default": {"triager": "minimax/MiniMax-M2.7"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert resolve_main_model_id(cfg) == "minimax/MiniMax-M2.7"


def test_resolve_main_model_id_missing() -> None:
    with pytest.raises(TriagerUnavailable):
        resolve_main_model_id(
            WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            )
        )


def test_unified_scanner_inherits_triager() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        providers={
            "use_main_model_for_all": True,
            "tier_default": {"triager": "minimax/MiniMax-M2.7"},
        },
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(model="openai/gpt-4o-mini"),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert resolve_model_slot(cfg, ModelSlot.scanner) == "minimax/MiniMax-M2.7"


def test_override_scanner_when_not_unified() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        providers={
            "use_main_model_for_all": False,
            "tier_default": {"triager": "minimax/MiniMax-M2.7"},
        },
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(model="openai/gpt-4o-mini"),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert resolve_model_slot(cfg, ModelSlot.scanner) == "openai/gpt-4o-mini"


def test_override_tier_b_fallback_to_triager() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        providers={
            "use_main_model_for_all": False,
            "tier_default": {"triager": "minimax/MiniMax-M2.7"},
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert resolve_model_slot(cfg, ModelSlot.tier_b) == "minimax/MiniMax-M2.7"


def test_lcm_summary_unified() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        providers={
            "use_main_model_for_all": True,
            "tier_default": {"triager": "minimax/MiniMax-M2.7"},
        },
        lcm=LcmWorkspaceConfig(summary_model="anthropic/claude-haiku-4-5"),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert resolve_model_slot(cfg, ModelSlot.lcm_summary) == "minimax/MiniMax-M2.7"


def test_fill_missing_only_seeds_absent_slots() -> None:
    doc: dict[str, object] = {
        "providers": {
            "use_main_model_for_all": False,
            "tier_default": {"triager": "main-m", "B": "custom-b"},
        },
    }
    fill_missing_model_slots_from_triager(doc)  # type: ignore[arg-type]
    tier = doc["providers"]["tier_default"]  # type: ignore[index]
    assert isinstance(tier, dict)
    assert tier["B"] == "custom-b"
    assert tier["C"] == "main-m"
    assert tier["B"] == "custom-b"


def test_model_slot_for_config_dot_path_tier_b() -> None:
    assert model_slot_for_config_dot_path("providers.tier_default.B") == ModelSlot.tier_b
    assert model_slot_for_config_dot_path("gateway.port") is None


def test_maybe_split_unified_model_on_config_set() -> None:
    doc: dict[str, object] = {
        "providers": {
            "use_main_model_for_all": True,
            "tier_default": {"triager": "minimax/MiniMax-M3", "B": "openai/gpt-5.5"},
        },
    }
    maybe_split_unified_model_on_config_set(  # type: ignore[arg-type]
        doc,
        "providers.tier_default.B",
        "openai/gpt-5.5",
    )
    providers = doc["providers"]
    assert isinstance(providers, dict)
    assert providers["use_main_model_for_all"] is False
    tier = providers["tier_default"]
    assert isinstance(tier, dict)
    assert tier["B"] == "openai/gpt-5.5"
    assert tier["C"] == "minimax/MiniMax-M3"
    assert tier["triager"] == "minimax/MiniMax-M3"


def test_maybe_split_unified_model_skips_when_same_as_triager() -> None:
    doc: dict[str, object] = {
        "providers": {
            "use_main_model_for_all": True,
            "tier_default": {"triager": "minimax/M3", "B": "minimax/M3"},
        },
    }
    maybe_split_unified_model_on_config_set(  # type: ignore[arg-type]
        doc,
        "providers.tier_default.B",
        "minimax/M3",
    )
    providers = doc["providers"]
    assert isinstance(providers, dict)
    assert providers["use_main_model_for_all"] is True


def test_transport_from_providers_models() -> None:
    assert (
        resolve_transport_for_model_id(
            {"models": {"x": {"transport": "anthropic"}}},
            "x",
        )
        == "anthropic"
    )


def test_minimax_catalog_defaults_to_chat_completions_transport() -> None:
    assert resolve_transport_for_model_id({}, "minimax/MiniMax-M2.7") == "chat_completions"


def test_resolve_wire_model_strips_minimax_prefix() -> None:
    assert resolve_wire_model_id("minimax/MiniMax-M2.7") == "MiniMax-M2.7"
    assert is_minimax_catalog_model("minimax/MiniMax-M2.7")


def test_is_minimax_model_matches_catalog_and_bare_wire_name() -> None:
    """Bare wire names (prefix stripped) are still recognized as MiniMax (not OpenAI)."""
    from sevn.config.model_resolution import is_minimax_model

    assert is_minimax_model("minimax/MiniMax-M3")
    assert is_minimax_model("MiniMax-M3")  # bare wire name
    assert is_minimax_model("minimax-m2.7")
    assert not is_minimax_model("openai/gpt-4o")
    assert not is_minimax_model("gpt-4o")


def test_workspace_has_minimax_any_slot() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        providers={"tier_default": {"B": "minimax/MiniMax-M2.7"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert workspace_has_minimax_catalog_model(cfg)


def test_legacy_minimax_openai_base_url_normalized() -> None:
    assert (
        resolve_minimax_anthropic_base_url("https://api.minimax.io/v1")
        == "https://api.minimax.io/anthropic/v1"
    )


def test_minimax_provider_transport_override_anthropic() -> None:
    """Provider-level minimax.transport=anthropic wins over the chat_completions default."""
    assert (
        resolve_transport_for_model_id(
            {"minimax": {"transport": "anthropic"}},
            "minimax/MiniMax-M3",
        )
        == "anthropic"
    )


def test_minimax_per_model_transport_override_wins_over_provider() -> None:
    """Per-model override in providers.models wins over providers.minimax.transport."""
    assert (
        resolve_transport_for_model_id(
            {
                "minimax": {"transport": "chat_completions"},
                "models": {"minimax/MiniMax-M3": {"transport": "anthropic"}},
            },
            "minimax/MiniMax-M3",
        )
        == "anthropic"
    )


def test_minimax_transport_default_is_chat_completions_without_override() -> None:
    """Without any override, minimax/* defaults to chat_completions (OpenAI wire)."""
    assert resolve_transport_for_model_id({}, "minimax/MiniMax-M2.7") == "chat_completions"
    assert (
        resolve_transport_for_model_id({"minimax": {}}, "minimax/MiniMax-M2.7")
        == "chat_completions"
    )


def test_non_minimax_unaffected_by_minimax_transport() -> None:
    """Non-minimax models are not affected by providers.minimax.transport."""
    assert (
        resolve_transport_for_model_id(
            {"minimax": {"transport": "chat_completions"}},
            "anthropic/claude-sonnet-4-20250514",
        )
        == "chat_completions"
    )
    assert (
        resolve_transport_for_model_id(
            {"minimax": {"transport": "chat_completions"}},
            "openai/gpt-4o",
        )
        == "chat_completions"
    )


def test_resolve_minimax_openai_base_url_default() -> None:
    from sevn.config.model_resolution import resolve_minimax_openai_base_url

    assert resolve_minimax_openai_base_url(None) == "https://api.minimax.io/v1"
    assert resolve_minimax_openai_base_url("  ") == "https://api.minimax.io/v1"


def test_resolve_minimax_openai_base_url_custom() -> None:
    from sevn.config.model_resolution import resolve_minimax_openai_base_url

    assert (
        resolve_minimax_openai_base_url("https://custom.minimax.io/v1")
        == "https://custom.minimax.io/v1"
    )
