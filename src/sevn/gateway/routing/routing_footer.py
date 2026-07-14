"""Telegram routing footer on first outbound bubble (`plan/operator-experience-wave-plan.md` Wave 6).

Module: sevn.gateway.routing.routing_footer
Depends: re, sevn.agent.triager.models, sevn.config.workspace_config

Exports:
    telegram_show_routing_enabled — read ``channels.telegram.show_routing``.
    format_subagent_tag — short ``⋮id`` attribution prefix (D7).
    format_routing_footer — one-line intent/tier/conf summary.
    append_routing_footer — attach footer to assistant text once per turn.
    strip_model_emitted_footer — remove footer-shaped lines from model output.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sevn.agent.triager.models import TriageResult
    from sevn.config.workspace_config import WorkspaceConfig


# Footer signature detector — matches any line that pairs ``intent=`` with ``conf=`` (with
# optional MarkdownV2 italic wrappers and tolerance for the corrupted ``er=`` / ``ier=`` /
# missing ``tier=`` token variants observed in the 2026-05-25 transcript). The regex is
# anchored to a single line; outbound hygiene strips matches before the gateway appends its
# own structured footer so duplicate or corrupted footers never reach the user
# (transcript-review item #7).
#
# Wave W3 (`plan/tier-b-quality-concurrency-config-wave-plan.md` §W3, D8): the canonical
# gateway footer also carries trailing ``· tools=[…] · skills=[…] · triager_s=N`` tokens
# *after* ``conf=`` (see :func:`format_routing_footer`). The earlier pattern anchored the
# line end immediately after the confidence value, so footers with those suffixes survived
# the persistence-time strip in ``channel_router.route_outgoing`` and leaked into
# ``visible_to_llm`` history — the executor then read them back and reproduced them
# mid-answer. The trailing ``[^\n]*?`` lets the match consume any further footer segments
# before the optional italic close / end-of-line.
_MODEL_EMITTED_FOOTER_RE = re.compile(
    r"^[ \t]*_?\s*intent\s*=[^\n]*?conf\s*=\s*[0-9.]+[^\n]*?_?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def telegram_show_routing_enabled(workspace: WorkspaceConfig) -> bool:
    """Return whether Telegram outbound should show a routing footer.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        bool: ``True`` when ``channels.telegram.show_routing`` is enabled.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> telegram_show_routing_enabled(WorkspaceConfig.minimal())
        False
    """
    channels = workspace.channels
    if channels is None or channels.telegram is None:
        return False
    return bool(channels.telegram.show_routing)


def format_subagent_tag(subagent_id: str) -> str:
    """Build the short sub-agent attribution prefix for parallel L1 replies (D7).

    Args:
        subagent_id (str): Registry short id (e.g. ``a1f3``).

    Returns:
        str: Tag ``⋮<id>`` suitable for prepending to a routing footer.

    Examples:
        >>> format_subagent_tag("a1f3")
        '⋮a1f3'
    """
    sid = subagent_id.strip()
    return f"⋮{sid}" if sid else ""


def format_routing_footer(
    triage: TriageResult,
    *,
    triager_ms: int | None = None,
) -> str:
    """Build the single-line routing footer from a ``TriageResult``.

    Wave 4 (`CONVERSATION_REVIEW_2026-05-28.md` §A2): when the triager already
    selected ``tools`` / ``skills`` and the gateway captured the triager LLM
    elapsed time, append them so the operator can see the routing decision +
    latency without reading the trace.

    Args:
        triage (TriageResult): Completed triage for the turn.
        triager_ms (int | None): Wall-clock milliseconds spent inside
            ``triage_turn`` for this turn. Rendered as whole seconds
            (``triager_s``) in the footer; omitted when ``None``.

    Returns:
        str: Footer line ``intent=… · tier=… · conf=…`` plus optional
            ``· tools=[…] · skills=[…] · triager_s=N``.

    Examples:
        >>> from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
        >>> triage = TriageResult(
        ...     intent=Intent.NEW_REQUEST,
        ...     complexity=ComplexityTier.B,
        ...     first_message="hi",
        ...     tools=["read", "log_query"],
        ...     skills=["lcm"],
        ...     mcp_servers_required=[],
        ...     confidence=0.82,
        ...     requires_vision=False,
        ...     requires_document=False,
        ... )
        >>> format_routing_footer(triage, triager_ms=712)
        'intent=NEW_REQUEST · tier=B · conf=0.82 · tools=[read,log_query] · skills=[lcm] · triager_s=1'
        >>> format_routing_footer(triage, triager_ms=8635)
        'intent=NEW_REQUEST · tier=B · conf=0.82 · tools=[read,log_query] · skills=[lcm] · triager_s=9'
        >>> format_routing_footer(triage)
        'intent=NEW_REQUEST · tier=B · conf=0.82 · tools=[read,log_query] · skills=[lcm]'
    """
    intent = triage.intent.value if hasattr(triage.intent, "value") else str(triage.intent)
    tier = (
        triage.complexity.value if hasattr(triage.complexity, "value") else str(triage.complexity)
    )
    parts: list[str] = [
        f"intent={intent}",
        f"tier={tier}",
        f"conf={triage.confidence:.2f}",
    ]
    if triage.tools:
        parts.append("tools=[" + ",".join(triage.tools) + "]")
    if triage.skills:
        parts.append("skills=[" + ",".join(triage.skills) + "]")
    if triager_ms is not None:
        parts.append(f"triager_s={round(triager_ms / 1000)}")
    return " · ".join(parts)


def strip_model_emitted_footer(text: str) -> str:
    """Remove footer-shaped lines that the model emitted on its own.

    Some providers occasionally inline an ``intent=… · tier=… · conf=…`` line into
    their reply (a leak from the conversation history showing past structured
    footers). Strip those before the gateway appends the canonical footer, so the
    user never sees a duplicate or corrupted variant.

    Args:
        text (str): Outbound assistant body straight from the LLM.

    Returns:
        str: ``text`` with any model-emitted footer lines removed.

    Examples:
        >>> strip_model_emitted_footer("hello\\n\\n_intent=X · er=B · conf=0.95_")
        'hello'
        >>> strip_model_emitted_footer(
        ...     "hi\\n\\n_intent=GREETING · tier=A · conf=1.00 · triager_s=0_"
        ... )
        'hi'
        >>> strip_model_emitted_footer("just hello")
        'just hello'
    """
    if "intent" not in text.lower() or "conf" not in text.lower():
        return text
    cleaned = _MODEL_EMITTED_FOOTER_RE.sub("", text)
    return cleaned.rstrip()


def append_routing_footer(
    text: str,
    triage: TriageResult,
    *,
    triager_ms: int | None = None,
    subagent_id: str | None = None,
) -> str:
    """Append routing footer to assistant-visible text.

    Any model-emitted footer-shaped lines in ``text`` are stripped first so the
    user never sees duplicates or corrupted variants (``er=B`` etc. — transcript
    review item #7).

    Args:
        text (str): Outbound assistant body.
        triage (TriageResult): Triage decision for the turn.
        triager_ms (int | None): Wall-clock milliseconds spent inside
            ``triage_turn`` for this turn (Wave 4 §A2).
        subagent_id (str | None): Level-1 sub-agent short id for parallel-reply
            attribution (D7).

    Returns:
        str: ``text`` with footer appended when non-empty.

    Examples:
        >>> from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
        >>> triage = TriageResult(
        ...     intent=Intent.GREETING,
        ...     complexity=ComplexityTier.A,
        ...     first_message="Hello",
        ...     tools=[],
        ...     skills=[],
        ...     mcp_servers_required=[],
        ...     confidence=1.0,
        ...     requires_vision=False,
        ...     requires_document=False,
        ... )
        >>> "intent=GREETING" in append_routing_footer("Hello", triage)
        True
        >>> "⋮a1" in append_routing_footer("Hello", triage, subagent_id="a1")
        True
    """
    body = strip_model_emitted_footer(text).rstrip()
    footer = format_routing_footer(triage, triager_ms=triager_ms)
    tag = format_subagent_tag(subagent_id or "")
    if tag:
        footer = f"{tag} · {footer}"
    if not body:
        return footer
    return f"{body}\n\n_{footer}_"


__all__ = [
    "append_routing_footer",
    "format_routing_footer",
    "format_subagent_tag",
    "strip_model_emitted_footer",
    "telegram_show_routing_enabled",
]
