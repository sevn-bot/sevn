"""Stale operator lock TTL recovery (`specs/23-cli.md` §4.3)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from sevn.cli.operator_lock import (
    STALE_LOCK_TTL_SECONDS,
    lock_file_age_seconds,
    operator_lock,
    operator_lock_path,
)


def test_stale_lock_cleared_when_holder_pid_dead(tmp_path: Path) -> None:
    """Dead PID in lock file allows the next acquirer to proceed."""
    home = tmp_path / "home"
    home.mkdir()
    lock_path = operator_lock_path(home)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("999999\n", encoding="utf-8")
    stale_ts = time.time() - STALE_LOCK_TTL_SECONDS - 60
    os.utime(lock_path, (stale_ts, stale_ts))
    assert lock_file_age_seconds(lock_path) > STALE_LOCK_TTL_SECONDS
    with operator_lock(home):
        assert lock_path.read_text(encoding="utf-8").strip() == str(os.getpid())
