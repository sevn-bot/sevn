"""Op log retention (D11). Green after W3."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.xfail(strict=False, reason="green after W3")


async def _oplog(tmp_path: Path) -> object:
    from sevn.store.db import upgrade
    from sevn.store.oplog import OpLog

    url = f"sqlite+aiosqlite:///{tmp_path / 'sevn.db'}"
    await upgrade(url)
    return OpLog(url)


async def test_oplog_returns_first_result(tmp_path: Path) -> None:
    log = await _oplog(tmp_path)
    await log.record("op1", "system.ping", {"seq": 1})  # type: ignore[attr-defined]
    found = await log.lookup("op1")  # type: ignore[attr-defined]
    assert found.method == "system.ping"
    assert found.result == {"seq": 1}


async def test_oplog_expires_after_24h(tmp_path: Path) -> None:
    from freezegun import freeze_time

    log = await _oplog(tmp_path)
    with freeze_time("2026-01-01T00:00:00+00:00", tick=False):
        await log.record("op1", "system.ping", {"seq": 1})  # type: ignore[attr-defined]
    with freeze_time("2026-01-01T23:59:00+00:00", tick=False):
        await log.prune()  # type: ignore[attr-defined]
        found = await log.lookup("op1")  # type: ignore[attr-defined]
        assert found is not None
        assert found.result == {"seq": 1}
    with freeze_time("2026-01-02T00:00:01+00:00", tick=False):
        await log.prune()  # type: ignore[attr-defined]
        assert await log.lookup("op1") is None  # type: ignore[attr-defined]
