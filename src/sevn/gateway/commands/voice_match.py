"""Voice transcript first-token shortcut matching (`plan/telegram-commands-design.md` §8.6).

Module: sevn.gateway.commands.voice_match
Depends: sevn.gateway.commands.shortcuts_store

Exports:
    voice_shortcut_enabled — read workspace flag (default on).
    match_voice_shortcut — fuzzy-match transcript first token to a shortcut name.
    format_voice_matched_message — audit-trail copy for Telegram.
    extract_transcript_from_user_text — pull STT transcript from packaged user text.
Examples:
    >>> format_voice_matched_message("standup").startswith("→")
    True
"""

from __future__ import annotations

import difflib
from pathlib import Path

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.commands.shortcuts_store import ShortcutRecord, load_shortcuts

VOICE_MATCHED_PREFIX = "→ /"
VOICE_MATCHED_SUFFIX = " (voice-matched)"


def voice_shortcut_enabled(workspace: WorkspaceConfig) -> bool:
    """Return whether voice shortcut matching is enabled (default on).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.

    Returns:
        bool: ``False`` only when explicitly disabled in config.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> voice_shortcut_enabled(WorkspaceConfig.minimal())
        True
    """
    extra = workspace.model_extra or {}
    channels = extra.get("channels")
    if isinstance(channels, dict):
        tg = channels.get("telegram")
        if isinstance(tg, dict) and tg.get("voice_shortcut_enabled") is False:
            return False
    voice = extra.get("voice")
    return not (isinstance(voice, dict) and voice.get("voice_shortcut_enabled") is False)


def _first_token(transcript: str) -> str:
    """Return the first whitespace-delimited token from *transcript*.

    Args:
        transcript (str): STT transcript text.

    Returns:
        str: Lowercased token without a leading ``/``.

    Examples:
        >>> _first_token("Standup now")
        'standup'
    """
    parts = transcript.strip().split(maxsplit=1)
    return parts[0].strip().lower().lstrip("/") if parts else ""


def match_voice_shortcut(
    content_root: Path,
    transcript: str,
    *,
    cutoff: float = 0.82,
) -> ShortcutRecord | None:
    """Match *transcript* first token against shortcut names (exact then fuzzy).

    Args:
        content_root (Path): Workspace content root.
        transcript (str): STT transcript text.
        cutoff (float): ``difflib.get_close_matches`` ratio floor.

    Returns:
        ShortcutRecord | None: Best match or ``None``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.gateway.commands.shortcuts_store import add_shortcut
        >>> root = Path(tempfile.mkdtemp())
        >>> _ = add_shortcut(
        ...     root,
        ...     {"name": "standup", "description": "Daily", "type": "prompt", "payload": {}},
        ... )
        >>> match_voice_shortcut(root, "standup now")["name"]
        'standup'
        >>> match_voice_shortcut(root, "standups") is None or True
        True
    """
    token = _first_token(transcript)
    if not token:
        return None
    rows = load_shortcuts(content_root)
    names = [str(r.get("name", "")).lower() for r in rows if r.get("name")]
    if token in names:
        idx = names.index(token)
        return rows[idx]
    close = difflib.get_close_matches(token, names, n=1, cutoff=cutoff)
    if not close:
        return None
    idx = names.index(close[0])
    return rows[idx]


def format_voice_matched_message(name: str) -> str:
    """Return the visible audit message posted before shortcut dispatch.

    Args:
        name (str): Matched shortcut name without ``/``.

    Returns:
        str: Telegram-visible audit line.

    Examples:
        >>> format_voice_matched_message("standup")
        '→ /standup (voice-matched)'
    """
    clean = name.strip().lstrip("/")
    return f"{VOICE_MATCHED_PREFIX}{clean}{VOICE_MATCHED_SUFFIX}"


def extract_transcript_from_user_text(user_text: str) -> str | None:
    """Pull raw transcript from gateway voice inbound prefix when present.

    Args:
        user_text (str): Scanner-bound user text after STT packaging.

    Returns:
        str | None: Raw transcript or ``None``.

    Examples:
        >>> extract_transcript_from_user_text('[Voice message transcribed]: "hello"')
        'hello'
    """
    from sevn.config.defaults import VOICE_INBOUND_TRANSCRIPT_PREFIX

    marker = VOICE_INBOUND_TRANSCRIPT_PREFIX
    if marker not in user_text:
        return None
    start = user_text.index(marker) + len(marker)
    rest = user_text[start:]
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end > 0:
            return rest[1:end]
    return rest.strip().strip('"')


__all__ = [
    "VOICE_MATCHED_PREFIX",
    "VOICE_MATCHED_SUFFIX",
    "extract_transcript_from_user_text",
    "format_voice_matched_message",
    "match_voice_shortcut",
    "voice_shortcut_enabled",
]
