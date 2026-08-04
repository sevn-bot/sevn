"""Batch D W14 RED — process eviction SIGKILL escalation (#175; green after W15).

Contracts: ``_dispose_job_async`` and LRU eviction must escalate SIGTERM → SIGKILL
for children that ignore SIGTERM, matching ``_stop_job`` (``process.py:528-544``).
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.process import (
    BackgroundJob,
    _background_reap_tasks,
    _dispose_job_async,
    _reap_stale_jobs,
    _session_jobs,
    reset_process_store_for_tests,
)

_SIGTERM_IGNORER_SCRIPT = (
    "import signal,time;"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
    "print('alive', flush=True);"
    "time.sleep(3600)"
)


class _SandboxWiringStub:
    """Minimal ``sandbox_client`` for host-backed tool tests."""


@pytest.fixture(autouse=True)
def _clean_process_store() -> None:
    reset_process_store_for_tests()
    yield
    reset_process_store_for_tests()


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    root = tmp_path / "ws"
    root.mkdir()
    return ToolContext(
        session_id="post-audit-process-evict",
        workspace_path=root,
        workspace_id="post-audit-process-evict-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        sandbox_client=_SandboxWiringStub(),
    )


def _running_job(
    *,
    job_id: str,
    proc: MagicMock,
    created_at: float,
) -> BackgroundJob:
    return BackgroundJob(
        job_id=job_id,
        command=[sys.executable, "-c", _SIGTERM_IGNORER_SCRIPT],
        cwd=Path("."),
        proc=proc,
        created_at=created_at,
    )


def _sigterm_ignoring_proc(*, pid: int) -> MagicMock:
    wait_calls = 0

    async def _wait() -> int:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            await asyncio.sleep(3600)
        return -9

    proc = MagicMock()
    proc.pid = pid
    proc.returncode = None
    proc.wait = _wait
    return proc


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W15: dispose_job_async SIGKILL escalation", strict=False)
async def test_dispose_job_async_sigkill_when_child_ignores_sigterm() -> None:
    """W14.1: ``_dispose_job_async`` must SIGKILL a SIGTERM-ignoring process group."""
    killpg_calls: list[tuple[int, int]] = []

    def _record_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append((pgid, sig))

    proc = _sigterm_ignoring_proc(pid=5150)
    job = _running_job(job_id="evict-dispose", proc=proc, created_at=0.0)

    with (
        patch("sevn.tools.process._STOP_GRACE_S", 0.05),
        patch("sevn.tools.process.os.getpgid", return_value=5150),
        patch("sevn.tools.process.os.killpg", side_effect=_record_killpg),
    ):
        await _dispose_job_async(job)

    assert any(sig == signal.SIGKILL for _pgid, sig in killpg_calls), (
        "expected SIGKILL after SIGTERM grace, matching _stop_job"
    )


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W15: LRU eviction SIGKILL escalation", strict=False)
async def test_lru_eviction_kills_sigterm_ignoring_running_child(ctx: ToolContext) -> None:
    """W14.1: LRU eviction must SIGKILL a SIGTERM-ignoring child via ``_dispose_job_async``."""
    killpg_calls: list[tuple[int, int]] = []

    def _record_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append((pgid, sig))

    evicted_proc = _sigterm_ignoring_proc(pid=4242)
    jobs = _session_jobs(ctx.session_id)
    jobs["job-0"] = _running_job(job_id="job-0", proc=evicted_proc, created_at=0.0)
    jobs["job-1"] = _running_job(
        job_id="job-1",
        proc=_sigterm_ignoring_proc(pid=4243),
        created_at=1.0,
    )
    jobs["job-2"] = _running_job(
        job_id="job-2",
        proc=_sigterm_ignoring_proc(pid=4244),
        created_at=2.0,
    )

    with (
        patch("sevn.tools.process.MAX_JOBS_PER_SESSION", 2),
        patch("sevn.tools.process._STOP_GRACE_S", 0.05),
        patch("sevn.tools.process.os.getpgid", return_value=4242),
        patch("sevn.tools.process.os.killpg", side_effect=_record_killpg),
    ):
        _reap_stale_jobs(ctx.session_id)
        if _background_reap_tasks:
            await asyncio.gather(*list(_background_reap_tasks), return_exceptions=True)

    assert "job-0" not in jobs
    assert any(sig == signal.SIGKILL for _pgid, sig in killpg_calls), (
        "LRU eviction must escalate to SIGKILL when SIGTERM is ignored"
    )
