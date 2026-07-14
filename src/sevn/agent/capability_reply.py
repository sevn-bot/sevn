"""Deterministic registry listings for capability questions (live-session).

Bypasses tier-B LLM for bare ``list your skills`` / ``list your tools`` asks so the
operator always gets the live registry snapshot instead of an opener-only stall.

Module: sevn.agent.capability_reply
Depends: re, sevn.tools.base, sevn.tools.meta_loaders

Exports:
    is_list_skills_message — bare skill-inventory ask detector.
    is_list_tools_message — bare tool-inventory ask detector.
    compose_list_skills_reply — markdown skill catalog from registry rows.
    compose_list_tools_reply — markdown tool catalog from enabled native tools.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from sevn.tools.meta_loaders import META_TOOL_NAMES

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sevn.tools.base import ToolDefinition

_LIST_SKILLS_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\s*list\s+(your\s+)?skills\b[?.!]*\s*$", re.I),
    re.compile(r"^\s*what\s+skills\s*(do\s+you\s+have)?\b[?.!]*\s*$", re.I),
    re.compile(r"^\s*which\s+skills\s*(do\s+you\s+have)?\b[?.!]*\s*$", re.I),
    re.compile(r"^\s*show\s+(your\s+)?skills\b[?.!]*\s*$", re.I),
)

_LIST_TOOLS_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\s*list\s+(your\s+)?tools\b[?.!]*\s*$", re.I),
    re.compile(r"^\s*what\s+tools\s*(do\s+you\s+have)?\b[?.!]*\s*$", re.I),
    re.compile(r"^\s*which\s+tools\s*(do\s+you\s+have)?\b[?.!]*\s*$", re.I),
    re.compile(r"^\s*show\s+(your\s+)?tools\b[?.!]*\s*$", re.I),
)


def is_list_skills_message(message: str) -> bool:
    """Return True for bare skill-inventory questions.

    Args:
        message (str): Operator message text.

    Returns:
        bool: True when the message is only asking for the skill catalog.

    Examples:
        >>> is_list_skills_message("list your skills")
        True
        >>> is_list_skills_message("what skills do you have?")
        True
        >>> is_list_skills_message("list skills in the repo")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _LIST_SKILLS_PATTERNS)


def is_list_tools_message(message: str) -> bool:
    """Return True for bare tool-inventory questions.

    Args:
        message (str): Operator message text.

    Returns:
        bool: True when the message is only asking for the tool catalog.

    Examples:
        >>> is_list_tools_message("list your tools")
        True
        >>> is_list_tools_message("what tools do you have?")
        True
        >>> is_list_tools_message("list tools for pdf")
        False
    """
    text = message.strip()
    if not text:
        return False
    return any(p.search(text) for p in _LIST_TOOLS_PATTERNS)


def compose_list_skills_reply(
    skill_descriptions: Mapping[str, str],
    *,
    skill_inventory: Mapping[str, Mapping[str, object]] | None = None,
) -> str:
    """Build a markdown skill catalog from registry summaries.

    Args:
        skill_descriptions (Mapping[str, str]): Skill id → one-line summary.
        skill_inventory (Mapping[str, Mapping[str, object]] | None): Optional
            per-skill script/runnable rows from ``ToolSet.skill_inventory``.

    Returns:
        str: Operator-facing markdown list.

    Examples:
        >>> body = compose_list_skills_reply({"pdf": "Render PDFs", "lcm": "Session recall"})
        >>> "pdf" in body and "2 skills" in body
        True
    """
    if not skill_descriptions:
        return "No skills are registered in this workspace session."
    lines = [f"**{len(skill_descriptions)} skills** available:"]
    inventory = skill_inventory or {}
    for name in sorted(skill_descriptions):
        desc = skill_descriptions[name].strip().replace("\n", " ")
        suffix = ""
        row = inventory.get(name)
        if isinstance(row, Mapping):
            # Prefer the inventory ``summary`` (full manifest description) over
            # ``skill_descriptions``, whose rows are the Triager routing index
            # lines clipped to ~80 chars (``SkillsIndex._clip``). The operator
            # asked for the catalog, so surface the untruncated text here.
            full = row.get("summary")
            if isinstance(full, str) and full.strip():
                desc = full.strip().replace("\n", " ")
            scripts = row.get("scripts", [])
            runnables = row.get("runnables", [])
            script_n = len(scripts) if isinstance(scripts, list) else 0
            runnable_n = len(runnables) if isinstance(runnables, list) else 0
            parts: list[str] = []
            if script_n:
                parts.append(f"{script_n} script{'s' if script_n != 1 else ''}")
            if runnable_n:
                parts.append(f"{runnable_n} runnable{'s' if runnable_n != 1 else ''}")
            if parts:
                suffix = f" ({', '.join(parts)})"
        lines.append(f"- **{name}**{suffix} — {desc}")
    lines.append("\nUse `load_skill` then `run_skill_script` / `run_skill_runnable` to run one.")
    return "\n".join(lines)


def compose_list_tools_reply(definitions: Sequence[ToolDefinition]) -> str:
    """Build a markdown tool catalog from enabled native registry tools.

    Meta tools (``load_tool``, ``list_registry``, …) are omitted to mirror
    ``list_registry`` output.

    Args:
        definitions (Sequence[ToolDefinition]): Native tool rows from ``ToolSet.native``.

    Returns:
        str: Operator-facing markdown list.

    Examples:
        >>> from sevn.tools.base import ToolDefinition
        >>> body = compose_list_tools_reply(
        ...     [
        ...         ToolDefinition(
        ...             name="read",
        ...             category="file",
        ...             description="Read a file",
        ...             parameters={},
        ...         ),
        ...     ],
        ... )
        >>> "read" in body and "1 tools" in body
        True
    """
    rows = sorted(
        (d.name, d.description.strip().replace("\n", " "))
        for d in definitions
        if d.enabled and d.name not in META_TOOL_NAMES
    )
    if not rows:
        return "No tools are registered in this workspace session."
    lines = [f"**{len(rows)} tools** available:"]
    lines.extend(f"- **{name}** — {desc}" for name, desc in rows)
    lines.append("\nUse `load_tool` before calling a tool not already in this turn's list.")
    return "\n".join(lines)


__all__ = [
    "compose_list_skills_reply",
    "compose_list_tools_reply",
    "is_list_skills_message",
    "is_list_tools_message",
]
