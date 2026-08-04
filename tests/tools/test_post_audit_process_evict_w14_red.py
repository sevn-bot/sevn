"""Batch D W14 RED — process eviction SIGKILL escalation (#175; green after W15).

Contracts: ``_dispose_job_async`` and LRU eviction must escalate SIGTERM → SIGKILL
for children that ignore SIGTERM, matching ``_stop_job`` (``process.py:528-544``).
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from pathlib import Path
from unittest.mock import patch

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


async def _spawn_sigterm_ignorer() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        _SIGTERM_IGNORER_SCRIPT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )


async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
        await asyncio.wait_for(proc.wait(), timeout=2.0)


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W15: dispose_job_async SIGKILL escalation", strict=False)
async def test_dispose_job_async_sigkill_when_child_ignores_sigterm() -> None:
    """W14.1: ``_dispose_job_async`` must SIGKILL a SIGTERM-ignoring process group."""
    killpg_calls: list[tuple[int, int]] = []

    def _record_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append((pgid, sig))
        import os

        os.killpg(pgid, sig)

    proc = await _spawn_sigterm_ignorer()
    assert proc.pid is not None
    job = BackgroundJob(
        job_id="evict-dispose",
        command=[sys.executable, "-c", _SIGTERM_IGNORER_SCRIPT],
        cwd=Path("."),
        proc=proc,
    )

    try:
        with (
            patch("sevn.tools.process._STOP_GRACE_S", 0.05),
            patch("sevn.tools.process.os.killpg", side_effect=_record_killpg),
        ):
            await _dispose_job_async(job)

        assert any(sig == signal.SIGKILL for _pgid, sig in killpg_calls), (
            "expected SIGKILL after SIGTERM grace, matching _stop_job"
        )
        assert proc.returncode is not None or proc.poll() is not None
    finally:
        await _kill_proc(proc)


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W15: LRU eviction SIGKILL escalation", strict=False)
async def test_lru_eviction_kills_sigterm_ignoring_running_child(ctx: ToolContext) -> None:
    """W14.1: LRU eviction must not leave a SIGTERM-ignoring child running after pop."""
    procs: list[asyncio.subprocess.Process] = []
    try:
        for index in range(3):
            proc = await _spawn_sigterm_ignorer()
            procs.append(proc)
            _session_jobs(ctx.session_id)[f"job-{index}"] = BackgroundJob(
                job_id=f"job-{index}",
                command=[sys.executable, "-c", _SIGTERM_IGNORER_SCRIPT],
                cwd=ctx.workspace_path,
                proc=proc,
                created_at=float(index),
            )

        with (
            patch("sevn.tools.process.MAX_JOBS_PER_SESSION", 2),
            patch("sevn.tools.process._STOP_GRACE_S", 0.05),
        ):
            _reap_stale_jobs(ctx.session_id)
            if _background_reap_tasks:
                await asyncio.gather(*list(_background_reap_tasks), return_exceptions=True)

        evicted_pid = procs[0].pid
        assert evicted_pid is not None
        import os

        with pytest.raises(ProcessLookupError):
            os.kill(evicted_pid, 0)

        jobs = _session_jobs(ctx.session_id)
        assert len(jobs) <= 2
    finally:
        for proc in procs:
            await _kill_proc(proc)
