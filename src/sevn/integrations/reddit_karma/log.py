"""Structured decision log for the Reddit karma loop (#74, W33.7).

Module: sevn.integrations.reddit_karma.log
Depends: json, pathlib, datetime

Exports:
    RedditDecisionLog — append-only JSONL logger under ``.sevn/reddit-karma-loop/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — runtime workspace paths in decision log
from typing import Any


@dataclass(slots=True)
class RedditDecisionLog:
    """Append-only JSONL log for candidates, skips, drafts, and outcomes."""

    workspace: Path
    path: Path = field(init=False)

    def __post_init__(self) -> None:
        """Ensure the log directory exists and bind ``decisions.jsonl``.

        Examples:
            >>> from pathlib import Path
            >>> import tempfile
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     log = RedditDecisionLog(Path(tmp))
            ...     log.path.name
            'decisions.jsonl'
        """
        base = self.workspace / ".sevn" / "reddit-karma-loop"
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "decisions.jsonl"

    def append(
        self,
        *,
        event: str,
        candidate: dict[str, Any] | None = None,
        skip_reason: str | None = None,
        draft: dict[str, Any] | None = None,
        action: str | None = None,
        url: str | None = None,
        outcome: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one decision row and return the serialized record.

        Args:
            event (str): Event kind (``candidate``, ``skip``, ``draft``, ``action``, ``outcome``).
            candidate (dict[str, Any] | None, optional): Discovery candidate metadata.
            skip_reason (str | None, optional): Why a candidate was skipped.
            draft (dict[str, Any] | None, optional): Draft payload metadata.
            action (str | None, optional): Planned or executed action name.
            url (str | None, optional): Thread or comment URL when known.
            outcome (str | None, optional): Result summary (posted, blocked, mod_removed, …).
            extra (dict[str, Any] | None, optional): Additional structured fields.

        Returns:
            dict[str, Any]: The row written to disk.

        Examples:
            >>> from pathlib import Path
            >>> import tempfile
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     log = RedditDecisionLog(Path(tmp))
            ...     row = log.append(event="skip", skip_reason="test")
            ...     row["event"]
            'skip'
        """
        row: dict[str, Any] = {
            "ts": datetime.now(tz=UTC).isoformat(),
            "event": event,
        }
        if candidate is not None:
            row["candidate"] = candidate
        if skip_reason is not None:
            row["skip_reason"] = skip_reason
        if draft is not None:
            row["draft"] = draft
        if action is not None:
            row["action"] = action
        if url is not None:
            row["url"] = url
        if outcome is not None:
            row["outcome"] = outcome
        if extra:
            row.update(extra)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def posts_today_count(self) -> int:
        """Count ``action`` events recorded for the current UTC day.

        Returns:
            int: Number of recorded actions today.

        Examples:
            >>> from pathlib import Path
            >>> import tempfile
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     log = RedditDecisionLog(Path(tmp))
            ...     log.posts_today_count()
            0
        """
        if not self.path.is_file():
            return 0
        today = datetime.now(tz=UTC).date().isoformat()
        count = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = str(row.get("ts") or "")
            if not ts.startswith(today):
                continue
            if row.get("event") == "action" and row.get("outcome") == "recorded":
                count += 1
        return count

    def seconds_since_last_post(self) -> int:
        """Return seconds since the last recorded action, or a large default.

        Returns:
            int: Seconds elapsed since the most recent action event.

        Examples:
            >>> from pathlib import Path
            >>> import tempfile
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     log = RedditDecisionLog(Path(tmp))
            ...     log.seconds_since_last_post() > 0
            True
        """
        if not self.path.is_file():
            return 999_999
        last_ts: datetime | None = None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") != "action":
                continue
            ts_raw = str(row.get("ts") or "")
            try:
                parsed = datetime.fromisoformat(ts_raw)
            except ValueError:
                continue
            if last_ts is None or parsed > last_ts:
                last_ts = parsed
        if last_ts is None:
            return 999_999
        delta = datetime.now(tz=UTC) - last_ts.astimezone(UTC)
        return max(0, int(delta.total_seconds()))


__all__ = ["RedditDecisionLog"]
