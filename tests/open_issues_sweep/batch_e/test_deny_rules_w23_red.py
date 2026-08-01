"""W23.5 — user-defined deny rules take precedence (#80 → W26, D15 additive-deny)."""

from __future__ import annotations

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.agent_turn import _permission_policy_from_workspace
from sevn.tools.permissions import AllowAllPermissionPolicy

_DENY_RULES_FIXTURE: dict[str, object] = {
    "default_profile": "owner_permissive",
    "profiles": {
        "owner_permissive": {"mode": "abac"},
    },
    "deny_rules": [
        {
            "tool": "sandbox_exec",
            "pattern": r"rm\s+-rf",
            "reason": "operator blocked destructive rm",
        },
    ],
}


def test_deny_rules_config_loads_from_permissions_block() -> None:
    """``permissions.deny_rules`` is available to the gateway policy resolver."""
    from sevn.tools.deny_rules import load_deny_rules_from_workspace

    ws = WorkspaceConfig.minimal(permissions=_DENY_RULES_FIXTURE)
    rules = load_deny_rules_from_workspace(ws)
    assert len(rules) == 1
    assert rules[0].tool == "sandbox_exec"
    assert "rm" in (rules[0].pattern or "")


def test_user_deny_rule_blocks_even_in_allow_all_mode() -> None:
    """Deny rules apply even when the session ceiling is permissive (D15)."""
    from sevn.tools.deny_rules import evaluate_deny_rules

    decision = evaluate_deny_rules(
        tool_name="sandbox_exec",
        args={"command": "rm -rf /tmp/demo"},
        rules=_DENY_RULES_FIXTURE["deny_rules"],  # type: ignore[arg-type]
        base_policy=AllowAllPermissionPolicy(),
    )
    assert decision.denied is True
    assert decision.reason == "operator blocked destructive rm"


def test_deny_rule_blocks_abac_owner_for_matching_tool() -> None:
    """ABAC owner permissive mode does not override an explicit deny rule."""
    ws = WorkspaceConfig.minimal(permissions=_DENY_RULES_FIXTURE)
    policy = _permission_policy_from_workspace(ws, channel="telegram", user_id="42")
    assert isinstance(policy, AllowAllPermissionPolicy) or policy.may_invoke("read")

    from sevn.tools.deny_rules import evaluate_deny_rules

    decision = evaluate_deny_rules(
        tool_name="sandbox_exec",
        args={"command": "rm -rf /"},
        rules=_DENY_RULES_FIXTURE["deny_rules"],  # type: ignore[arg-type]
        base_policy=policy,
    )
    assert decision.denied is True


def test_deny_decision_audit_log_redacts_secrets() -> None:
    """Approval/deny audit lines never include tool args secrets."""
    from loguru import logger as loguru_logger

    from sevn.tools.deny_rules import log_deny_decision

    secret_arg = "token=super-secret-value"
    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="INFO")
    try:
        log_deny_decision(
            tool_name="integration_call",
            args={"headers": secret_arg},
            reason="operator denied outbound",
            session_id="sess-deny-1",
        )
    finally:
        loguru_logger.remove(sink_id)
    combined = " ".join(captured)
    assert "super-secret-value" not in combined
    assert "operator denied outbound" in combined
