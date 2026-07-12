"""Owner-facing Telegram copy for improve-job transitions (`specs/33-self-improvement.md` §10.6).

Module: sevn.channels.self_improve_copy
Depends: sevn.self_improve.jobs.events

Exports:
    SelfImproveTelegramNotification — rendered text + optional inline keyboard.
    format_self_improve_job_telegram — map job events to Telegram payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sevn.self_improve.jobs.events import ImproveJobEventPayload


@dataclass(frozen=True, slots=True)
class SelfImproveTelegramNotification:
    """Rendered Telegram body plus optional inline keyboard markup."""

    text: str
    inline_keyboard: dict[str, Any] | None = field(default=None)


def _pr_ready_keyboard(*, job_id: str, pr_url: str) -> dict[str, Any]:
    """Build inline keyboard for PR-ready improve-job notifications.

    Args:
        job_id (str): Improve job identifier (truncated in callback data).
        pr_url (str): Pull-request URL for the ``Open PR`` button.

    Returns:
        dict[str, Any]: Telegram ``inline_keyboard`` markup dict.

    Examples:
        >>> kb = _pr_ready_keyboard(job_id="j1", pr_url="https://example/pr/1")
        >>> "inline_keyboard" in kb
        True
    """
    return {
        "inline_keyboard": [
            [
                {"text": "Open PR", "url": pr_url},
                {
                    "text": "Discard run",
                    "callback_data": f"si:abort:{job_id[:48]}",
                },
            ],
        ],
    }


def format_self_improve_job_telegram(
    payload: ImproveJobEventPayload,
) -> SelfImproveTelegramNotification:
    """Render owner-facing Telegram copy for one improve-job event.

    Args:
        payload (ImproveJobEventPayload): Transition or promotion event fields.

    Returns:
        SelfImproveTelegramNotification: Markdown-safe body and optional buttons.

    Examples:
        >>> note = format_self_improve_job_telegram(
        ...     {"job_id": "j1", "state": "queued", "preset": "A", "event": "transition"},
        ... )
        >>> "[Self-improve]" in note.text
        True
        >>> note.inline_keyboard is None
        True
        >>> pr = format_self_improve_job_telegram(
        ...     {
        ...         "job_id": "j1",
        ...         "state": "awaiting_review",
        ...         "preset": "B",
        ...         "event": "promotion_open_pr",
        ...         "pr_url": "https://github.com/o/r/pull/1",
        ...     },
        ... )
        >>> pr.inline_keyboard is not None
        True
    """
    job_id = str(payload.get("job_id", ""))
    state = str(payload.get("state", "queued"))
    preset = str(payload.get("preset", "A"))
    event = str(payload.get("event", "transition"))
    blocked = payload.get("blocked_reason")
    pr_url = payload.get("pr_url")
    shortlist_count = payload.get("shortlist_count")

    head = f"[Self-improve] Job `{job_id[:12]}` · preset {preset}"

    if event == "promotion_open_pr" and isinstance(pr_url, str) and pr_url.strip():
        text = f"{head}\nPR ready — metrics attached.\n{pr_url.strip()}"
        return SelfImproveTelegramNotification(
            text=text,
            inline_keyboard=_pr_ready_keyboard(job_id=job_id, pr_url=pr_url.strip()),
        )

    if state == "queued":
        text = f"{head}\nQueued — waiting for a writer slot."
    elif state == "running":
        text = f"{head}\nRunning sampler and detectors."
    elif state == "awaiting_eval":
        text = f"{head}\nShortlist ready — evaluation starting."
    elif state == "blocked":
        reason = blocked if isinstance(blocked, str) and blocked.strip() else "unknown"
        text = f"{head}\nBlocked ({reason}). Open Mission Control for details."
    elif state == "awaiting_review":
        if isinstance(shortlist_count, int):
            text = f"{head}\nAwaiting review — shortlist has {shortlist_count} turns."
        else:
            text = f"{head}\nAwaiting operator review."
    elif state == "merged":
        text = f"{head}\nPromotion merged."
    elif state == "aborted":
        text = f"{head}\nRun aborted."
    else:
        text = f"{head}\nState: {state}."

    return SelfImproveTelegramNotification(text=text)
