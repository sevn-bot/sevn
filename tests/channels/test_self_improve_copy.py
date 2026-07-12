"""Telegram copy for improve-job notifications (`specs/33-self-improvement.md` §10.6)."""

from __future__ import annotations

from sevn.channels.self_improve_copy import format_self_improve_job_telegram


def test_queued_job_copy_has_self_improve_prefix() -> None:
    note = format_self_improve_job_telegram(
        {"job_id": "abc", "state": "queued", "preset": "A", "event": "transition"},
    )
    assert note.text.startswith("[Self-improve]")
    assert "Queued" in note.text
    assert note.inline_keyboard is None


def test_pr_ready_copy_includes_open_pr_button() -> None:
    note = format_self_improve_job_telegram(
        {
            "job_id": "job123",
            "state": "awaiting_review",
            "preset": "B",
            "event": "promotion_open_pr",
            "pr_url": "https://github.com/o/r/pull/814",
        },
    )
    assert "PR ready" in note.text
    assert note.inline_keyboard is not None
    row = note.inline_keyboard["inline_keyboard"][0]
    assert row[0]["text"] == "Open PR"
    assert row[1]["text"] == "Discard run"
