"""Canonical opener and motion-promise phrasing for triager, grounding, harness, gateway.

Module: sevn.agent.openers
Depends: (none)

Exports:
    is_bare_opener — whether normalized text starts with a :data:`BARE_OPENERS` prefix.
    normalize_opener — collapse whitespace and lower-case for opener matching.
    strip_opener_echo — remove a leading echo of the triager opener from tier-B output.

Module-level constants: ``BARE_OPENERS`` (union of former five duplicated lists) and
``MOTION_PROMISE_MARKERS`` (P4 motion-promise phrases).
"""

from __future__ import annotations

from typing import Final

BARE_OPENERS: Final[frozenset[str]] = frozenset(
    {
        # routing_policy._FORBIDDEN_ACK_STARTERS + b_harness._OPENER_PREFIXES
        "on it",
        "let me",
        "one sec",
        "one moment",
        "got it",
        "checking",
        "sure",
        "okay",
        "ok",
        "alright",
        "here you go",
        "here's the",
        "here is the",
        "pulling",
        "re-pulling",
        "fetching",
        "looking",
        "picking it back up",
        "running the full pipeline",
        "re-rendering",
        "sending the file",
        # grounding._CANNED_OPENERS
        "found it.",
        "found it —",
        "found it -",
        "serp returned",
        "web search returned",
        # agent_turn._is_triager_opener_ack extras
        "running",
        "working on",
        "looking into",
    }
)

GROUNDING_CANNED_OPENERS: Final[frozenset[str]] = frozenset(
    {
        "found it.",
        "found it —",
        "found it -",
        "serp returned",
        "web search returned",
    }
)
"""Former :data:`grounding._CANNED_OPENERS` — provenance strip/detect prefixes (subset of BARE_OPENERS)."""

if not GROUNDING_CANNED_OPENERS <= BARE_OPENERS:
    msg = "GROUNDING_CANNED_OPENERS must be a subset of BARE_OPENERS"
    raise ValueError(msg)

# Subset used by :func:`is_bare_opener` (P9 triager in-flight ack guard).  Every entry
# is also in :data:`BARE_OPENERS`; the full union includes grounding + routing prefixes
# that must not be misclassified as short acks (e.g. ``here is the``).
_TRIAGER_OPENER_ACK_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "on it",
        "checking",
        "running",
        "pulling",
        "let me",
        "one moment",
        "working on",
        "looking into",
    }
)

MOTION_PROMISE_MARKERS: Final[frozenset[str]] = frozenset(
    {
        # Core motion-promise substrings (W5.2 — quote-specific one-offs removed).
        "on it",
        "doing",
        "executing",
        "rendering",
        "let me",
        "i'll do",
        "starting now",
    }
)


def normalize_opener(text: str) -> str:
    """Collapse whitespace and lower-case text for opener prefix matching.

    Args:
        text (str): Raw opener or tier-B output fragment.

    Returns:
        str: Normalized single-line form suitable for ``startswith`` checks.

    Examples:
        >>> normalize_opener("  On   It — checking.  ")
        'on it — checking.'
    """
    return " ".join(text.strip().lower().split())


def is_bare_opener(text: str) -> bool:
    """Whether ``text`` is a short in-flight ack (bare-opener prefix guard).

    Args:
        text (str): Triager ``first_message`` or tier-B output fragment.

    Returns:
        bool: ``True`` when normalized text starts with a :data:`BARE_OPENERS` prefix.

    Examples:
        >>> is_bare_opener("On it — running the full pipeline.")
        True
        >>> is_bare_opener("Here is the full registry list:")
        False
    """
    normalized = normalize_opener(text)
    if not normalized:
        return False
    return any(normalized.startswith(prefix) for prefix in _TRIAGER_OPENER_ACK_PREFIXES)


def strip_opener_echo(text: str, opener: str) -> str:
    """Remove a leading echo of the triager opener from tier-B output.

    The triager ``first_message`` is already visible before tier-B runs. When tier-B
    opens with the same (or a paraphrase of the same) line, the user sees the ack
    twice. Conservative: only trims an exact (normalised) prefix match or a
    standalone first-line ack followed by more text.

    Args:
        text (str): Tier-B assembled output text.
        opener (str): The triager ``first_message`` already shown to the user.

    Returns:
        str: ``text`` with a leading echo of ``opener`` removed.

    Examples:
        >>> strip_opener_echo("On it — checking.\\n\\nThe answer.", "On it — checking.")
        'The answer.'
        >>> strip_opener_echo("The answer.", "On it — checking.")
        'The answer.'
        >>> strip_opener_echo("On it — checking now.\\n\\nHere's the answer.", "On it — checking now.")
        "Here's the answer."
    """
    pre = (opener or "").strip()
    if not pre or not text.strip():
        return text
    body = text.lstrip()

    pre_norm = normalize_opener(pre)
    if not pre_norm:
        return text
    if normalize_opener(body[: len(pre) + 8]).startswith(pre_norm):
        cut = len(pre)
        while cut < len(body) and body[cut] in " \t.,—-:;!?\n":
            cut += 1
        return body[cut:].lstrip()
    first_line, sep, rest = body.partition("\n")
    if sep and rest.strip() and normalize_opener(first_line) == pre_norm:
        return rest.lstrip()
    return text
