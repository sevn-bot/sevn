"""User-defined deny rules extending workspace ``permissions`` (#80, open-issues-sweep W26).

Deny rules are additive-only (D15): they can block tool calls even when the session
permission profile is permissive. Evaluation runs at ``check_permission_before_dispatch``
and ``ToolExecutor.dispatch`` — no third policy location.

Module: sevn.tools.deny_rules
Depends: sevn.config.workspace_config, sevn.logging.log_redact, sevn.tools.context, sevn.tools.codes

Exports:
    DenyRule — one configured deny rule.
    DenyDecision — evaluation outcome.
    parse_deny_rules — parse raw config rows.
    load_deny_rules_from_workspace — parse ``permissions.deny_rules``.
    evaluate_deny_rules — match tool + args against rules.
    enveloped_deny_with_reason — model-facing PERMISSION_DENIED envelope.
    log_deny_decision — redacted audit log line.
    check_deny_rules_for_dispatch — defense-in-depth helper for ``ToolExecutor``.
    deny_envelope_from_rules — shared pre-dispatch deny envelope builder.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from sevn.logging.log_redact import redact_log_line
from sevn.tools.codes import ToolResultCode

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.tools.context import ToolContext
    from sevn.tools.permissions import PermissionPolicy

_SECRET_REF_RE = re.compile(r"\$\{SECRET:[^}]+\}")


@dataclass(frozen=True)
class DenyRule:
    """One operator-configured deny rule under ``permissions.deny_rules``."""

    tool: str | None = None
    pattern: str | None = None
    domain: str | None = None
    path: str | None = None
    reason: str = "Permission denied"


@dataclass(frozen=True)
class DenyDecision:
    """Outcome of evaluating deny rules for one tool invocation."""

    denied: bool
    reason: str | None = None


def _parse_rule(raw: object) -> DenyRule | None:
    """Parse one raw config object into a :class:`DenyRule`.

    Args:
        raw (object): One ``deny_rules`` list element.

    Returns:
        DenyRule | None: Parsed rule, or ``None`` when invalid or empty.

    Examples:
        >>> _parse_rule({"tool": "delete", "reason": "blocked"}).tool
        'delete'
    """
    if not isinstance(raw, dict):
        return None
    tool_raw = raw.get("tool")
    tool = str(tool_raw).strip() if tool_raw is not None and str(tool_raw).strip() else None
    pattern_raw = raw.get("pattern")
    pattern = (
        str(pattern_raw).strip() if pattern_raw is not None and str(pattern_raw).strip() else None
    )
    domain_raw = raw.get("domain")
    domain = str(domain_raw).strip() if domain_raw is not None and str(domain_raw).strip() else None
    path_raw = raw.get("path")
    path = str(path_raw).strip() if path_raw is not None and str(path_raw).strip() else None
    reason_raw = raw.get("reason")
    reason = (
        str(reason_raw).strip()
        if reason_raw is not None and str(reason_raw).strip()
        else "Permission denied"
    )
    if not any((tool, pattern, domain, path)):
        return None
    return DenyRule(tool=tool, pattern=pattern, domain=domain, path=path, reason=reason)


def parse_deny_rules(raw_rules: object) -> tuple[DenyRule, ...]:
    """Parse a ``deny_rules`` config list into immutable rule objects.

    Args:
        raw_rules (object): ``permissions.deny_rules`` value from ``sevn.json``.

    Returns:
        tuple[DenyRule, ...]: Parsed rules; empty when ``raw_rules`` is not a list.

    Examples:
        >>> rules = parse_deny_rules([{"tool": "delete", "reason": "blocked"}])
        >>> rules[0].tool
        'delete'
    """
    if not isinstance(raw_rules, list):
        return ()
    parsed: list[DenyRule] = []
    for item in raw_rules:
        rule = _parse_rule(item)
        if rule is not None:
            parsed.append(rule)
    return tuple(parsed)


def load_deny_rules_from_workspace(workspace: WorkspaceConfig) -> tuple[DenyRule, ...]:
    """Load ``permissions.deny_rules`` from a workspace config document.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        tuple[DenyRule, ...]: Parsed deny rules for the workspace.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(permissions={"deny_rules": [{"tool": "delete"}]})
        >>> load_deny_rules_from_workspace(ws)[0].tool
        'delete'
    """
    raw = workspace.permissions if isinstance(workspace.permissions, dict) else {}
    return parse_deny_rules(raw.get("deny_rules"))


def _redact_args_for_log(args: dict[str, Any]) -> str:
    """Return a JSON summary of tool args with secrets redacted for audit logs.

    Args:
        args (dict[str, Any]): Raw tool arguments.

    Returns:
        str: JSON string safe for structured audit logs.

    Examples:
        >>> "secret" not in _redact_args_for_log({"token": "token=secret"})
        True
    """

    def _redact(value: object) -> object:
        if isinstance(value, str):
            cleaned = _SECRET_REF_RE.sub("<redacted-secret-ref>", value)
            return redact_log_line(cleaned)
        if isinstance(value, dict):
            return {str(k): _redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_redact(item) for item in value]
        return value

    return json.dumps(_redact(dict(args)), sort_keys=True, default=str)


def _arg_text(args: dict[str, Any]) -> str:
    """Join common tool-arg fields into one searchable string for pattern matching.

    Args:
        args (dict[str, Any]): Validated tool arguments.

    Returns:
        str: Concatenated command/url/path/domain/query text.

    Examples:
        >>> _arg_text({"command": "rm -rf /tmp"})
        'rm -rf /tmp'
    """
    parts: list[str] = []
    for key in ("command", "url", "path", "domain", "query"):
        val = args.get(key)
        if val is not None:
            parts.append(str(val))
    if not parts:
        parts.append(json.dumps(args, sort_keys=True, default=str))
    return "\n".join(parts)


def _rule_matches(rule: DenyRule, *, tool_name: str, args: dict[str, Any]) -> bool:
    """Return whether ``rule`` matches ``tool_name`` and ``args``.

    Args:
        rule (DenyRule): Configured deny rule.
        tool_name (str): Registry tool name.
        args (dict[str, Any]): Validated tool arguments.

    Returns:
        bool: ``True`` when all configured matchers succeed.

    Examples:
        >>> rule = DenyRule(tool="delete")
        >>> _rule_matches(rule, tool_name="delete", args={})
        True
    """
    if rule.tool is not None and rule.tool != tool_name:
        return False
    text = _arg_text(args)
    if rule.pattern is not None:
        try:
            if not re.search(rule.pattern, text):
                return False
        except re.error:
            return False
    if rule.domain is not None and rule.domain.lower() not in text.lower():
        return False
    return rule.path is None or rule.path in text


def evaluate_deny_rules(
    *,
    tool_name: str,
    args: dict[str, Any],
    rules: list[dict[str, Any]] | tuple[DenyRule, ...] | list[DenyRule],
    base_policy: PermissionPolicy,
    operator_overrides: frozenset[str] | None = None,
) -> DenyDecision:
    """Return a deny decision when a configured rule matches (D15 additive-deny).

    Deny rules apply even when ``base_policy`` is permissive. Operator session
    acknowledgements in ``operator_overrides`` skip deny evaluation for that tool.

    Args:
        tool_name (str): Registry tool name being dispatched.
        args (dict[str, Any]): Validated tool arguments.
        rules (list[dict[str, Any]] | tuple[DenyRule, ...] | list[DenyRule]): Configured rules.
        base_policy (PermissionPolicy): Session permission ceiling (informational for D15).
        operator_overrides (frozenset[str] | None): Session-acked tools that bypass deny rules.

    Returns:
        DenyDecision: ``denied=True`` with ``reason`` when a rule matches.

    Examples:
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> decision = evaluate_deny_rules(
        ...     tool_name="delete",
        ...     args={},
        ...     rules=[{"tool": "delete", "reason": "blocked"}],
        ...     base_policy=AllowAllPermissionPolicy(),
        ... )
        >>> decision.denied
        True
    """
    _ = base_policy
    if operator_overrides and tool_name in operator_overrides:
        return DenyDecision(denied=False)
    normalized: tuple[DenyRule, ...]
    if rules and isinstance(rules[0], DenyRule):
        normalized = tuple(rules)  # type: ignore[arg-type]
    else:
        normalized = parse_deny_rules(rules)
    for rule in normalized:
        if _rule_matches(rule, tool_name=tool_name, args=args):
            return DenyDecision(denied=True, reason=rule.reason)
    return DenyDecision(denied=False)


def enveloped_deny_with_reason(*, tool_name: str, reason: str) -> str:
    """Serialize a model-facing denial envelope with the operator reason.

    Args:
        tool_name (str): Registry tool name (reserved for future structured payloads).
        reason (str): Human-readable denial reason for the model.

    Returns:
        str: JSON envelope including ``message`` and ``PERMISSION_DENIED`` code.

    Examples:
        >>> import json
        >>> blob = json.loads(enveloped_deny_with_reason(tool_name="delete", reason="no"))
        >>> blob["message"]
        'no'
    """
    _ = tool_name
    payload = {
        "ok": False,
        "message": reason,
        "error": reason,
        "code": str(ToolResultCode.PERMISSION_DENIED),
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def log_deny_decision(
    *,
    tool_name: str,
    args: dict[str, Any],
    reason: str,
    session_id: str,
) -> None:
    """Emit a redacted audit log line for a deny-rule block.

    Args:
        tool_name (str): Registry tool name.
        args (dict[str, Any]): Tool arguments (redacted before logging).
        reason (str): Deny reason shown to operators/models.
        session_id (str): Active gateway session id.

    Returns:
        None: Side-effect only.

    Examples:
        >>> log_deny_decision(
        ...     tool_name="delete",
        ...     args={"path": "x"},
        ...     reason="blocked",
        ...     session_id="s1",
        ... ) is None
        True
    """
    safe_args = _redact_args_for_log(args)
    logger.info(
        "tool deny decision tool={} session={} reason={} args={}",
        tool_name,
        session_id,
        redact_log_line(reason),
        safe_args,
    )


def check_deny_rules_for_dispatch(
    ctx: ToolContext,
    tool_name: str,
    args: dict[str, Any],
) -> str | None:
    """Defense-in-depth deny-rule check for ``ToolExecutor.dispatch``.

    Args:
        ctx (ToolContext): Active dispatch context carrying ``deny_rules``.
        tool_name (str): Registry tool name.
        args (dict[str, Any]): Validated tool arguments.

    Returns:
        str | None: Denial envelope JSON when blocked; ``None`` when allowed.

    Examples:
        >>> check_deny_rules_for_dispatch.__name__
        'check_deny_rules_for_dispatch'
    """
    rules = ctx.deny_rules
    if not rules:
        return None
    if tool_name in ctx.human_acknowledged_tools:
        return None
    base = ctx.permissions
    from sevn.tools.permissions import AllowAllPermissionPolicy

    decision = evaluate_deny_rules(
        tool_name=tool_name,
        args=args,
        rules=rules,
        base_policy=base if base is not None else AllowAllPermissionPolicy(),
        operator_overrides=ctx.human_acknowledged_tools,
    )
    if not decision.denied:
        return None
    log_deny_decision(
        tool_name=tool_name,
        args=args,
        reason=decision.reason or "Permission denied",
        session_id=ctx.session_id,
    )
    return enveloped_deny_with_reason(
        tool_name=tool_name,
        reason=decision.reason or "Permission denied",
    )


def deny_envelope_from_rules(
    *,
    tool_name: str,
    args: dict[str, Any],
    rules: tuple[DenyRule, ...],
    session_id: str,
    operator_overrides: frozenset[str],
    base_policy: PermissionPolicy,
) -> str | None:
    """Evaluate deny rules and return an envelope when blocked.

    Args:
        tool_name (str): Registry tool name.
        args (dict[str, Any]): Validated tool arguments.
        rules (tuple[DenyRule, ...]): Parsed deny rules for the session.
        session_id (str): Active gateway session id.
        operator_overrides (frozenset[str]): Session-acked tools that bypass deny rules.
        base_policy (PermissionPolicy): Session permission ceiling.

    Returns:
        str | None: Denial envelope JSON when blocked; ``None`` when allowed.

    Examples:
        >>> deny_envelope_from_rules.__name__
        'deny_envelope_from_rules'
    """
    if not rules:
        return None
    decision = evaluate_deny_rules(
        tool_name=tool_name,
        args=args,
        rules=rules,
        base_policy=base_policy,
        operator_overrides=operator_overrides,
    )
    if not decision.denied:
        return None
    reason = decision.reason or "Permission denied"
    log_deny_decision(tool_name=tool_name, args=args, reason=reason, session_id=session_id)
    return enveloped_deny_with_reason(tool_name=tool_name, reason=reason)


__all__ = [
    "DenyDecision",
    "DenyRule",
    "check_deny_rules_for_dispatch",
    "deny_envelope_from_rules",
    "enveloped_deny_with_reason",
    "evaluate_deny_rules",
    "load_deny_rules_from_workspace",
    "log_deny_decision",
    "parse_deny_rules",
]
