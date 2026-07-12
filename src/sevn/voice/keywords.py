"""Voice trigger keyword matching (`specs/20-voice.md` §4.1, §11).

Module: sevn.voice.keywords
Depends: re

Exports:
    user_text_matches_voice_trigger — Unicode word-boundary match for ``when_asked``.
    compile_voice_trigger_patterns — pre-compiled regex helpers for tests.
"""

from __future__ import annotations

import re


def _is_word_char(ch: str) -> bool:
    """Return whether ``ch`` continues a token (letters/digits in any script).

    Args:
        ch (str): Single character.

    Returns:
        bool: ``True`` when the character is alphanumeric or underscore.

    Examples:
        >>> _is_word_char("a")
        True
        >>> _is_word_char(" ")
        False
        >>> _is_word_char("你")
        True
    """

    return ch.isalnum() or ch == "_"


def user_text_matches_voice_trigger(*, user_text: str, keywords: tuple[str, ...]) -> bool:
    """Return whether case-folded ``user_text`` contains any keyword at a word boundary.

    Multi-word phrases (e.g. ``read aloud``) match as a whole unit with boundaries only
    at the phrase edges. Uses Unicode ``str.isalnum`` (not ASCII ``\\b``) so CJK and
    Latin scripts share one deterministic rule (`specs/20-voice.md` §11).

    Args:
        user_text (str): Latest user-visible text for the session turn.
        keywords (tuple[str, ...]): Workspace ``voice_trigger_keywords`` (may be empty).

    Returns:
        bool: ``True`` when any non-empty keyword matches.

    Examples:
        >>> user_text_matches_voice_trigger(user_text="please SPEAK now", keywords=("speak",))
        True
        >>> user_text_matches_voice_trigger(user_text="speakers only", keywords=("speak",))
        False
        >>> user_text_matches_voice_trigger(user_text="nothing", keywords=("speak",))
        False
    """

    hay = (user_text or "").casefold()
    if not hay:
        return False
    for raw in keywords:
        kw = raw.strip().casefold()
        if not kw:
            continue
        start = 0
        while True:
            idx = hay.find(kw, start)
            if idx < 0:
                break
            before_ok = idx == 0 or not _is_word_char(hay[idx - 1])
            after_idx = idx + len(kw)
            after_ok = after_idx >= len(hay) or not _is_word_char(hay[after_idx])
            if before_ok and after_ok:
                return True
            start = idx + 1
    return False


def compile_voice_trigger_patterns(keywords: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    """Pre-compile regex patterns mirroring :func:`user_text_matches_voice_trigger` logic.

    Exposed for tests/documentation; runtime gating uses the scanner above.

    Args:
        keywords (tuple[str, ...]): Workspace trigger phrases.

    Returns:
        tuple[re.Pattern[str], ...]: One pattern per non-empty keyword.

    Examples:
        >>> pats = compile_voice_trigger_patterns(("speak",))
        >>> len(pats) == 1
        True
        >>> pats[0].search("please speak now") is not None
        True
    """

    patterns: list[re.Pattern[str]] = []
    for raw in keywords:
        kw = raw.strip()
        if not kw:
            continue
        escaped = re.escape(kw)
        patterns.append(re.compile(escaped, re.IGNORECASE))
    return tuple(patterns)
