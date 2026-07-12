"""User-visible canned messages on turn failure, empty output, or escalation gaps.

These strings reach the user verbatim when the gateway can't deliver a real
answer. Keep them informative — when the bot hits its round budget, "Tier C/D
not configured" is more useful than a generic apology.

Module: sevn.prompts.fallbacks
Depends: (none)

Exports:
    format_cascade_budget_exhausted_message — D7 cascade cap copy with optional partial.
    format_empty_output_message — empty-turn fallback; surfaces partial progress when present.
    format_tier_b_operator_failure_report — D8 tier-B no-answer operator report.
    looks_like_unfinished_assistant_reply — detect prior no-answer assistant lines.
    unfinished_reply_markers — substrings for unfinished-reply detection.
    match_continuation_phrase — normalised short continuation phrase match.
    is_retry_back_reference_phrase — retry subset used by gateway back-reference.
    normalize_short_message — punctuation-trimmed short-message key.
    render_no_answer_message — map reason label to user-facing line.

Note:
    All other module-level string constants here are part of the public API surface;
    they are simple assignments and intentionally not listed in ``Exports``.
"""

from __future__ import annotations

# Tier-B / Tier-C/D escalation templates (formatted by the executor with the
# target tier name and the rounds-tried summary).
TIER_B_SELF_ESCALATION_TEMPLATE: str = (
    "This needs more tools / a planner - switching to tier {tier} and continuing."
)
TIER_B_ROUND_BUDGET_TEMPLATE: str = (
    "I've used my round budget for this turn - escalating to tier {tier} to finish."
)
TIER_B_REPEATED_WRONG_CALL_TEMPLATE: str = (
    "I repeated the same failing tool call — escalating to tier {tier} to try a different approach."
)
ASSISTANT_NO_OUTPUT_PLACEHOLDER: str = "(no output)"
"""Internal executor placeholder that must never be persisted or sent to the user."""
# Wave 3 (CONVERSATION_REVIEW_2026-05-28.md §A12): when there is no expanded /
# tier-C path to escalate to, surface the cap explicitly. ``{rounds}`` is the
# concrete budget that was exhausted.
TIER_B_ROUND_BUDGET_STOP_TEMPLATE: str = (
    "Stopping after {rounds} rounds. The request needed more steps than the budget "
    "allows — try splitting it, naming a specific target file/path, or use `try "
    "again` after rephrasing."
)
TIER_B_ROUND_BUDGET_NO_ESCALATION_TEMPLATE: str = (
    "I hit my {rounds}-round budget without finishing. Tier C/D is not configured "
    "(see `specs/21-executor-tier-cd.md` §2 to enable). What I tried: {tool_calls}. "
    "Try splitting the request or rephrasing."
)

# Gateway user-visible strings for unwired-executor + no-answer paths.
TIER_UNSUPPORTED_USER_MESSAGE: str = (
    "That kind of task needs a deeper executor tier that is not wired on this gateway yet."
)

ESCALATION_UNAVAILABLE_USER_MESSAGE: str = (
    "I tried to hand this off to a deeper planner tier but tier C/D isn't configured on "
    "this gateway (see `specs/21-executor-tier-cd.md` §2 to enable). I used my round "
    "budget on this turn without finishing. Try splitting the request into smaller asks, "
    "narrowing to one file or path, or ask me to check the logs for what blocked it."
)

EXECUTOR_NO_ANSWER_FALLBACK: str = (
    "I couldn't generate a follow-up just now — the executor returned no text and no "
    "tool call. Please try rephrasing, or ask me to check the logs."
)

# Tier-B answer finalizer fallbacks keyed by ``FinalizationStatus``.
FINALIZER_TIMEOUT_MESSAGE: str = (
    "I ran out of time on this turn before finishing. "
    "Try again with a narrower ask, or break it into separate steps."
)
FINALIZER_EMPTY_MESSAGE: str = (
    "I finished the turn without producing a reply. This usually means the LLM "
    "returned no text and no tool call on its last round, or the round budget ran "
    "out before an answer was assembled. Try rephrasing, or ask me to check the logs."
)
FINALIZER_CANCELLED_MESSAGE: str = (
    "Switching to your new message — the previous request was dropped."
)
FINALIZER_ERROR_MESSAGE: str = "Sorry — an internal error stopped that turn. Try again."

_CASCADE_BUDGET_EXHAUSTED_PREFIX: str = "I ran out of time on this turn before finishing."
_CASCADE_BUDGET_EXHAUSTED_PARTIAL: str = " Here's what I found so far: {partial}"
_CASCADE_BUDGET_EXHAUSTED_RETRY: str = (
    " Want me to keep going on this thread, or narrow it to a specific part?"
)


def format_cascade_budget_exhausted_message(partial_progress: str | None = None) -> str:
    """Build the cumulative cascade cap message (D7: partial progress + retry invite).

    Args:
        partial_progress (str | None): Best-effort excerpt from streaming or executor
            output gathered before the cap fired.

    Returns:
        str: Operator-facing line without blame framing ("Abandoned", etc.).

    Examples:
        >>> "keep going" in format_cascade_budget_exhausted_message()
        True
        >>> "Abandoned" not in format_cascade_budget_exhausted_message("found sessions")
        True
        >>> "found sessions" in format_cascade_budget_exhausted_message("found sessions")
        True
    """
    text = _CASCADE_BUDGET_EXHAUSTED_PREFIX
    partial = (partial_progress or "").strip()
    if partial:
        text += _CASCADE_BUDGET_EXHAUSTED_PARTIAL.format(partial=partial)
    text += _CASCADE_BUDGET_EXHAUSTED_RETRY
    return text


_EMPTY_OUTPUT_SALVAGE_PREFIX: str = (
    "I couldn't compose a final answer for that turn — a step likely failed before I finished."
)
_EMPTY_OUTPUT_SALVAGE_PARTIAL: str = " Here's what I gathered: {partial}"
_EMPTY_OUTPUT_SALVAGE_RETRY: str = " Want me to try again?"


def format_empty_output_message(partial_progress: str | None = None) -> str:
    """Build the empty-output fallback, surfacing partial progress when available.

    Graceful-degrade path for a turn that produced no deliverable text (e.g. a tool
    looped to its retry cap). With nothing salvageable it returns the plain
    :data:`TURN_EMPTY_FALLBACK_TEXT`; with a partial excerpt it reports the failure
    honestly, shows what was gathered, and invites a retry rather than sending nothing.

    Args:
        partial_progress (str | None): Best-effort excerpt from streaming or executor
            output gathered before the turn ended without a final answer.

    Returns:
        str: The generic empty-turn line when no partial exists, otherwise an honest
        degrade message embedding the partial.

    Examples:
        >>> format_empty_output_message() == TURN_EMPTY_FALLBACK_TEXT
        True
        >>> "what I gathered" in format_empty_output_message("found sessions")
        True
        >>> "found sessions" in format_empty_output_message("found sessions")
        True
    """
    partial = (partial_progress or "").strip()
    if not partial:
        return TURN_EMPTY_FALLBACK_TEXT
    text = _EMPTY_OUTPUT_SALVAGE_PREFIX
    text += _EMPTY_OUTPUT_SALVAGE_PARTIAL.format(partial=partial)
    text += _EMPTY_OUTPUT_SALVAGE_RETRY
    return text


def format_tier_b_operator_failure_report(
    *,
    failure_detail: str | None = None,
    tool_name: str | None = None,
    tool_error: str | None = None,
) -> str:
    """Build a no-answer operator report when tier-B stops without assistant text (D8).

    Args:
        failure_detail (str | None): Harness/machine label (e.g. ``no assistant output``).
        tool_name (str | None): Last tool that returned ``ok=false``, if any.
        tool_error (str | None): Error string from that tool envelope.

    Returns:
        str: Actionable report naming what was attempted and inviting retry.

    Examples:
        >>> msg = format_tier_b_operator_failure_report(
        ...     tool_name="history",
        ...     tool_error="timeout",
        ... )
        >>> "history" in msg and "try again" in msg.lower()
        True
        >>> "no data" not in msg.lower() and "no history" not in msg.lower()
        True
    """
    lines: list[str] = [
        "I couldn't finish a full answer on this turn.",
    ]
    if tool_name:
        err = (tool_error or "ok=false").strip()
        lines.append(f"I tried `{tool_name}` and it failed: {err}.")
    elif failure_detail:
        lines.append(f"What stopped me: {failure_detail.strip()}.")
    lines.append(
        "I have not confirmed the data is missing — retrieval may have failed. "
        "Try again, name a narrower path, or ask me to check the logs."
    )
    return " ".join(lines)


FINALIZER_FALLBACK_MESSAGES: dict[str, str] = {
    "timeout": FINALIZER_TIMEOUT_MESSAGE,
    "empty": FINALIZER_EMPTY_MESSAGE,
    "cancelled": FINALIZER_CANCELLED_MESSAGE,
    "error": FINALIZER_ERROR_MESSAGE,
}

# Tier-C/D decompose phase: the LLM returned non-JSON or schema-violating JSON.
# The harness appends a 200-char snippet for diagnostic value.
CD_DECOMPOSE_PARSE_FAILURE_PREFIX: str = (
    "Sorry — I could not parse the execution plan. Decompose output missing `steps`."
)

# Router + gateway empty-turn fallback (``channel_router.route_outgoing`` and
# ``agent_turn._render_no_answer_message`` for ``empty_output:*`` reasons).
TURN_EMPTY_FALLBACK_TEXT: str = (
    "I finished the turn but had nothing to send. Try rephrasing the request."
)

# Typed reason → user-facing line for gateway no-answer paths (transcript-review #8).
NO_ANSWER_MESSAGES: dict[str, str] = {
    "timeout": FINALIZER_TIMEOUT_MESSAGE,
    "timeout_expanded_retry": (
        "I retried with the expanded toolkit and still ran out of time on this turn. "
        "Try a simpler version of the request, or split it into steps."
    ),
    "exception": (
        "An error interrupted the turn before I could answer. "
        "The trace is in the logs — try again, or rephrase if it keeps happening."
    ),
    "exception_expanded_retry": (
        "Both the first attempt and the expanded-budget retry hit errors. The trace is in the logs."
    ),
    "missing_outcome": ("I ended that turn without producing an answer. Try again."),
    "unhandled_exception": (
        "An unexpected error happened while running that turn. The full trace is in the logs."
    ),
    "first_session_intro_failure": (
        "I couldn't finish the first-session introduction — the model provider rejected "
        "the request. Check proxy.log for details, then try again or send skip intro."
    ),
    "fabricated_file_delivery": (
        "I wasn't able to deliver that file — a tool step failed and I should not have "
        "claimed success. I'll need to retry the render/send steps."
    ),
    "cancelled_by_new_message": (
        "That turn was interrupted by your next message — I stopped mid-flight to handle it."
    ),
}

# Distinctive substrings for ``looks_like_unfinished_assistant_reply`` — each must
# appear in the corresponding :data:`NO_ANSWER_MESSAGES` value (case-insensitive).
_NO_ANSWER_UNFINISHED_MARKERS: dict[str, str] = {
    "timeout": "ran out of time",
    "timeout_expanded_retry": "expanded toolkit",
    "exception": "error interrupted",
    "exception_expanded_retry": "expanded-budget retry",
    "missing_outcome": "without producing an answer",
    "unhandled_exception": "unexpected error",
    "first_session_intro_failure": "first-session introduction",
    "fabricated_file_delivery": "wasn't able to deliver that file",
    "cancelled_by_new_message": "interrupted by your next message",
}

# Other assistant failure lines not keyed in :data:`NO_ANSWER_MESSAGES`.
_EXTRA_UNFINISHED_MARKERS: tuple[str, ...] = (
    "had nothing to send",
    "couldn't compose a final answer",
    "couldn't generate a follow-up",
    "tier c/d is not configured",
    "could not parse the execution plan",
    "round budget",
    "expanded budget",
)

# Short follow-up continuations when a prior turn already routed to tier B/C/D.
# Normalised whole-message match (punctuation-trimmed, lowercased, whitespace collapsed).
# Multi-word phrases are allowed up to :data:`CONTINUATION_MAX_WORDS`.
CONTINUATION_MAX_WORDS: int = 4
CONTINUATION_PHRASES: frozenset[str] = frozenset(
    {
        "so",
        "and",
        "but",
        "then",
        "now",
        "go ahead",
        "go on",
        "continue",
        "keep going",
        "try again",
        "retry",
        "again",
        "redo",
        "do it",
        "do that",
        "just do it",
        "yes",
        "yes please",
        "yep",
        "please",
        "please do",
        "you just talk",
        "get on with it",
        "hurry up",
    },
)

# Subset of :data:`CONTINUATION_PHRASES` that trigger gateway retry back-reference
# (``agent_turn._resolve_retry_back_reference``) when the prior assistant line was
# unfinished. Triager continuation fast-path uses the superset via
# :func:`match_continuation_phrase`.
#
# Precedence (no double-fire): gateway back-reference runs **before** triage and
# rewrites e.g. ``try again`` into the prior user request, so
# ``try_fast_continuation_triage`` never sees the bare retry phrase when back-ref
# applies. Continuation-only phrases (``go ahead``, ``so``) never match back-ref.
RETRY_BACKREF_PHRASES: frozenset[str] = frozenset(
    {
        "try again",
        "again",
        "redo",
        "continue",
        "keep going",
    },
)


def _validate_no_answer_markers() -> None:
    """Assert every no-answer marker is a substring of its message (import-time).

    Examples:
        >>> _validate_no_answer_markers() is None
        True
    """
    for reason, marker in _NO_ANSWER_UNFINISHED_MARKERS.items():
        message = NO_ANSWER_MESSAGES[reason]
        if marker.lower() not in message.lower():
            msg = f"{reason!r}: marker {marker!r} not in message"
            raise AssertionError(msg)
    if "had nothing to send" not in TURN_EMPTY_FALLBACK_TEXT.lower():
        raise AssertionError("TURN_EMPTY_FALLBACK_TEXT missing had nothing to send")


_validate_no_answer_markers()


def unfinished_reply_markers() -> tuple[str, ...]:
    """Return substrings that identify prior no-answer assistant lines.

    Returns:
        tuple[str, ...]: Sorted unique markers derived from :data:`NO_ANSWER_MESSAGES`
        and other known fallback copy.

    Examples:
        >>> "had nothing to send" in unfinished_reply_markers()
        True
    """
    markers = set(_EXTRA_UNFINISHED_MARKERS)
    markers.update(_NO_ANSWER_UNFINISHED_MARKERS.values())
    return tuple(sorted(markers))


def looks_like_unfinished_assistant_reply(text: str) -> bool:
    """Return True when ``text`` matches a known no-answer/failure line.

    Args:
        text (str): Assistant message body.

    Returns:
        bool: True when the assistant line signals incomplete work.

    Examples:
        >>> looks_like_unfinished_assistant_reply(
        ...     "I finished the turn but had nothing to send."
        ... )
        True
        >>> looks_like_unfinished_assistant_reply("Here are the folders you asked for.")
        False
    """
    probe = text.strip().lower()
    if not probe:
        return False
    return any(marker in probe for marker in unfinished_reply_markers())


def render_no_answer_message(reason: str, *, partial_progress: str | None = None) -> str:
    """Map a no-answer reason label to a user-facing line.

    Args:
        reason (str): Machine-readable label like ``timeout`` or
            ``empty_output:status=ok``.
        partial_progress (str | None): Optional partial answer for budget-exhausted.

    Returns:
        str: Specific user message when the reason is known; the generic
        ``EXECUTOR_NO_ANSWER_FALLBACK`` otherwise.

    Examples:
        >>> "ran out of time" in render_no_answer_message("timeout").lower()
        True
        >>> render_no_answer_message("nonsense") == EXECUTOR_NO_ANSWER_FALLBACK
        True
        >>> render_no_answer_message("empty_output:status=ok") == TURN_EMPTY_FALLBACK_TEXT
        True
    """
    if reason == "cascade_budget_exhausted":
        return format_cascade_budget_exhausted_message(partial_progress)
    if reason in NO_ANSWER_MESSAGES:
        return NO_ANSWER_MESSAGES[reason]
    if reason.startswith("empty_output"):
        return format_empty_output_message(partial_progress)
    return EXECUTOR_NO_ANSWER_FALLBACK


def normalize_short_message(text: str) -> str:
    """Return a punctuation-trimmed, lowercased message key for token matching.

    Args:
        text (str): Raw user message.

    Returns:
        str: Normalised comparison key (may be empty).

    Examples:
        >>> normalize_short_message("  So?  ")
        'so'
        >>> normalize_short_message("Go Ahead!!")
        'go ahead'
    """
    norm = " ".join(text.strip().lower().split()).strip(" \t.,!?;:—-…")
    return " ".join(norm.split())


def match_continuation_phrase(text: str) -> str | None:
    """Return the normalised phrase when the message is an obvious continuation.

    Only short whole-message continuations (``≤ CONTINUATION_MAX_WORDS`` words)
    match. Substantive follow-ups ("ok now I see it") return ``None``.

    Args:
        text (str): Raw user message.

    Returns:
        str | None: Matched continuation phrase, else ``None``.

    Examples:
        >>> match_continuation_phrase("so?")
        'so'
        >>> match_continuation_phrase("go ahead")
        'go ahead'
        >>> match_continuation_phrase("try again!")
        'try again'
        >>> match_continuation_phrase("ok now I see it") is None
        True
    """
    norm = normalize_short_message(text)
    if not norm:
        return None
    if len(norm.split()) > CONTINUATION_MAX_WORDS:
        return None
    return norm if norm in CONTINUATION_PHRASES else None


def is_retry_back_reference_phrase(text: str) -> bool:
    """Return whether ``text`` is a short "retry previous request" utterance.

    Args:
        text (str): Raw latest user message.

    Returns:
        bool: True when text is a retry/back-reference phrase.

    Examples:
        >>> is_retry_back_reference_phrase("try again")
        True
        >>> is_retry_back_reference_phrase("again?")
        True
        >>> is_retry_back_reference_phrase("list source_code/src")
        False
    """
    norm = normalize_short_message(text)
    if not norm:
        return False
    return norm in RETRY_BACKREF_PHRASES
