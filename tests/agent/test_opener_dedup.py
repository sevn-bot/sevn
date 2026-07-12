"""Regression: leading duplicated triager opener is stripped from the tier-B final.

The triager ``first_message`` ("On it — …") is shown to the user before tier-B runs.
When tier-B opens its substantive answer with the same line, the user would see the
ack twice. The gateway delivery path (``_strip_preamble_echo``) removes the leading
echo while preserving the body, and the harness mirror (``_strip_opener_echo``) does
the same for its opener-only classification (`specs/14-executor-tier-b.md` §2.7).
"""

from __future__ import annotations

from sevn.agent.executors.b_harness import _strip_opener_echo
from sevn.gateway.agent_turn import _strip_preamble_echo


def test_gateway_strips_duplicated_opener_keeps_body() -> None:
    opener = "On it — let me pull the registry list."
    final = f"{opener}\n\nYour tools are: read, glob, list_registry."
    out = _strip_preamble_echo(final, opener)
    assert out == "Your tools are: read, glob, list_registry."


def test_gateway_strips_inline_opener_prefix() -> None:
    opener = "On it — checking."
    # Opener restated inline on the same line, followed by real content.
    out = _strip_preamble_echo("On it — checking. The answer is 42.", opener)
    assert out == "The answer is 42."


def test_gateway_preserves_answer_without_opener() -> None:
    opener = "On it — checking."
    final = "The workspace has 3 folders: a, b, c."
    assert _strip_preamble_echo(final, opener) == final


def test_gateway_does_not_mangle_real_content_that_merely_starts_similar() -> None:
    # A substantive answer that does not restate the opener is untouched.
    opener = "Mmm, let me see…"
    final = "Let me explain how the gateway turn spine works in detail."
    assert _strip_preamble_echo(final, opener) == final


def test_harness_strip_opener_echo_keeps_substantive_body() -> None:
    opener = "On it — checking."
    out = _strip_opener_echo("On it — checking.\n\nThe answer.", opener)
    assert out == "The answer."
    # No opener present → body preserved verbatim.
    assert _strip_opener_echo("The answer.", opener) == "The answer."
