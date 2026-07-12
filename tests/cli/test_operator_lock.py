"""Advisory operator lock (`specs/23-cli.md` §4.3)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sevn.cli.operator_lock import OperatorLockHeld, operator_lock

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_operator_lock_blocks_second_process(tmp_path: Path) -> None:
    """A second process cannot take the advisory lock while the first holds it."""
    home = tmp_path / "h"
    home.mkdir()
    hp = str(home.resolve())
    ready = tmp_path / "lock-subproc-ready"
    hp_ready = str(ready.resolve())
    script = (
        "import time\n"
        "from pathlib import Path\n"
        "from sevn.cli.operator_lock import operator_lock\n"
        f"ready = Path({hp_ready!r})\n"
        f"with operator_lock(Path({hp!r})):\n"
        "    ready.write_text('ok')\n"
        "    time.sleep(30)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 15.0
    while not ready.exists():
        if time.monotonic() > deadline:
            err = proc.stderr.read() if proc.stderr else ""
            msg = f"subprocess never acquired lock or wrote ready file (poll={proc.poll()}): {err}"
            raise AssertionError(msg)
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            msg = f"subprocess exited before ready (code={proc.returncode}): {err}"
            raise AssertionError(msg)
        time.sleep(0.05)
    assert proc.poll() is None, proc.stderr.read() if proc.stderr else ""
    try:
        with pytest.raises(OperatorLockHeld):  # noqa: SIM117
            with operator_lock(home):
                pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
