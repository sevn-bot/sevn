"""Minimal permission surfaces for invoke-time gating (`specs/11-tools-registry.md` §8).

Full ABAC merges with specs 06-08 land later; callers substitute workspace-bound
policies implementing ``PermissionPolicy``.

Module: sevn.tools.permissions
Depends: (none)

Exports:
    PermissionPolicy — Protocol checked before decorated tool bodies run.
    AllowAllPermissionPolicy — permissive Phase-2 stub.
    DenyingPermissionPolicy — hard-deny stub for tests/gateway sandboxes.
    AttributeBasedPermissionPolicy — deny egress/exec/mutating tools for untrusted principals.
    resolve_principal — map channel + user id to owner/untrusted/unknown.
    apply_permission_scope_narrowing — wrap a base policy with Triager narrowing hints.

Examples:
    >>> AllowAllPermissionPolicy().may_invoke("anything")
    True
    >>> DenyingPermissionPolicy().may_invoke("nope")
    False
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable


@runtime_checkable
class PermissionPolicy(Protocol):
    """Authorize a tool invocation by global name."""

    def may_invoke(self, tool_name: str) -> bool:
        """Decide runtime authorization for ``tool_name``.

                Args:
        tool_name (str): Canonical tool registry identifier.

                Returns:
                    bool: Permit when invocation should succeed.

                Examples:
                    >>> class _Concrete:
                    ...     def may_invoke(self, tool_name: str) -> bool:
                    ...         return True
                    ...
                    >>> isinstance(_Concrete(), PermissionPolicy)
                    True
        """

        ...


class AllowAllPermissionPolicy:
    """Permissive stub until ABAC payloads wire through the gateway."""

    def may_invoke(self, tool_name: str) -> bool:
        """Permit unconditionally.

                Args:
        tool_name (str): Tool identifier ignored in this stub.

                Returns:
                    bool: Always ``True``.

                Examples:
                    >>> AllowAllPermissionPolicy().may_invoke("x")
                    True
        """

        return True


class DenyingPermissionPolicy:
    """Strict stub for negative executor tests."""

    def may_invoke(self, tool_name: str) -> bool:
        """Reject every tool call.

                Args:
        tool_name (str): Tool identifier retained for ABI parity.

                Returns:
                    bool: Always ``False``.

                Examples:
                    >>> DenyingPermissionPolicy().may_invoke("anything")
                    False
        """

        return False


# ---------------------------------------------------------------------------
# ABAC attribute sets (W4 — `specs/11-tools-registry.md` §8)
# ---------------------------------------------------------------------------

#: Exact tool names classified as egress (network/external-service calls).
_EGRESS_TOOLS: frozenset[str] = frozenset({"integration_call"})

#: Prefixes for egress tools resolved by name-matching (e.g. ``web_*``).
_EGRESS_PREFIXES: tuple[str, ...] = ("web_",)

#: Exact tool names classified as exec (arbitrary code / subprocess execution).
_EXEC_TOOLS: frozenset[str] = frozenset({"sandbox_exec", "process"})

#: Prefixes for exec tools (e.g. ``terminal_*``).
_EXEC_PREFIXES: tuple[str, ...] = ("terminal_",)

#: Exact tool names classified as mutating (file-system write / destructive ops).
_MUTATING_TOOLS: frozenset[str] = frozenset({"write", "edit", "delete", "write_workspace_md"})

#: Prefixes for mutating tools (e.g. ``move_*``).
_MUTATING_PREFIXES: tuple[str, ...] = ("move_",)

#: Principal kinds recognised by :class:`AttributeBasedPermissionPolicy`.
PrincipalKind = Literal["owner", "untrusted", "unknown"]


def _tool_is_restricted(tool_name: str) -> bool:
    """Return ``True`` when *tool_name* falls into any restricted attribute class.

    Egress, exec, and mutating tools are restricted for non-owner principals
    under the ABAC policy (W4 — ``specs/11-tools-registry.md`` §8).

    Args:
        tool_name (str): Canonical tool registry identifier.

    Returns:
        bool: ``True`` when the tool is egress, exec, or mutating.

    Examples:
        >>> _tool_is_restricted("web_search")
        True
        >>> _tool_is_restricted("sandbox_exec")
        True
        >>> _tool_is_restricted("delete")
        True
        >>> _tool_is_restricted("move_file")
        True
        >>> _tool_is_restricted("read")
        False
        >>> _tool_is_restricted("serp")
        False
    """
    if tool_name in _EGRESS_TOOLS or tool_name in _EXEC_TOOLS or tool_name in _MUTATING_TOOLS:
        return True
    for prefix in _EGRESS_PREFIXES:
        if tool_name.startswith(prefix):
            return True
    for prefix in _EXEC_PREFIXES:
        if tool_name.startswith(prefix):
            return True
    return any(tool_name.startswith(prefix) for prefix in _MUTATING_PREFIXES)


class AttributeBasedPermissionPolicy:
    """ABAC policy: allow all for the owner; deny egress/exec/mutating for untrusted principals.

    ``principal`` is resolved at gateway-turn construction time from the session's
    ``channel`` + ``user_id`` relative to the workspace's ``channels.telegram.allowed_users``
    allowlist (owner = first allowlist entry on the ``telegram`` channel, or any authenticated
    session on a loopback-bound Web UI).  All other principals resolve to ``"untrusted"``
    (known but not on the allowlist) or ``"unknown"`` (no identity information).

    The loopback / owner principal preserves today's single-operator behaviour unchanged
    (D4: default posture must NOT regress Telegram/local-Web usage).

    Args:
        principal (PrincipalKind): Resolved trust level for this gateway turn.

    Examples:
        >>> AttributeBasedPermissionPolicy("owner").may_invoke("web_search")
        True
        >>> AttributeBasedPermissionPolicy("owner").may_invoke("sandbox_exec")
        True
        >>> AttributeBasedPermissionPolicy("untrusted").may_invoke("web_fetch")
        False
        >>> AttributeBasedPermissionPolicy("untrusted").may_invoke("sandbox_exec")
        False
        >>> AttributeBasedPermissionPolicy("untrusted").may_invoke("delete")
        False
        >>> AttributeBasedPermissionPolicy("untrusted").may_invoke("move_file")
        False
        >>> AttributeBasedPermissionPolicy("untrusted").may_invoke("read")
        True
        >>> AttributeBasedPermissionPolicy("unknown").may_invoke("integration_call")
        False
        >>> AttributeBasedPermissionPolicy("unknown").may_invoke("serp")
        True
    """

    def __init__(self, principal: PrincipalKind) -> None:
        """Bind a resolved principal for subsequent :meth:`may_invoke` checks.

        Args:
            principal (PrincipalKind): ``owner``, ``untrusted``, or ``unknown``.

        Returns:
            None

        Examples:
            >>> AttributeBasedPermissionPolicy("owner").principal
            'owner'
        """
        self._principal: PrincipalKind = principal

    @property
    def principal(self) -> PrincipalKind:
        """Resolved trust level bound at construction time.

        Returns:
            PrincipalKind: One of ``"owner"``, ``"untrusted"``, or ``"unknown"``.

        Examples:
            >>> AttributeBasedPermissionPolicy("owner").principal
            'owner'
        """
        return self._principal

    def may_invoke(self, tool_name: str) -> bool:
        """Permit the call when the principal is the owner, or the tool is unrestricted.

        Args:
            tool_name (str): Canonical tool registry identifier.

        Returns:
            bool: ``False`` only when a non-owner principal attempts an egress/exec/mutating tool.

        Examples:
            >>> AttributeBasedPermissionPolicy("owner").may_invoke("anything")
            True
            >>> AttributeBasedPermissionPolicy("untrusted").may_invoke("web_search")
            False
            >>> AttributeBasedPermissionPolicy("untrusted").may_invoke("read")
            True
        """
        if self._principal == "owner":
            return True
        return not _tool_is_restricted(tool_name)


def resolve_principal(
    *,
    channel: str,
    user_id: str,
    owner_user_ids: frozenset[str],
    loopback_channels: frozenset[str] | None = None,
) -> PrincipalKind:
    """Resolve the ABAC principal kind from session attributes.

    Owner resolution rules (D4):
    - Any session on a loopback-bound channel (``"local_open"``, ``"webchat"`` when
      the gateway is bound to ``127.0.0.1``/``localhost``) is treated as the owner.
    - On ``telegram`` (or any non-loopback channel), the ``user_id`` must appear in
      ``owner_user_ids`` (``channels.telegram.allowed_users``) to be owner.
    - Otherwise the principal is ``"untrusted"`` when ``user_id`` is non-empty, or
      ``"unknown"`` when it is empty / anonymous.

    This function is deterministic and has no I/O; the caller resolves the owner
    list and loopback status from workspace config + channel attributes at turn
    construction time.

    Args:
        channel (str): Session channel key (``"telegram"``, ``"webchat"``, ``"local_open"``, …).
        user_id (str): Session user identifier (may be empty for anonymous / system sessions).
        owner_user_ids (frozenset[str]): Set of stringified owner user ids from the workspace
            allowlist (``channels.telegram.allowed_users``).
        loopback_channels (frozenset[str] | None): Channel keys considered loopback-trusted.
            Defaults to ``{"local_open", "webchat"}`` when ``None``.

    Returns:
        PrincipalKind: ``"owner"``, ``"untrusted"``, or ``"unknown"``.

    Examples:
        >>> resolve_principal(channel="local_open", user_id="", owner_user_ids=frozenset())
        'owner'
        >>> resolve_principal(channel="telegram", user_id="123", owner_user_ids=frozenset({"123"}))
        'owner'
        >>> resolve_principal(channel="telegram", user_id="999", owner_user_ids=frozenset({"123"}))
        'untrusted'
        >>> resolve_principal(channel="telegram", user_id="", owner_user_ids=frozenset())
        'unknown'
        >>> resolve_principal(channel="webchat", user_id="anon", owner_user_ids=frozenset())
        'owner'
    """
    effective_loopback = (
        loopback_channels if loopback_channels is not None else frozenset({"local_open", "webchat"})
    )
    if channel in effective_loopback:
        return "owner"
    if user_id and user_id in owner_user_ids:
        return "owner"
    if user_id:
        return "untrusted"
    return "unknown"


def apply_permission_scope_narrowing(
    base: PermissionPolicy | None,
    narrowing: str | None,
) -> PermissionPolicy | None:
    """Narrow an existing policy using Triager hints (`specs/14-executor-tier-b.md` §3.1).

    When ``narrowing`` is None or ``base`` is None, returns ``base`` unchanged.

    Supported sentinel values (MVP):

    - ``deny_integration`` — blocks ``integration_call`` only.

        Args:
        base (PermissionPolicy | None): Session template policy ceiling.
        narrowing (str | None): ``TriageResult.permission_scope_narrowing``.

        Returns:
            PermissionPolicy | None: Possibly wrapped policy, or original ``base``.

        Examples:
            >>> p = apply_permission_scope_narrowing(AllowAllPermissionPolicy(), "deny_integration")
            >>> p is not None and p.may_invoke("integration_call")
            False
    """

    if base is None or narrowing is None:
        return base
    if narrowing == "deny_integration":
        bound = base

        class _DenyIntegration:
            def may_invoke(self, tool_name: str) -> bool:
                if tool_name == "integration_call":
                    return False
                return bound.may_invoke(tool_name)

        return _DenyIntegration()
    return base


__all__ = [
    "AllowAllPermissionPolicy",
    "AttributeBasedPermissionPolicy",
    "DenyingPermissionPolicy",
    "PermissionPolicy",
    "PrincipalKind",
    "apply_permission_scope_narrowing",
    "resolve_principal",
]
