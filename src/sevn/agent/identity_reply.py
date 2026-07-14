"""Resolved ``IDENTITY.md`` replies for identity turns (live-session W8).

Module: sevn.agent.identity_reply
Depends: re, sevn.agent.triager.routing_policy, sevn.gateway.onboarding.first_session, sevn.prompts.tier_b

Exports:
    is_pure_identity_message — ``who are you`` / name questions without capability asks.
    resolve_workspace_identity — canonical ``(name, role)`` from workspace ``IDENTITY.md``.
    compose_identity_reply — deterministic tier-A-style identity answer when name resolves.
    identity_bootstrap_incomplete_fields — placeholder labels for boot diagnostics.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from sevn.agent.triager.routing_policy import is_identity_or_capability_message
from sevn.gateway.onboarding.first_session import missing_user_md_bootstrap_fields
from sevn.prompts.tier_b import (
    _extract_identity_name,
    _extract_identity_role,
    _read_identity_doc,
)

if TYPE_CHECKING:
    from pathlib import Path

_CAPABILITY_IDENTITY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\s*what\s+can\s+you\s+do\b", re.I),
    re.compile(r"^\s*what\s+do\s+you\s+do\b", re.I),
    re.compile(r"^\s*list\s+(your\s+)?(tools|skills)\b", re.I),
    re.compile(r"^\s*what\s+(tools|skills)\b", re.I),
    re.compile(r"^\s*which\s+model\b", re.I),
)

_PRODUCT_AS_NAME: Final[frozenset[str]] = frozenset({"sevn.bot", "sevn", "sevn bot"})


def is_pure_identity_message(message: str) -> bool:
    """Return True for name/self questions that should not invoke tier-B LLM.

    Excludes capability/model/tool-list asks (those stay on tier B with registry context).

    Args:
        message (str): Operator message text.

    Returns:
        bool: True for ``who are you``, ``what's your name``, etc.

    Examples:
        >>> is_pure_identity_message("who are you?")
        True
        >>> is_pure_identity_message("what can you do?")
        False
    """
    text = message.strip()
    if not text or not is_identity_or_capability_message(text):
        return False
    return not any(p.search(text) for p in _CAPABILITY_IDENTITY_PATTERNS)


def resolve_workspace_identity(content_root: Path) -> tuple[str, str]:
    """Read canonical agent name and role from ``IDENTITY.md``.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        tuple[str, str]: ``(name, role)``; empty strings when unresolved.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "IDENTITY.md").write_text(
        ...         "## Name\\n\\ntestmee\\n\\n## Role\\nhelper",
        ...         encoding="utf-8",
        ...     )
        ...     resolve_workspace_identity(root)
        ('testmee', 'helper')
    """
    body = _read_identity_doc(content_root)
    return _extract_identity_name(body), _extract_identity_role(body)


def _resolved_display_name(
    content_root: Path,
    *,
    agent_display_name: str,
) -> str:
    """Pick the operator-facing name, never the product label ``sevn.bot``.

    Args:
        content_root (Path): Workspace content root.
        agent_display_name (str): ``agent.display_name`` from ``sevn.json``.

    Returns:
        str: Resolved name or empty string.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "IDENTITY.md").write_text("## Name\\n\\nNova", encoding="utf-8")
        ...     _resolved_display_name(root, agent_display_name="Sevn")
        'Nova'
    """
    name, _ = resolve_workspace_identity(content_root)
    if name and name.strip().lower() not in _PRODUCT_AS_NAME:
        return name.strip()
    fallback = (agent_display_name or "").strip()
    if fallback and fallback.lower() not in _PRODUCT_AS_NAME:
        return fallback
    return ""


def compose_identity_reply(
    content_root: Path,
    *,
    agent_display_name: str = "",
) -> str | None:
    """Build a deterministic identity answer from resolved ``IDENTITY.md`` fields.

    Returns ``None`` when the canonical name is still a placeholder so tier B can read
    ``IDENTITY.md`` via tools instead of inventing a product label.

    Args:
        content_root (Path): Workspace content root.
        agent_display_name (str): Fallback from ``resolve_agent_display_name``.

    Returns:
        str | None: Markdown reply or ``None`` when name is unresolved.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "IDENTITY.md").write_text(
        ...         "## Name\\n\\ntestmee\\n\\n## Role\\nPersonal helper.",
        ...         encoding="utf-8",
        ...     )
        ...     reply = compose_identity_reply(root)
        ...     reply is not None and "testmee" in reply and "sevn.bot" not in reply.lower()
        True
    """
    name = _resolved_display_name(content_root, agent_display_name=agent_display_name)
    if not name:
        return None
    _, role = resolve_workspace_identity(content_root)
    role_text = role.strip().rstrip(".") if role else ""
    if role_text:
        return f"I'm **{name}** — {role_text}."
    return f"I'm **{name}**."


def identity_bootstrap_incomplete_fields(content_root: Path) -> tuple[str, ...]:
    """Return bootstrap field labels still holding template placeholders.

    Used for ``workspace.layout_mismatch`` boot traces when narrative files exist but
    are not yet personalised.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        tuple[str, ...]: Labels such as ``USER.md:Name`` or ``IDENTITY.md:Name``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.seed import load_template
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "IDENTITY.md").write_text(
        ...         load_template("IDENTITY.md"),
        ...         encoding="utf-8",
        ...     )
        ...     "IDENTITY.md:Name" in identity_bootstrap_incomplete_fields(root)
        True
    """
    issues: list[str] = []
    identity_path = content_root / "IDENTITY.md"
    if not identity_path.is_file():
        issues.append("IDENTITY.md:missing")
    else:
        name, _ = resolve_workspace_identity(content_root)
        if not name:
            issues.append("IDENTITY.md:Name")
    for label in missing_user_md_bootstrap_fields(content_root):
        issues.append(f"USER.md:{label}")
    return tuple(issues)


__all__ = [
    "compose_identity_reply",
    "identity_bootstrap_incomplete_fields",
    "is_pure_identity_message",
    "resolve_workspace_identity",
]
