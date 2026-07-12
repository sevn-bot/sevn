"""Tests for gateway boot/cron registry (CW-2)."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.boot_registry import (
    BootContext,
    clear_boot_registry,
    register_boot_hook,
    register_cron_job,
    run_boot_hooks,
    run_cron_reconciles,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    from sevn.gateway import boot_registry as br

    saved_hooks = list(br._BOOT_HOOKS)
    saved_jobs = list(br._CRON_JOBS)
    clear_boot_registry()
    yield
    clear_boot_registry()
    br._BOOT_HOOKS.extend(saved_hooks)
    br._CRON_JOBS.extend(saved_jobs)


def test_builtin_cron_jobs_registered() -> None:
    from sevn.gateway import boot_registry as br
    from sevn.gateway.boot_registry import _register_builtin_cron_jobs

    _register_builtin_cron_jobs()
    names = {entry[1] for entry in br._CRON_JOBS}
    assert {"dreaming", "my_sevn_sync", "my_sevn_issues_sync"}.issubset(names)


@pytest.mark.asyncio
async def test_run_boot_hooks_priority_and_isolation() -> None:
    order: list[str] = []

    async def first(_ctx: BootContext) -> None:
        order.append("first")

    async def fail(_ctx: BootContext) -> None:
        msg = "boot fail"
        raise RuntimeError(msg)

    async def last(_ctx: BootContext) -> None:
        order.append("last")

    register_boot_hook("fail", fail, priority=5)
    register_boot_hook("first", first, priority=0)
    register_boot_hook("last", last, priority=10)

    ctx = BootContext(
        app=MagicMock(),
        workspace=WorkspaceConfig.minimal(),
        layout=MagicMock(),
        conn=sqlite3.connect(":memory:"),
        trace=MagicMock(),
        gateway_router=MagicMock(),
        process_settings=None,
        content_root=MagicMock(),
    )
    await run_boot_hooks(ctx)
    assert order == ["first", "last"]


def test_run_cron_reconciles_calls_registered_hook() -> None:
    called: list[str] = []

    def hook(conn: sqlite3.Connection, ws: WorkspaceConfig) -> None:
        _ = conn, ws
        called.append("cron")

    register_cron_job("test", hook)
    conn = sqlite3.connect(":memory:")
    run_cron_reconciles(conn, WorkspaceConfig.minimal())
    assert called == ["cron"]
