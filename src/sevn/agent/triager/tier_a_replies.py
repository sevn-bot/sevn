"""Tier-A canned greeting reply pools by category (hello / thanks / bye).

Module: sevn.agent.triager.tier_a_replies
Depends: typing

Exports:
    TIER_A_NAME_PLACEHOLDER — ``{name}`` token for USER.md personalization.
    TIER_A_HELLO_REPLY_COUNT — hello pool size (100).
    TIER_A_BYE_REPLY_COUNT — bye pool size (50).
    TIER_A_THANKS_REPLY_COUNT — thanks pool size (25).
    TIER_A_HELLO_REPLIES — hello reply pool (generic + named templates).
    TIER_A_BYE_REPLIES — bye reply pool.
    TIER_A_THANKS_REPLIES — thanks reply pool.
    tier_a_hello_generic_replies — hello templates without ``{name}``.
    tier_a_hello_named_replies — hello templates with ``{name}``.
    tier_a_bye_generic_replies — bye templates without ``{name}``.
    tier_a_bye_named_replies — bye templates with ``{name}``.
    tier_a_thanks_generic_replies — thanks templates without ``{name}``.
    tier_a_thanks_named_replies — thanks templates with ``{name}``.
    TIER_A_REPLIES — alias for :data:`TIER_A_HELLO_REPLIES` (backward compat).
    TIER_A_REPLY_COUNT — alias for :data:`TIER_A_HELLO_REPLY_COUNT`.
    tier_a_generic_replies — alias for :data:`tier_a_hello_generic_replies`.
    tier_a_named_replies — alias for :data:`tier_a_hello_named_replies`.

Examples:
    >>> len(TIER_A_HELLO_REPLIES)
    100
    >>> len(TIER_A_BYE_REPLIES)
    50
    >>> len(TIER_A_THANKS_REPLIES)
    25
    >>> TIER_A_NAME_PLACEHOLDER in tier_a_hello_named_replies[0]
    True
"""

from __future__ import annotations

from typing import Final

TIER_A_NAME_PLACEHOLDER: Final[str] = "{name}"

TIER_A_HELLO_REPLY_COUNT: Final[int] = 100
TIER_A_BYE_REPLY_COUNT: Final[int] = 50
TIER_A_THANKS_REPLY_COUNT: Final[int] = 25

# Backward-compat aliases (hello pool was the original single pool).
TIER_A_REPLY_COUNT: Final[int] = TIER_A_HELLO_REPLY_COUNT

_HELLO_GENERIC_SEEDS: Final[tuple[str, ...]] = (
    "Hi! What's on your mind?",
    "Hey — what can I help with?",
    "Hello! Ready when you are.",
    "Hey there — what's up?",
    "Hi there — good to hear from you.",
    "Hello — how can I help today?",
    "Hey! What would you like to do?",
    "Hi — what's the plan?",
    "Hello there — need anything?",
    "Hey — ready when you are.",
)

_HELLO_NAMED_SEEDS: Final[tuple[str, ...]] = (
    "Hi {name}! What's on your mind?",
    "Hey {name} — what can I help with?",
    "Hello {name}! Ready when you are.",
    "Hey there, {name} — what's up?",
    "Hi {name} — good to hear from you.",
    "Hello {name} — how can I help today?",
    "Hey {name}! What would you like to do?",
    "Hi {name} — what's the plan?",
    "Hello there, {name} — need anything?",
    "Hey {name} — ready when you are.",
)

_HELLO_GENERIC_STEMS: Final[tuple[str, ...]] = (
    "Hi",
    "Hey",
    "Hello",
    "Hi there",
    "Hey there",
    "Hello there",
    "Good morning",
    "Good afternoon",
    "Good evening",
    "Howdy",
)

_HELLO_GENERIC_PROMPTS: Final[tuple[str, ...]] = (
    "what's on your mind?",
    "what can I help with?",
    "what's up?",
    "how can I help?",
    "ready when you are.",
    "what would you like to do?",
    "need anything?",
    "what are we tackling?",
    "what's the plan?",
    "how's it going?",
)

_HELLO_NAMED_STEMS: Final[tuple[str, ...]] = (
    "Hi {name}",
    "Hey {name}",
    "Hello {name}",
    "Hi there, {name}",
    "Hey there, {name}",
    "Hello there, {name}",
    "Good morning, {name}",
    "Good afternoon, {name}",
    "Good evening, {name}",
    "Howdy, {name}",
)

_HELLO_NAMED_PROMPTS: Final[tuple[str, ...]] = _HELLO_GENERIC_PROMPTS

_BYE_GENERIC_SEEDS: Final[tuple[str, ...]] = (
    "See you! 👋",
    "Take care — ping me anytime.",
    "Bye for now — talk soon!",
    "Goodbye! Catch you later.",
    "Later — I'm here when you need me.",
)

_BYE_NAMED_SEEDS: Final[tuple[str, ...]] = (
    "See you, {name}! 👋",
    "Take care, {name} — ping me anytime.",
    "Bye for now, {name} — talk soon!",
    "Goodbye, {name}! Catch you later.",
    "Later, {name} — I'm here when you need me.",
)

_BYE_GENERIC_STEMS: Final[tuple[str, ...]] = (
    "Bye",
    "Goodbye",
    "See you",
    "Take care",
    "Catch you later",
    "Talk soon",
)

_BYE_GENERIC_PROMPTS: Final[tuple[str, ...]] = (
    "👋",
    "— ping me anytime.",
    "— talk soon!",
    "— catch you later.",
    "for now!",
    "later!",
)

_BYE_NAMED_STEMS: Final[tuple[str, ...]] = (
    "Bye, {name}",
    "Goodbye, {name}",
    "See you, {name}",
    "Take care, {name}",
    "Catch you later, {name}",
    "Talk soon, {name}",
)

_BYE_NAMED_PROMPTS: Final[tuple[str, ...]] = _BYE_GENERIC_PROMPTS

_THANKS_GENERIC_SEEDS: Final[tuple[str, ...]] = (
    "Anytime!",
    "You got it 👍",
    "Happy to help.",
    "No problem!",
    "Glad I could help.",
)

_THANKS_NAMED_SEEDS: Final[tuple[str, ...]] = (
    "Anytime, {name}!",
    "You got it, {name} 👍",
    "Happy to help, {name}.",
    "No problem, {name}!",
    "Glad I could help, {name}.",
)

_THANKS_GENERIC_STEMS: Final[tuple[str, ...]] = (
    "Anytime",
    "You got it",
    "Happy to help",
    "No problem",
    "Glad to help",
    "My pleasure",
)

_THANKS_GENERIC_PROMPTS: Final[tuple[str, ...]] = (
    "!",
    " 👍",
    ".",
    " — anytime.",
    " — glad to help.",
)

_THANKS_NAMED_STEMS: Final[tuple[str, ...]] = (
    "Anytime, {name}",
    "You got it, {name}",
    "Happy to help, {name}",
    "No problem, {name}",
    "Glad to help, {name}",
    "My pleasure, {name}",
)

_THANKS_NAMED_PROMPTS: Final[tuple[str, ...]] = _THANKS_GENERIC_PROMPTS


def _join_opener(stem: str, prompt: str) -> str:
    """Join a greeting stem and follow-up prompt into one line.

    Args:
        stem (str): Opening phrase.
        prompt (str): Short follow-up clause.

    Returns:
        str: Single-line greeting.

    Examples:
        >>> _join_opener("Hi", "what's up?")
        "Hi — What's up?"
    """
    if stem.startswith("Good "):
        return f"{stem}! {prompt[:1].upper()}{prompt[1:]}"
    if prompt in ("!", ".", " 👍"):
        return f"{stem}{prompt}"
    if prompt.startswith(("—", "for ", "later")):
        return f"{stem} {prompt}"
    punct = "!" if "?" not in prompt else " —"
    return f"{stem}{punct} {prompt[:1].upper()}{prompt[1:]}"


def _dedupe_extend(target: list[str], candidates: tuple[str, ...], *, limit: int) -> None:
    """Append unique candidates until ``target`` reaches ``limit`` entries.

    Args:
        target (list[str]): Mutable reply list.
        candidates (tuple[str, ...]): Candidate lines in priority order.
        limit (int): Target list length.

    Returns:
        None: Mutates ``target`` in place.

    Examples:
        >>> rows: list[str] = []
        >>> _dedupe_extend(rows, ("a", "a", "b"), limit=2)
        >>> rows
        ['a', 'b']
    """
    seen = set(target)
    for line in candidates:
        if len(target) >= limit:
            return
        if line in seen:
            continue
        target.append(line)
        seen.add(line)


def _build_reply_half(
    *,
    seeds: tuple[str, ...],
    stems: tuple[str, ...],
    prompts: tuple[str, ...],
    limit: int,
    filler_generic: str,
    filler_named: str,
) -> tuple[str, ...]:
    """Build one half of a tier-A pool (generic or named).

    Args:
        seeds (tuple[str, ...]): Hand-authored seed lines.
        stems (tuple[str, ...]): Opener stems for combinatorial expansion.
        prompts (tuple[str, ...]): Follow-up prompts for expansion.
        limit (int): Half-pool size.
        filler_generic (str): Generic filler template when combos run short.
        filler_named (str): Named filler template when combos run short.

    Returns:
        tuple[str, ...]: Exactly ``limit`` unique reply templates.

    Examples:
        >>> half = _build_reply_half(
        ...     seeds=("Hi!",),
        ...     stems=("Hey",),
        ...     prompts=("what's up?",),
        ...     limit=2,
        ...     filler_generic="Hey — what's up?",
        ...     filler_named="Hey {name} — what's up?",
        ... )
        >>> len(half) == 2
        True
    """
    built: list[str] = []
    _dedupe_extend(built, seeds, limit=limit)
    combos = tuple(_join_opener(stem, prompt) for stem in stems for prompt in prompts)
    _dedupe_extend(built, combos, limit=limit)
    filler = filler_named if TIER_A_NAME_PLACEHOLDER in seeds[0] else filler_generic
    idx = 0
    while len(built) < limit:
        candidate = (
            filler if idx == 0 else f"{filler[:-1] if filler.endswith('.') else filler} ({idx + 1})"
        )
        if candidate not in built:
            built.append(candidate)
        idx += 1
    return tuple(built[:limit])


def _build_category_replies(
    *,
    generic_limit: int,
    named_limit: int,
    generic_seeds: tuple[str, ...],
    named_seeds: tuple[str, ...],
    generic_stems: tuple[str, ...],
    generic_prompts: tuple[str, ...],
    named_stems: tuple[str, ...],
    named_prompts: tuple[str, ...],
    filler_generic: str,
    filler_named: str,
) -> tuple[str, ...]:
    """Build a full category pool (generic half + named half).

    Args:
        generic_limit (int): Generic half size.
        named_limit (int): Named half size.
        generic_seeds (tuple[str, ...]): Generic seed lines.
        named_seeds (tuple[str, ...]): Named seed lines.
        generic_stems (tuple[str, ...]): Generic opener stems.
        generic_prompts (tuple[str, ...]): Generic follow-up prompts.
        named_stems (tuple[str, ...]): Named opener stems.
        named_prompts (tuple[str, ...]): Named follow-up prompts.
        filler_generic (str): Generic filler line.
        filler_named (str): Named filler line.

    Returns:
        tuple[str, ...]: Generic half followed by named half.

    Examples:
        >>> pool = _build_category_replies(
        ...     generic_limit=2,
        ...     named_limit=2,
        ...     generic_seeds=("Hi!", "Hey!"),
        ...     named_seeds=("Hi {name}!", "Hey {name}!"),
        ...     generic_stems=("Hi",),
        ...     generic_prompts=("what's up?",),
        ...     named_stems=("Hi {name}",),
        ...     named_prompts=("what's up?",),
        ...     filler_generic="Hi — what's up?",
        ...     filler_named="Hi {name} — what's up?",
        ... )
        >>> len(pool) == 4
        True
    """
    generic = _build_reply_half(
        seeds=generic_seeds,
        stems=generic_stems,
        prompts=generic_prompts,
        limit=generic_limit,
        filler_generic=filler_generic,
        filler_named=filler_named,
    )
    named = _build_reply_half(
        seeds=named_seeds,
        stems=named_stems,
        prompts=named_prompts,
        limit=named_limit,
        filler_generic=filler_generic,
        filler_named=filler_named,
    )
    return generic + named


def _split_generic_named(pool: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a pool into generic and named template halves.

    Args:
        pool (tuple[str, ...]): Full reply pool.

    Returns:
        tuple[tuple[str, ...], tuple[str, ...]]: ``(generic, named)`` partitions.

    Examples:
        >>> g, n = _split_generic_named(("Hi!", "Hey {name}!"))
        >>> g == ("Hi!",) and n == ("Hey {name}!",)
        True
    """
    generic = tuple(line for line in pool if TIER_A_NAME_PLACEHOLDER not in line)
    named = tuple(line for line in pool if TIER_A_NAME_PLACEHOLDER in line)
    return generic, named


TIER_A_HELLO_REPLIES: Final[tuple[str, ...]] = _build_category_replies(
    generic_limit=TIER_A_HELLO_REPLY_COUNT // 2,
    named_limit=TIER_A_HELLO_REPLY_COUNT // 2,
    generic_seeds=_HELLO_GENERIC_SEEDS,
    named_seeds=_HELLO_NAMED_SEEDS,
    generic_stems=_HELLO_GENERIC_STEMS,
    generic_prompts=_HELLO_GENERIC_PROMPTS,
    named_stems=_HELLO_NAMED_STEMS,
    named_prompts=_HELLO_NAMED_PROMPTS,
    filler_generic="Hey — what's on your mind?",
    filler_named="Hey {name} — what's on your mind?",
)

TIER_A_BYE_REPLIES: Final[tuple[str, ...]] = _build_category_replies(
    generic_limit=TIER_A_BYE_REPLY_COUNT // 2,
    named_limit=TIER_A_BYE_REPLY_COUNT // 2,
    generic_seeds=_BYE_GENERIC_SEEDS,
    named_seeds=_BYE_NAMED_SEEDS,
    generic_stems=_BYE_GENERIC_STEMS,
    generic_prompts=_BYE_GENERIC_PROMPTS,
    named_stems=_BYE_NAMED_STEMS,
    named_prompts=_BYE_NAMED_PROMPTS,
    filler_generic="See you! 👋",
    filler_named="See you, {name}! 👋",
)

TIER_A_THANKS_REPLIES: Final[tuple[str, ...]] = _build_category_replies(
    generic_limit=13,
    named_limit=12,
    generic_seeds=_THANKS_GENERIC_SEEDS,
    named_seeds=_THANKS_NAMED_SEEDS,
    generic_stems=_THANKS_GENERIC_STEMS,
    generic_prompts=_THANKS_GENERIC_PROMPTS,
    named_stems=_THANKS_NAMED_STEMS,
    named_prompts=_THANKS_NAMED_PROMPTS,
    filler_generic="Anytime!",
    filler_named="Anytime, {name}!",
)

tier_a_hello_generic_replies, tier_a_hello_named_replies = _split_generic_named(
    TIER_A_HELLO_REPLIES
)
tier_a_bye_generic_replies, tier_a_bye_named_replies = _split_generic_named(TIER_A_BYE_REPLIES)
tier_a_thanks_generic_replies, tier_a_thanks_named_replies = _split_generic_named(
    TIER_A_THANKS_REPLIES,
)

TIER_A_REPLIES: Final[tuple[str, ...]] = TIER_A_HELLO_REPLIES
tier_a_generic_replies: Final[tuple[str, ...]] = tier_a_hello_generic_replies
tier_a_named_replies: Final[tuple[str, ...]] = tier_a_hello_named_replies


def _verify_tier_a_reply_pool_lengths() -> None:
    """Raise when hello/thanks/bye reply pools drift from W7 size contract.

    Examples:
        >>> _verify_tier_a_reply_pool_lengths()
    """
    checks: tuple[tuple[int, int, str], ...] = (
        (len(TIER_A_HELLO_REPLIES), TIER_A_HELLO_REPLY_COUNT, "hello"),
        (len(tier_a_hello_generic_replies), TIER_A_HELLO_REPLY_COUNT // 2, "hello generic"),
        (len(tier_a_hello_named_replies), TIER_A_HELLO_REPLY_COUNT // 2, "hello named"),
        (len(TIER_A_BYE_REPLIES), TIER_A_BYE_REPLY_COUNT, "bye"),
        (len(tier_a_bye_generic_replies), TIER_A_BYE_REPLY_COUNT // 2, "bye generic"),
        (len(tier_a_bye_named_replies), TIER_A_BYE_REPLY_COUNT // 2, "bye named"),
        (len(TIER_A_THANKS_REPLIES), TIER_A_THANKS_REPLY_COUNT, "thanks"),
        (len(tier_a_thanks_generic_replies), 13, "thanks generic"),
        (len(tier_a_thanks_named_replies), 12, "thanks named"),
    )
    for actual, expected, label in checks:
        if actual != expected:
            msg = f"tier-A {label} reply pool length {actual} != {expected}"
            raise ValueError(msg)


_verify_tier_a_reply_pool_lengths()
