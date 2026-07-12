"""Deterministic USER.md fallback after bootstrap tier-B (`plan/operator-experience-wave-plan.md` Wave 3).

Module: sevn.gateway.bootstrap_capture
Depends: pathlib, re, sevn.gateway.first_session, sevn.tools.workspace_files

Exports:
    extract_bootstrap_name — parse a display name from operator intro text.
    try_bootstrap_user_md_fallback — patch ``USER.md`` when bootstrap is incomplete.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from sevn.gateway.first_session import _is_user_md_placeholder_value
from sevn.tools.workspace_files import write_workspace_md

_NAME_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)\bmy name is\s+([A-Za-z][A-Za-z0-9 _.-]{0,40})"),
    re.compile(r"(?i)\bi['']?m\s+([A-Za-z][A-Za-z0-9 _.-]{0,40})"),
    re.compile(r"(?i)\bname['']?s\s+([A-Za-z][A-Za-z0-9 _.-]{0,40})"),
    re.compile(r"(?i)\bcall me\s+([A-Za-z][A-Za-z0-9 _.-]{0,40})"),
)
_NUMBERED_ANSWER: Final[re.Pattern[str]] = re.compile(
    r"^\s*(\d+)\.\s*(.+)$",
    re.MULTILINE,
)
# Single-token name: must start with a letter, ≤ 24 chars total, no spaces (single token).
_SIMPLE_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,23}$")

# Stopwords / pronouns that are not names even when they are single tokens.
_NAME_STOPWORDS: Final[frozenset[str]] = frozenset(
    {"i", "my", "the", "im", "name", "hi", "hey", "a", "an", "it", "me"}
)

# Label-anchored extraction: recognise "label: value" inside a numbered line.
# Keys are lowercased labels; values are the USER.md field names.
_INLINE_LABEL_MAP: Final[dict[str, str]] = {
    "name": "Name",
    "role": "Role",
    "timezone": "Timezone",
    "tz": "Timezone",
    "style": "Style",
    "language": "Language",
    "lang": "Language",
    "preferences": "Preferences",
    "prefs": "Preferences",
}
_INLINE_LABEL_RE: Final[re.Pattern[str]] = re.compile(r"(?i)^([a-z]+)\s*:\s*(.+)$")

# Timezone heuristics — IANA city names and common abbreviations.
_TZ_IANA_RE: Final[re.Pattern[str]] = re.compile(
    r"\b([A-Z][a-zA-Z]+(?:/[A-Za-z][A-Za-z0-9_]+)+)\b"  # e.g. America/New_York, Europe/Amsterdam
)
_TZ_ABBREV_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(UTC|GMT|CET|CEST|EST|EDT|PST|PDT|MST|MDT|CST|CDT|IST|JST|AEST|AEDT)\b"
)
# City → IANA mapping for common city hints.
_CITY_TZ: Final[dict[str, str]] = {
    "amsterdam": "Europe/Amsterdam",
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "rome": "Europe/Rome",
    "madrid": "Europe/Madrid",
    "brussels": "Europe/Brussels",
    "zurich": "Europe/Zurich",
    "new_york": "America/New_York",
    "new york": "America/New_York",
    "los_angeles": "America/Los_Angeles",
    "los angeles": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "toronto": "America/Toronto",
    "sydney": "Australia/Sydney",
    "tokyo": "Asia/Tokyo",
    "dubai": "Asia/Dubai",
    "singapore": "Asia/Singapore",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
}

# Style heuristics.
_STYLE_WORDS: Final[frozenset[str]] = frozenset(
    {"casual", "formal", "brief", "detailed", "verbose", "concise", "terse", "direct"}
)

# ISO language heuristics.
_LANGUAGE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "english",
        "spanish",
        "french",
        "german",
        "portuguese",
        "italian",
        "dutch",
        "russian",
        "chinese",
        "japanese",
        "korean",
        "arabic",
        "hindi",
        "turkish",
        "polish",
        "swedish",
        "norwegian",
        "danish",
        "finnish",
        "greek",
        "hebrew",
        "thai",
        "vietnamese",
        "indonesian",
        "malay",
        "ukrainian",
    }
)


def _first_alpha_token(value: str) -> str | None:
    """Return the first alpha-leading token from ``value``.

    Args:
        value (str): Candidate name or phrase.

    Returns:
        str | None: Trimmed token when valid, else ``None``.

    Examples:
        >>> _first_alpha_token("Alex")
        'Alex'
        >>> _first_alpha_token("123") is None
        True
    """
    text = value.strip().rstrip(".,!?")
    if not text:
        return None
    first = text.split()[0] if text else ""
    if first and first[0].isalpha():
        return first
    return None


def _parse_numbered_bootstrap_answers(user_text: str) -> dict[int, str]:
    """Parse ``1. answer`` lines from bootstrap reply text.

    Args:
        user_text (str): Latest user message in the bootstrap turn.

    Returns:
        dict[int, str]: Answer index to trimmed text.

    Examples:
        >>> _parse_numbered_bootstrap_answers("1. Alex\\n2. casual")
        {1: 'Alex', 2: 'casual'}
    """
    answers: dict[int, str] = {}
    for match in _NUMBERED_ANSWER.finditer(user_text):
        answers[int(match.group(1))] = match.group(2).strip()
    return answers


def _extract_timezone(text: str) -> str | None:
    """Return the first IANA timezone found in ``text``, or ``None``.

    Args:
        text (str): Candidate string (a numbered answer or full message).

    Returns:
        str | None: IANA timezone string or ``None``.

    Examples:
        >>> _extract_timezone("Europe/Amsterdam")
        'Europe/Amsterdam'
        >>> _extract_timezone("amsterdam")
        'Europe/Amsterdam'
        >>> _extract_timezone("CET")
        'CET'
        >>> _extract_timezone("hello") is None
        True
    """
    m = _TZ_IANA_RE.search(text)
    if m:
        return m.group(1)
    m = _TZ_ABBREV_RE.search(text)
    if m:
        return m.group(1)
    lower = text.strip().lower()
    return _CITY_TZ.get(lower)


def _parse_labeled_bootstrap_fields(user_text: str) -> dict[str, str]:
    """Extract USER.md fields from numbered lines using label anchors and heuristics.

    Labels are matched by the text of each line, never by position.  A numbered line
    like ``2. timezone: Amsterdam`` maps to ``Timezone`` via the inline label; a bare
    answer like ``2. casual`` maps to ``Style`` only when ``casual`` is in
    ``_STYLE_WORDS``.  No positional ``1→Name, 2→Role`` mapping is applied.

    Args:
        user_text (str): Latest user message in the bootstrap turn.

    Returns:
        dict[str, str]: Field label to trimmed answer text (only confident fields).

    Examples:
        >>> _parse_labeled_bootstrap_fields("2. timezone: Amsterdam")
        {'Timezone': 'Europe/Amsterdam'}
        >>> _parse_labeled_bootstrap_fields("4. casual")
        {'Style': 'casual'}
        >>> _parse_labeled_bootstrap_fields("hello random")
        {}
    """
    answers = _parse_numbered_bootstrap_answers(user_text)
    fields: dict[str, str] = {}
    for _idx, raw in answers.items():
        # 1. Check for inline label: "timezone: Amsterdam" or "style: casual"
        label_match = _INLINE_LABEL_RE.match(raw)
        if label_match:
            label_key = label_match.group(1).lower()
            label_value = label_match.group(2).strip()
            field_name = _INLINE_LABEL_MAP.get(label_key)
            if field_name and label_value:
                if field_name == "Timezone":
                    tz = _extract_timezone(label_value) or label_value
                    fields.setdefault(field_name, tz)
                else:
                    fields.setdefault(field_name, label_value)
                continue
        # 2. No inline label — try heuristics on the raw value.
        lower = raw.lower().strip()
        # Timezone heuristic
        tz = _extract_timezone(raw)
        if tz and "Timezone" not in fields:
            fields["Timezone"] = tz
            continue
        # Style heuristic
        if lower in _STYLE_WORDS and "Style" not in fields:
            fields["Style"] = raw.strip()
            continue
        # Language heuristic
        if lower in _LANGUAGE_NAMES and "Language" not in fields:
            fields["Language"] = raw.strip()
            continue
        # No confident match — skip this answer rather than guessing.
        # Role and Preferences require an inline label (e.g. "role: AI engineer").
    return fields


def _is_valid_name_token(token: str) -> bool:
    """Return True when ``token`` is a plausible single-word display name.

    Args:
        token (str): Candidate name token (already extracted from a phrase).

    Returns:
        bool: True when the token passes all name validation checks.

    Examples:
        >>> _is_valid_name_token("Alex")
        True
        >>> _is_valid_name_token("I")
        False
        >>> _is_valid_name_token("my")
        False
    """
    if not _SIMPLE_NAME.fullmatch(token):
        return False
    return token.lower() not in _NAME_STOPWORDS


def extract_bootstrap_name(user_text: str) -> str | None:
    """Return a high-confidence display name from operator intro text.

    The numbered-line branch requires the first token of answer 1 to be a SINGLE
    alpha-leading word (≤ 24 chars) that is not a pronoun or stopword.  Multi-word
    phrases like ``"I am into AI engineering"`` are rejected.

    Args:
        user_text (str): Latest user message in the bootstrap turn.

    Returns:
        str | None: Trimmed name when a pattern matches, else ``None``.

    Examples:
        >>> extract_bootstrap_name("Hi, I'm Alex and I build bots")
        'Alex'
        >>> extract_bootstrap_name("1. Alex\\n2. casual")
        'Alex'
        >>> extract_bootstrap_name("hello there") is None
        True
        >>> extract_bootstrap_name("1. I am into AI engineering\\n2. amsterdam") is None
        True
    """
    text = user_text.strip()
    if not text:
        return None
    # Numbered branch: answer 1 must be a valid single-token name.
    numbered = _parse_numbered_bootstrap_answers(text)
    first_answer = numbered.get(1, "")
    if first_answer:
        first_answer_stripped = first_answer.strip().rstrip(".,!?")
        # Reject multi-word answers immediately (they are descriptions, not names).
        if " " not in first_answer_stripped and _is_valid_name_token(first_answer_stripped):
            return first_answer_stripped
    # Natural-language patterns ("my name is …", "I'm …", etc.)
    for pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        token = _first_alpha_token(match.group(1))
        if token is not None and _is_valid_name_token(token):
            return token
    return None


def _replace_field_line(lines: list[str], field_label: str, value: str) -> bool:
    """Replace one ``- **Field:**`` bullet only when its current value is a placeholder.

    Args:
        lines (list[str]): Markdown lines to mutate in place.
        field_label (str): Label between ``**`` markers (e.g. ``Name``).
        value (str): New field value.

    Returns:
        bool: True when an existing placeholder line was replaced.  False when the
            line is absent or already holds a non-placeholder value (no write).

    Examples:
        >>> body = ["- **Name:** _(your name)_"]
        >>> _replace_field_line(body, "Name", "Alex")
        True
        >>> body
        ['- **Name:** Alex']
        >>> body2 = ["- **Name:** Alex"]
        >>> _replace_field_line(body2, "Name", "Jordan")
        False
        >>> body2
        ['- **Name:** Alex']
    """
    needle = f"**{field_label}:**"
    for idx, line in enumerate(lines):
        if needle not in line:
            continue
        # Extract the current value after the needle.
        _, _, tail = line.partition(needle)
        current_value = tail.strip()
        if not _is_user_md_placeholder_value(current_value):
            # Non-placeholder value — leave it untouched.
            return False
        lines[idx] = f"- **{field_label}:** {value}"
        return True
    return False


def _replace_preferences_line(lines: list[str], pref_value: str) -> bool:
    """Replace the placeholder bullet under ``## Preferences`` when present.

    Args:
        lines (list[str]): Markdown lines to mutate in place.
        pref_value (str): Preference text.

    Returns:
        bool: True when a placeholder line was replaced.

    Examples:
        >>> body = ["## Preferences", "- _(tools you prefer)_"]
        >>> _replace_preferences_line(body, "bullet lists")
        True
    """
    pref_heading = next(
        (i for i, line in enumerate(lines) if line.strip() == "## Preferences"),
        None,
    )
    if pref_heading is None:
        return False
    for idx in range(pref_heading + 1, len(lines)):
        line = lines[idx]
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            bullet_value = stripped[2:].strip()
            if _is_user_md_placeholder_value(bullet_value):
                lines[idx] = f"- {pref_value}"
                return True
            break
    return False


def _patch_user_md(content_root: Path, *, fields: dict[str, str]) -> str:
    """Build ``USER.md`` body with bootstrap fields replaced and marker removed.

    Args:
        content_root (Path): Workspace content root.
        fields (dict[str, str]): ``USER.md`` field labels to values.

    Returns:
        str: Patched markdown body.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_patch_user_md)
        True
    """
    path = content_root / "USER.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else "- **Name:** _(your name)_\n"
    lines: list[str] = []
    for line in text.splitlines():
        if "<!-- sevn-bootstrap:user-incomplete -->" in line:
            continue
        lines.append(line)
    for label in ("Name", "Role", "Timezone", "Style", "Language"):
        value = fields.get(label)
        if not value:
            continue
        if not _replace_field_line(lines, label, value):
            # Only append when the field is not present at all (no matching needle line).
            needle = f"**{label}:**"
            has_line = any(needle in line for line in lines)
            if not has_line:
                lines.append(f"- **{label}:** {value}")
    preferences = fields.get("Preferences")
    if preferences and not _replace_preferences_line(lines, preferences):
        pref_needle = "## Preferences"
        has_pref_section = any(line.strip() == pref_needle for line in lines)
        if not has_pref_section:
            lines.append(f"- {preferences}")
    return "\n".join(lines).strip() + "\n"


def try_bootstrap_user_md_fallback(
    content_root: Path,
    user_text: str,
    *,
    agent_name: str = "Sevn",
) -> bool:
    """Patch ``USER.md`` when bootstrap is incomplete and answers are parseable.

    Only confident, label-anchored or heuristically identified fields are written.
    Partial answers (e.g. timezone only) are applied; unrelated text produces no write.
    Non-placeholder field values are never overwritten.

    Args:
        content_root (Path): Workspace content root.
        user_text (str): Latest user message for the turn.
        agent_name (str): Bot display name for completion checks.

    Returns:
        bool: ``True`` when a write was applied.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(try_bootstrap_user_md_fallback)
        True
    """
    from sevn.gateway.first_session import user_md_bootstrap_profile_incomplete

    _ = agent_name
    if not user_md_bootstrap_profile_incomplete(content_root):
        return False
    fields = _parse_labeled_bootstrap_fields(user_text)
    name = extract_bootstrap_name(user_text)
    if name is not None:
        fields.setdefault("Name", name)
    if not fields:
        return False
    body = _patch_user_md(content_root, fields=fields)
    write_workspace_md(content_root, "USER.md", body)
    from loguru import logger

    logger.info(
        "bootstrap capture wrote USER.md fields={fields} content_root={root}",
        fields=sorted(fields),
        root=str(content_root),
    )
    return True


__all__ = [
    "extract_bootstrap_name",
    "try_bootstrap_user_md_fallback",
]
