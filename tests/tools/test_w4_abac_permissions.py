"""W4 ABAC permission policy tests (`plan/forward-track-registry-bindings-permissions-v1gate-wave-plan.md` W4.4).

Acceptance criteria:
- Owner principal → all tools allowed (including egress/exec/mutating).
- Untrusted principal → web_fetch / sandbox_exec / delete denied with a typed permission envelope.
- read / serp still allowed for untrusted.
- Unknown principal → restricted tools also denied.
- _permission_policy_from_workspace with abac mode resolves owner from workspace config.
- loopback / local_open channel always resolves as owner (D4 regression guard).
"""

from __future__ import annotations

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.agent_turn import _permission_policy_from_workspace
from sevn.tools.permissions import (
    AllowAllPermissionPolicy,
    AttributeBasedPermissionPolicy,
    DenyingPermissionPolicy,
    _tool_is_restricted,
    resolve_principal,
)

# ---------------------------------------------------------------------------
# resolve_principal
# ---------------------------------------------------------------------------


class TestResolvePrincipal:
    def test_local_open_is_owner_regardless_of_user_id(self) -> None:
        assert (
            resolve_principal(channel="local_open", user_id="", owner_user_ids=frozenset())
            == "owner"
        )

    def test_webchat_is_owner_regardless_of_user_id(self) -> None:
        assert (
            resolve_principal(channel="webchat", user_id="anon", owner_user_ids=frozenset())
            == "owner"
        )

    def test_telegram_owner_user_id_match(self) -> None:
        assert (
            resolve_principal(channel="telegram", user_id="123", owner_user_ids=frozenset({"123"}))
            == "owner"
        )

    def test_telegram_non_owner_user_id(self) -> None:
        assert (
            resolve_principal(channel="telegram", user_id="999", owner_user_ids=frozenset({"123"}))
            == "untrusted"
        )

    def test_telegram_empty_user_id_no_owner_list(self) -> None:
        assert (
            resolve_principal(channel="telegram", user_id="", owner_user_ids=frozenset())
            == "unknown"
        )

    def test_telegram_with_user_id_but_empty_owner_list(self) -> None:
        assert (
            resolve_principal(channel="telegram", user_id="42", owner_user_ids=frozenset())
            == "untrusted"
        )

    def test_custom_loopback_channels(self) -> None:
        assert (
            resolve_principal(
                channel="myloopback",
                user_id="",
                owner_user_ids=frozenset(),
                loopback_channels=frozenset({"myloopback"}),
            )
            == "owner"
        )

    def test_default_loopback_does_not_include_telegram(self) -> None:
        # telegram is never in the default loopback set
        assert (
            resolve_principal(channel="telegram", user_id="", owner_user_ids=frozenset())
            == "unknown"
        )


# ---------------------------------------------------------------------------
# _tool_is_restricted
# ---------------------------------------------------------------------------


class TestToolIsRestricted:
    @pytest.mark.parametrize(
        "name",
        [
            "web_search",
            "web_fetch",
            "web_custom_tool",
            "integration_call",
            "sandbox_exec",
            "terminal_spawn",
            "terminal_run",
            "terminal_close",
            "process",
            "write",
            "edit",
            "delete",
            "move_file",
            "write_workspace_md",
        ],
    )
    def test_restricted_tools(self, name: str) -> None:
        assert _tool_is_restricted(name), f"expected {name!r} to be restricted"

    @pytest.mark.parametrize(
        "name",
        [
            "read",
            "serp",
            "get_page_content",
            "list_dir",
            "load_skill",
            "load_tool",
            "send_message",
            "memory_read",
        ],
    )
    def test_unrestricted_tools(self, name: str) -> None:
        assert not _tool_is_restricted(name), f"expected {name!r} to be unrestricted"


# ---------------------------------------------------------------------------
# AttributeBasedPermissionPolicy
# ---------------------------------------------------------------------------


class TestAttributeBasedPermissionPolicy:
    # --- owner principal ---

    def test_owner_allows_web_search(self) -> None:
        assert AttributeBasedPermissionPolicy("owner").may_invoke("web_search")

    def test_owner_allows_sandbox_exec(self) -> None:
        assert AttributeBasedPermissionPolicy("owner").may_invoke("sandbox_exec")

    def test_owner_allows_delete(self) -> None:
        assert AttributeBasedPermissionPolicy("owner").may_invoke("delete")

    def test_owner_allows_anything(self) -> None:
        p = AttributeBasedPermissionPolicy("owner")
        for tool in (
            "web_fetch",
            "integration_call",
            "terminal_spawn",
            "write",
            "edit",
            "move_file",
            "process",
        ):
            assert p.may_invoke(tool), f"owner should allow {tool!r}"

    # --- untrusted principal ---

    def test_untrusted_denies_web_fetch(self) -> None:
        assert not AttributeBasedPermissionPolicy("untrusted").may_invoke("web_fetch")

    def test_untrusted_denies_web_search(self) -> None:
        assert not AttributeBasedPermissionPolicy("untrusted").may_invoke("web_search")

    def test_untrusted_denies_sandbox_exec(self) -> None:
        assert not AttributeBasedPermissionPolicy("untrusted").may_invoke("sandbox_exec")

    def test_untrusted_denies_delete(self) -> None:
        assert not AttributeBasedPermissionPolicy("untrusted").may_invoke("delete")

    def test_untrusted_denies_write(self) -> None:
        assert not AttributeBasedPermissionPolicy("untrusted").may_invoke("write")

    def test_untrusted_denies_edit(self) -> None:
        assert not AttributeBasedPermissionPolicy("untrusted").may_invoke("edit")

    def test_untrusted_denies_move_file(self) -> None:
        assert not AttributeBasedPermissionPolicy("untrusted").may_invoke("move_file")

    def test_untrusted_denies_integration_call(self) -> None:
        assert not AttributeBasedPermissionPolicy("untrusted").may_invoke("integration_call")

    def test_untrusted_denies_process(self) -> None:
        assert not AttributeBasedPermissionPolicy("untrusted").may_invoke("process")

    def test_untrusted_denies_terminal_spawn(self) -> None:
        assert not AttributeBasedPermissionPolicy("untrusted").may_invoke("terminal_spawn")

    def test_untrusted_allows_read(self) -> None:
        assert AttributeBasedPermissionPolicy("untrusted").may_invoke("read")

    def test_untrusted_allows_serp(self) -> None:
        assert AttributeBasedPermissionPolicy("untrusted").may_invoke("serp")

    def test_untrusted_allows_load_skill(self) -> None:
        assert AttributeBasedPermissionPolicy("untrusted").may_invoke("load_skill")

    def test_untrusted_allows_memory_read(self) -> None:
        assert AttributeBasedPermissionPolicy("untrusted").may_invoke("memory_read")

    # --- unknown principal ---

    def test_unknown_denies_integration_call(self) -> None:
        assert not AttributeBasedPermissionPolicy("unknown").may_invoke("integration_call")

    def test_unknown_denies_web_fetch(self) -> None:
        assert not AttributeBasedPermissionPolicy("unknown").may_invoke("web_fetch")

    def test_unknown_allows_serp(self) -> None:
        assert AttributeBasedPermissionPolicy("unknown").may_invoke("serp")

    def test_unknown_allows_read(self) -> None:
        assert AttributeBasedPermissionPolicy("unknown").may_invoke("read")

    # --- principal property ---

    def test_principal_property(self) -> None:
        assert AttributeBasedPermissionPolicy("owner").principal == "owner"
        assert AttributeBasedPermissionPolicy("untrusted").principal == "untrusted"
        assert AttributeBasedPermissionPolicy("unknown").principal == "unknown"


# ---------------------------------------------------------------------------
# _permission_policy_from_workspace (gateway integration)
# ---------------------------------------------------------------------------


class TestPermissionPolicyFromWorkspace:
    def test_default_no_permissions_config_is_allow_all(self) -> None:
        ws = WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        )
        policy = _permission_policy_from_workspace(ws, channel="telegram", user_id="42")
        assert isinstance(policy, AllowAllPermissionPolicy)
        assert policy.may_invoke("web_search")

    def test_abac_mode_loopback_is_owner(self) -> None:
        ws = WorkspaceConfig(
            schema_version=1,
            permissions={
                "default_profile": "strict",
                "profiles": {"strict": {"mode": "abac"}},
            },
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        )
        policy = _permission_policy_from_workspace(ws, channel="local_open", user_id="")
        # loopback → owner → all allowed
        assert policy.may_invoke("web_search")
        assert policy.may_invoke("sandbox_exec")

    def test_abac_mode_webchat_is_owner(self) -> None:
        ws = WorkspaceConfig(
            schema_version=1,
            permissions={
                "default_profile": "strict",
                "profiles": {"strict": {"mode": "abac"}},
            },
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        )
        policy = _permission_policy_from_workspace(ws, channel="webchat", user_id="anon")
        assert policy.may_invoke("web_search")

    def test_abac_mode_telegram_owner_user_id_allows_all(self) -> None:
        from sevn.config.workspace_config import (
            ChannelsWorkspaceSectionConfig,
            TelegramChannelConfig,
        )

        ws = WorkspaceConfig(
            schema_version=1,
            permissions={
                "default_profile": "strict",
                "profiles": {"strict": {"mode": "abac"}},
            },
            channels=ChannelsWorkspaceSectionConfig(
                telegram=TelegramChannelConfig(allowed_users=[123])
            ),
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        )
        policy = _permission_policy_from_workspace(ws, channel="telegram", user_id="123")
        assert policy.may_invoke("web_search")
        assert policy.may_invoke("sandbox_exec")

    def test_abac_mode_telegram_untrusted_user_denied_egress(self) -> None:
        ws = WorkspaceConfig(
            schema_version=1,
            permissions={
                "default_profile": "strict",
                "profiles": {"strict": {"mode": "abac"}},
            },
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        )
        policy = _permission_policy_from_workspace(ws, channel="telegram", user_id="999")
        assert not policy.may_invoke("web_fetch")
        assert not policy.may_invoke("sandbox_exec")
        assert not policy.may_invoke("delete")
        # Read-only tools still pass
        assert policy.may_invoke("read")
        assert policy.may_invoke("serp")

    def test_deny_all_mode(self) -> None:
        ws = WorkspaceConfig(
            schema_version=1,
            permissions={
                "default_profile": "locked",
                "profiles": {"locked": {"mode": "deny_all"}},
            },
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        )
        policy = _permission_policy_from_workspace(ws, channel="telegram", user_id="1")
        assert isinstance(policy, DenyingPermissionPolicy)
        assert not policy.may_invoke("read")

    def test_deny_tools_list_static(self) -> None:
        ws = WorkspaceConfig(
            schema_version=1,
            permissions={
                "default_profile": "p",
                "profiles": {"p": {"deny_tools": ["web_search", "delete"]}},
            },
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        )
        policy = _permission_policy_from_workspace(ws, channel="telegram", user_id="1")
        assert not policy.may_invoke("web_search")
        assert not policy.may_invoke("delete")
        assert policy.may_invoke("read")

    def test_no_profile_key_falls_back_to_allow_all(self) -> None:
        ws = WorkspaceConfig(
            schema_version=1,
            permissions={"profiles": {"p": {"mode": "abac"}}},
            # no default_profile key
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        )
        policy = _permission_policy_from_workspace(ws, channel="telegram", user_id="42")
        assert isinstance(policy, AllowAllPermissionPolicy)

    def test_d4_regression_default_workspace_loopback(self) -> None:
        """D4: default posture must NOT regress single-operator Telegram/local-Web usage."""
        ws = WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        )
        for channel in ("telegram", "local_open", "webchat"):
            policy = _permission_policy_from_workspace(ws, channel=channel, user_id="1")
            assert policy.may_invoke("web_search"), f"default should allow web_search on {channel}"
            assert policy.may_invoke("sandbox_exec"), (
                f"default should allow sandbox_exec on {channel}"
            )
