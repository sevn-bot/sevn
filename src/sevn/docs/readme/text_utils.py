"""Sentence and path formatting helpers for README prose emission.

Module: sevn.docs.readme.text_utils
Depends: re

Exports:
    format_path_list — comma-separated backtick path list for prose.
    truncate_at_sentence — truncate prose at a sentence boundary within a limit.
    first_sentence — first sentence from prose text.
    role_from_summary — manifest summary first-sentence role line.

Examples:
    >>> from sevn.docs.readme.text_utils import format_path_list
    >>> format_path_list(["a.py", "b.py"])
    '`a.py`, `b.py`'
"""

from __future__ import annotations

import re

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s")
_ABBREV_BEFORE_PERIOD = frozenset(
    {
        "incl",
        "eg",
        "ie",
        "etc",
        "vs",
        "mr",
        "mrs",
        "dr",
        "sr",
        "jr",
        "st",
        "fig",
        "dept",
        "approx",
        "min",
        "max",
        "ext",
        "vol",
        "ref",
        "al",
    }
)


def first_sentence(text: str) -> str:
    """Return the first complete sentence from prose text.

    Args:
        text (str): Source prose.

    Returns:
        str: First sentence ending in ``.``, ``!``, or ``?``; empty when none.

    Examples:
        >>> first_sentence("Hello world. More text.")
        'Hello world.'
    """
    stripped = text.strip()
    for match in _SENTENCE_BOUNDARY.finditer(stripped):
        if not _is_sentence_boundary(stripped, match.start()):
            continue
        candidate = stripped[: match.start() + 1].strip()
        if candidate and candidate[-1] in ".!?":
            return candidate
    return ""


def truncate_at_sentence(text: str, limit: int) -> str:
    """Return the longest leading sentence fragment that fits within ``limit``.

    Args:
        text (str): Source prose.
        limit (int): Maximum character length for the returned fragment.

    Returns:
        str: Sentence ending in ``.``, ``!``, or ``?``; empty when none fits.

    Examples:
        >>> truncate_at_sentence("Hello world. More text.", 15)
        'Hello world.'
        >>> truncate_at_sentence("No sentence boundary at all", 12)
        ''
    """
    if limit <= 0 or not text.strip():
        return ""
    stripped = text.strip()
    if len(stripped) <= limit and stripped[-1] in ".!?":
        return stripped
    best = ""
    for match in _SENTENCE_BOUNDARY.finditer(stripped):
        end = match.start() + 1
        if end > limit:
            break
        if not _is_sentence_boundary(stripped, match.start()):
            continue
        candidate = stripped[:end].strip()
        if candidate and candidate[-1] in ".!?":
            best = candidate
    return best


def _is_sentence_boundary(text: str, space_pos: int) -> bool:
    """Return True when ``space_pos`` ends a real sentence (not an abbreviation).

    Args:
        text (str): Full prose string.
        space_pos (int): Index of the whitespace after sentence punctuation.

    Returns:
        bool: True when the boundary is a sentence end.

    Examples:
        >>> _is_sentence_boundary("Items (incl. foo) and more. Extra", 24)
        False
    """
    if space_pos < 1 or text[space_pos - 1] not in ".!?":
        return False
    punct_pos = space_pos - 1
    word_start = punct_pos
    while word_start > 0 and (text[word_start - 1].isalnum() or text[word_start - 1] == "."):
        word_start -= 1
    word = text[word_start:punct_pos].lower().rstrip(".")
    return word not in _ABBREV_BEFORE_PERIOD


def format_path_list(paths: list[str], *, max_items: int = 4) -> str:
    """Format path list for inline prose.

    Args:
        paths (list[str]): Repo-relative paths.
        max_items (int): Maximum paths to quote before summarizing the remainder.

    Returns:
        str: Comma-separated backtick paths with a true remainder count.

    Examples:
        >>> format_path_list(["a.py", "b.py"])
        '`a.py`, `b.py`'
        >>> format_path_list([f"m{i}.py" for i in range(114)], max_items=4)
        '`m0.py`, `m1.py`, `m2.py`, `m3.py`, and 110 more'
    """
    if not paths:
        return "(see source tree)"
    quoted = [f"`{p}`" for p in paths[:max_items]]
    remainder = len(paths) - max_items
    if remainder > 0:
        return ", ".join(quoted) + f", and {remainder} more"
    return ", ".join(quoted)


def role_from_summary(summary: str) -> str:
    """Use the first sentence of the manifest summary as the role line.

    Args:
        summary (str): Manifest summary text.

    Returns:
        str: Role line for the title suffix.

    Examples:
        >>> role_from_summary("FastAPI control plane. More detail.")
        'FastAPI control plane'
    """
    first = summary.split(".", maxsplit=1)[0].strip()
    return first or summary
