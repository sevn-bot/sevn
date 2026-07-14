"""Retry-storm guard: ``window_transcript`` trims history for tier-B retry passes.

A failed tier-B turn re-runs through summarize / full-index retry passes; without windowing
each pass re-sends the whole transcript (~33 turns observed live), blowing the token budget
~5x. ``window_transcript`` keeps only the last N turns for retries while leaving the narrow
first pass full.
"""

from __future__ import annotations

from sevn.agent.transcript_replay import TranscriptRow
from sevn.gateway.triage.triage_context import window_transcript


def _turns(n: int) -> list[str]:
    return [f"user: m{i}" if i % 2 == 0 else f"assistant: r{i}" for i in range(n)]


def _rows(n: int) -> list[TranscriptRow]:
    return [
        TranscriptRow(
            role="user" if i % 2 == 0 else "assistant",
            text=f"t{i}",
            provider_turn_messages=(
                [{"role": "assistant", "content": f"pm{i}"}] if i % 2 else None
            ),
        )
        for i in range(n)
    ]


def test_window_keeps_last_n_turns() -> None:
    turns, rows = _turns(20), _rows(20)
    wt, wr = window_transcript(turns, rows, max_turns=3)
    assert len(wt) == 6
    assert len(wr) == 6
    assert wt == turns[-6:]
    # Most-recent rows are kept, preserving provider_turn_messages on assistant rows.
    assert wr[-1].text == "t19"
    assert wr[-1].provider_turn_messages == [{"role": "assistant", "content": "pm19"}]


def test_window_passthrough_when_short() -> None:
    turns, rows = _turns(4), _rows(4)
    wt, wr = window_transcript(turns, rows, max_turns=6)
    assert wt == turns
    assert wr == rows


def test_window_disabled_with_nonpositive_cap() -> None:
    turns, rows = _turns(8), _rows(8)
    wt, wr = window_transcript(turns, rows, max_turns=0)
    assert wt == turns
    assert wr == rows
    # Returns copies, not the same list objects (callers mutate freely).
    assert wt is not turns
    assert wr is not rows
