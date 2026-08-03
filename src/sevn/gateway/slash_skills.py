"""Stacked slash-skill parsing and turn overlay (``#87``, W16).

Module: sevn.gateway.slash_skills
Depends: dataclasses, sevn.gateway.commands.shortcuts_store, sevn.skills.manager

Exports:
    StackedSlashSkillParseResult — parser output for one inbound line.
    SlashSkillInboundPreprocessResult — inbound preprocessor outcome.
    build_slash_skill_turn_overlay — ordered loaded-skill metadata for a turn.
    format_slash_skill_errors — user-visible error text from parser failures.
    known_skill_ids_from_manager — non-quarantined skill ids from inventory.
    merge_slash_skills_into_triage — combine slash-bound and triager skill picks.
    parse_stacked_slash_skills — parse leading ``/skill`` tokens deterministically.
    preprocess_stacked_slash_skills_inbound — attach slash overlay before triage dispatch.
    resolve_skill_shortcut_slash — map a ``/shortcut`` to a skill shortcut row.
    skill_shortcut_slash_text — build slash-skill text from a shortcut record.
Examples:
    >>> from sevn.gateway.slash_skills import parse_stacked_slash_skills
    >>> r = parse_stacked_slash_skills("/research hi", known_skill_ids=frozenset({"research"}))
    >>> r.skill_ids
    ('research',)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sevn.gateway.commands.shortcuts_store import CORE_COMMAND_NAMES, ShortcutRecord, find_shortcut

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.skills.manager import SkillsManager

SLASH_SKILL_OVERLAY_META_KEY = "slash_skill_overlay"

RESERVED_SLASH_SKILL_COMMANDS: frozenset[str] = frozenset(
    {
        *CORE_COMMAND_NAMES,
        "agents",
        "platform",
        "logs",
        "traces",
        "diagnose",
        "file-issue",
        "evolution",
        "improve",
        "self-improve",
    },
)


@dataclass(frozen=True, slots=True)
class StackedSlashSkillParseResult:
    """Outcome of :func:`parse_stacked_slash_skills` for one inbound line."""

    skill_ids: tuple[str, ...]
    remainder: str
    errors: tuple[str, ...]
    deferred_to_core_handler: bool = False
    conflict_resolution: str | None = None
    effective_skill_id: str | None = None


def known_skill_ids_from_manager(manager: SkillsManager) -> frozenset[str]:
    """Return loadable skill ids from a :class:`~sevn.skills.manager.SkillsManager`.

    Args:
        manager (SkillsManager): Reloaded skills registry for the workspace.

    Returns:
        frozenset[str]: Advertised (non-quarantined) skill ids.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.skills.manager import SkillsManager
        >>> isinstance(known_skill_ids_from_manager(SkillsManager.shared(Path("/tmp"))), frozenset)
        True
    """
    return frozenset(manager.advertised_skill_descriptions())


def _slash_token_body(token: str) -> str:
    """Return slash token name without leading ``/`` or Telegram ``@bot`` suffix.

    Args:
        token (str): One inbound slash token (e.g. ``/config@MyBot``).

    Returns:
        str: Command or skill name body.

    Examples:
        >>> _slash_token_body("/config@alexstestee_bot")
        'config'
        >>> _slash_token_body("/research")
        'research'
    """
    raw = token.lstrip("/").strip()
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    return raw


def _resolve_known_skill(token: str, known_skill_ids: frozenset[str]) -> str | None:
    """Match one slash token to a canonical skill id (case-insensitive).

    Args:
        token (str): One inbound slash token (e.g. ``/Research``).
        known_skill_ids (frozenset[str]): Valid skill inventory ids.

    Returns:
        str | None: Canonical skill id, or ``None`` when unknown.

    Examples:
        >>> _resolve_known_skill("/research", frozenset({"research"}))
        'research'
        >>> _resolve_known_skill("/nope", frozenset({"research"})) is None
        True
    """
    raw = _slash_token_body(token)
    if not raw:
        return None
    if raw in known_skill_ids:
        return raw
    lower = raw.lower()
    for skill_id in known_skill_ids:
        if skill_id.lower() == lower:
            return skill_id
    return None


def parse_stacked_slash_skills(
    text: str,
    *,
    known_skill_ids: frozenset[str],
    reserved_commands: frozenset[str] | None = None,
) -> StackedSlashSkillParseResult:
    """Parse zero or more leading slash-skill tokens from inbound text.

    Core slash commands (``/help``, ``/new``, …) defer to the existing handler
    chain — they are never treated as skill ids even when present in
    ``known_skill_ids``. Unknown slash tokens produce explicit errors and do
    not fall through as prose. When multiple skills are stacked, metadata
    conflicts resolve with **later token wins** (``effective_skill_id``).

    Args:
        text (str): Raw inbound user text.
        known_skill_ids (frozenset[str]): Valid skill inventory ids.
        reserved_commands (frozenset[str] | None): Override reserved slash names.

    Returns:
        StackedSlashSkillParseResult: Parsed skill chain, remainder, and errors.

    Examples:
        >>> r = parse_stacked_slash_skills(
        ...     "/research /writing go",
        ...     known_skill_ids=frozenset({"research", "writing"}),
        ... )
        >>> r.skill_ids
        ('research', 'writing')
        >>> r.remainder
        'go'
    """
    reserved = reserved_commands if reserved_commands is not None else RESERVED_SLASH_SKILL_COMMANDS
    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return StackedSlashSkillParseResult((), stripped, ())

    tokens = stripped.split()
    skill_ids: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("/"):
            break
        slash_body = _slash_token_body(token)
        if "/" not in slash_body and slash_body.lower() in reserved:
            if skill_ids:
                # Core handler already declined (first token was a skill). Emitting
                # an explicit error avoids silently dropping the skill chain into prose.
                return StackedSlashSkillParseResult(
                    (),
                    "",
                    (f"core command `/{slash_body}` cannot follow slash skills",),
                )
            return StackedSlashSkillParseResult(
                (),
                stripped,
                (),
                deferred_to_core_handler=True,
            )
        resolved = _resolve_known_skill(token, known_skill_ids)
        if resolved is None:
            unknown = _slash_token_body(token)
            return StackedSlashSkillParseResult(
                (),
                "",
                (f"unknown slash skill `{unknown}`",),
            )
        skill_ids.append(resolved)
        index += 1

    remainder = " ".join(tokens[index:]).strip()
    conflict_resolution: str | None = None
    effective_skill_id: str | None = None
    if len(skill_ids) > 1:
        conflict_resolution = "later_wins"
        effective_skill_id = skill_ids[-1]
    elif len(skill_ids) == 1:
        effective_skill_id = skill_ids[0]

    return StackedSlashSkillParseResult(
        tuple(skill_ids),
        remainder,
        (),
        conflict_resolution=conflict_resolution,
        effective_skill_id=effective_skill_id,
    )


def build_slash_skill_turn_overlay(
    *,
    skill_ids: tuple[str, ...],
    remainder: str,
    conflict_resolution: str | None = None,
    effective_skill_id: str | None = None,
) -> dict[str, Any]:
    """Build turn metadata describing slash-loaded skills in order.

    Args:
        skill_ids (tuple[str, ...]): Parsed skill chain (load order).
        remainder (str): User prompt after the slash prefix.
        conflict_resolution (str | None): Conflict rule when stacked.
        effective_skill_id (str | None): Winning skill id for conflicts.

    Returns:
        dict[str, Any]: Overlay stored on the inbound user message metadata.

    Examples:
        >>> overlay = build_slash_skill_turn_overlay(
        ...     skill_ids=("a", "b"),
        ...     remainder="go",
        ...     conflict_resolution="later_wins",
        ...     effective_skill_id="b",
        ... )
        >>> [row["skill_id"] for row in overlay["loaded_skills"]]
        ['a', 'b']
    """
    resolution = conflict_resolution
    effective = effective_skill_id
    if len(skill_ids) > 1 and resolution is None:
        resolution = "later_wins"
        effective = skill_ids[-1]
    elif len(skill_ids) == 1 and effective is None:
        effective = skill_ids[0]

    return {
        "loaded_skills": [
            {"skill_id": skill_id, "order": order} for order, skill_id in enumerate(skill_ids)
        ],
        "user_prompt": remainder,
        "conflict_resolution": resolution,
        "effective_skill_id": effective,
    }


def format_slash_skill_errors(errors: tuple[str, ...]) -> str:
    """Format parser errors for a user-visible gateway reply.

    Args:
        errors (tuple[str, ...]): Parser error strings.

    Returns:
        str: Single message suitable for outbound chat.

    Examples:
        >>> format_slash_skill_errors(("unknown slash skill `x`",))
        'unknown slash skill `x`'
    """
    if not errors:
        return "Unknown slash skill."
    return "\n".join(errors)


def resolve_skill_shortcut_slash(
    text: str,
    content_root: Path,
) -> ShortcutRecord | None:
    """Return a shortcut row when *text* is a ``type: skill`` slash shortcut.

    Args:
        text (str): Inbound slash text (e.g. ``/standup`` or ``/standup args``).
        content_root (Path): Workspace content root for ``shortcuts.json``.

    Returns:
        ShortcutRecord | None: Matching skill shortcut, or ``None``.

    Examples:
        >>> resolve_skill_shortcut_slash("/help", __import__("pathlib").Path("/tmp")) is None
        True
    """
    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return None
    command = stripped.split(maxsplit=1)[0].lower()
    name = command.lstrip("/")
    row = find_shortcut(content_root, name)
    if row is None:
        return None
    if str(row.get("type", "")).strip().lower() != "skill":
        return None
    return row


def skill_shortcut_slash_text(row: ShortcutRecord, *, trailing_args: str = "") -> str:
    """Build slash-skill invocation text from a skill shortcut row.

    Args:
        row (ShortcutRecord): Shortcut with ``type: skill``.
        trailing_args (str): Extra args after the shortcut name on the slash line.

    Returns:
        str: Text suitable for :func:`parse_stacked_slash_skills`.

    Examples:
        >>> skill_shortcut_slash_text(
        ...     {"name": "go", "type": "skill", "payload": {"skill_id": "research"}},
        ... )
        '/research'
    """
    payload = row.get("payload")
    payload_dict = payload if isinstance(payload, dict) else {}
    skill_id = str(
        payload_dict.get("skill_id") or payload_dict.get("target") or row.get("name") or ""
    ).strip()
    template = str(
        payload_dict.get("template") or payload_dict.get("text") or payload_dict.get("prompt") or ""
    ).strip()
    remainder = trailing_args.strip() or template
    base = f"/{skill_id}"
    return f"{base} {remainder}".strip() if remainder else base


def merge_slash_skills_into_triage(
    triage_skills: list[str],
    overlay: dict[str, Any],
) -> list[str]:
    """Merge slash-loaded skills into triager skill picks preserving order.

    Slash-bound ids precede triager picks; duplicates are dropped case-insensitively
    while keeping the first canonical spelling from the slash chain.

    Args:
        triage_skills (list[str]): Skills from triager output.
        overlay (dict[str, Any]): Overlay from :func:`build_slash_skill_turn_overlay`.

    Returns:
        list[str]: Combined skill id list.

    Examples:
        >>> merge_slash_skills_into_triage(
        ...     ["extra"],
        ...     {"loaded_skills": [{"skill_id": "research", "order": 0}]},
        ... )
        ['research', 'extra']
    """
    loaded = overlay.get("loaded_skills")
    slash_ids: list[str] = []
    if isinstance(loaded, list):
        for row in loaded:
            if isinstance(row, dict):
                skill_id = str(row.get("skill_id") or "").strip()
                if skill_id:
                    slash_ids.append(skill_id)
    seen = {skill_id.lower() for skill_id in slash_ids}
    merged = list(slash_ids)
    for skill_id in triage_skills:
        token = str(skill_id or "").strip()
        if not token:
            continue
        if token.lower() in seen:
            continue
        seen.add(token.lower())
        merged.append(token)
    effective = str(overlay.get("effective_skill_id") or "").strip()
    if overlay.get("conflict_resolution") == "later_wins" and effective:
        merged = [sid for sid in merged if sid.lower() != effective.lower()]
        merged.append(effective)
    return merged


@dataclass(frozen=True, slots=True)
class SlashSkillInboundPreprocessResult:
    """Outcome of :func:`preprocess_stacked_slash_skills_inbound`."""

    msg: Any
    reply_text: str | None = None


def preprocess_stacked_slash_skills_inbound(
    msg: Any,
    *,
    slash_text: str,
    content_root: Path,
    workspace: Any | None,
    layout: Any | None,
) -> SlashSkillInboundPreprocessResult:
    """Parse stacked slash skills and attach turn overlay before triage dispatch.

    Args:
        msg (Any): Inbound :class:`~sevn.gateway.channel_router.IncomingMessage`.
        slash_text (str): Normalised inbound text (may include skill shortcut rewrite).
        content_root (Path): Workspace content root.
        workspace (Any | None): Parsed workspace config for :class:`~sevn.skills.manager.SkillsManager`.
        layout (Any | None): Workspace layout (unused; retained for call-site parity).

    Returns:
        SlashSkillInboundPreprocessResult: Possibly rewritten ``msg`` or parser error text.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.gateway.channel_router import IncomingMessage
        >>> m = IncomingMessage(channel="telegram", user_id="1", text="/nope")
        >>> isinstance(
        ...     preprocess_stacked_slash_skills_inbound(
        ...         m,
        ...         slash_text="/nope",
        ...         content_root=Path("/tmp"),
        ...         workspace=None,
        ...         layout=None,
        ...     ),
        ...     SlashSkillInboundPreprocessResult,
        ... )
        True
    """
    from sevn.gateway.channel_router import IncomingMessage
    from sevn.skills.manager import SkillsManager

    _ = layout
    if not slash_text.startswith("/"):
        return SlashSkillInboundPreprocessResult(msg=msg)

    manager = SkillsManager.shared(
        content_root,
        layout=layout,
        config=workspace,
    )
    parsed = parse_stacked_slash_skills(
        slash_text,
        known_skill_ids=known_skill_ids_from_manager(manager),
    )
    if parsed.errors:
        return SlashSkillInboundPreprocessResult(
            msg=msg,
            reply_text=format_slash_skill_errors(parsed.errors),
        )
    if not parsed.skill_ids:
        return SlashSkillInboundPreprocessResult(msg=msg)

    overlay = build_slash_skill_turn_overlay(
        skill_ids=parsed.skill_ids,
        remainder=parsed.remainder,
        conflict_resolution=parsed.conflict_resolution,
        effective_skill_id=parsed.effective_skill_id,
    )
    md = dict(msg.metadata) if isinstance(msg.metadata, dict) else {}
    md[SLASH_SKILL_OVERLAY_META_KEY] = overlay
    rewritten = IncomingMessage(
        channel=msg.channel,
        user_id=msg.user_id,
        text=parsed.remainder,
        metadata=md,
        raw=msg.raw,
        attachments=list(msg.attachments),
    )
    return SlashSkillInboundPreprocessResult(msg=rewritten)


__all__ = [
    "RESERVED_SLASH_SKILL_COMMANDS",
    "SLASH_SKILL_OVERLAY_META_KEY",
    "SlashSkillInboundPreprocessResult",
    "StackedSlashSkillParseResult",
    "build_slash_skill_turn_overlay",
    "format_slash_skill_errors",
    "known_skill_ids_from_manager",
    "merge_slash_skills_into_triage",
    "parse_stacked_slash_skills",
    "preprocess_stacked_slash_skills_inbound",
    "resolve_skill_shortcut_slash",
    "skill_shortcut_slash_text",
]
