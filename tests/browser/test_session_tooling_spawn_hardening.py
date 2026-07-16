"""RED suite for session-tooling CDP spawn hardening (D1-D7; green after W2).

Contracts from `.ignorelocal/waves/session-tooling-failure-fixes-wave-plan.md`.
Browser-spawn end-to-end is presence/shape (mocked Chrome); operator-observed
live spawn is deferred to W2 acceptance.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sevn.browser import lifecycle
from sevn.skills import browser_session as bs


def _profile_with_locks(profile_dir: Path, *, port: int = 52377) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "SingletonLock").write_text("lock", encoding="utf-8")
    (profile_dir / "SingletonSocket").write_text("sock", encoding="utf-8")
    (profile_dir / "SingletonCookie").write_text("cookie", encoding="utf-8")
    (profile_dir / "DevToolsActivePort").write_text(
        f"{port}\n/devtools/browser\n", encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_d1_reap_clears_locks_for_sevn_pid_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D1 + convention 11: reap sevn PID + clear locks; leave a foreign PID untouched."""
    content_root = tmp_path / "ws"
    content_root.mkdir()
    session_id = "sess-reap-1"
    profile_dir = content_root / ".sevn" / "browser-profiles" / session_id
    _profile_with_locks(profile_dir)

    sevn_pid = 424242
    foreign_pid = os.getpid()
    bs.write_registry(
        content_root,
        session_id,
        bs.BrowserSessionRegistry(
            pid=sevn_pid,
            cdp_url="",
            cdp_port=0,
            profile_dir=str(profile_dir),
            headless=True,
            spawned_by_sevn=True,
            last_used_at="2026-07-15T00:00:00+00:00",
        ),
    )

    killed: list[int] = []

    def _fake_kill(pid: int, _sig: int = 15) -> None:
        killed.append(pid)
        if pid == foreign_pid:
            raise AssertionError("must never signal operator/foreign PID")

    monkeypatch.setattr(os, "kill", _fake_kill)

    def _pid_alive(pid: int) -> bool:
        return pid == foreign_pid

    for mod in (bs, lifecycle):
        if hasattr(mod, "pid_is_alive"):
            monkeypatch.setattr(mod, "pid_is_alive", _pid_alive)

    spawn_calls: list[Path] = []

    def _fake_spawn(
        profile: Path,
        *,
        headless: bool = False,
        seed_port: int | None = None,
        cfg: object = None,
    ) -> tuple[MagicMock, int, str]:
        spawn_calls.append(profile)
        proc = MagicMock()
        proc.pid = 999001
        proc.poll.return_value = None
        return proc, 59999, "http://127.0.0.1:59999"

    monkeypatch.setattr(bs, "spawn_chrome", _fake_spawn)
    monkeypatch.setattr(bs, "cdp_reachable", lambda _url: True)
    monkeypatch.setattr(
        lifecycle.CDPBrowserSession,
        "attach",
        classmethod(lambda cls, url: MagicMock(cdp_url=url)),
    )

    await lifecycle.spawn_or_attach(content_root, session_id)

    assert not (profile_dir / "SingletonLock").exists()
    assert not (profile_dir / "SingletonSocket").exists()
    assert not (profile_dir / "SingletonCookie").exists()
    assert spawn_calls, "spawn must proceed after reap"
    assert foreign_pid not in killed


def test_d2_stale_devtools_active_port_rejected(tmp_path: Path) -> None:
    """D2: DevToolsActivePort with mtime older than spawn time is ignored."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    port_file = profile_dir / "DevToolsActivePort"
    port_file.write_text("52377\n/devtools/browser\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(port_file, (old, old))
    spawn_time = time.time()

    result = bs.read_devtools_active_port(profile_dir, spawned_after=spawn_time)  # type: ignore[call-arg]
    assert result is None


def test_d2_fresh_devtools_active_port_accepted(tmp_path: Path) -> None:
    """D2: DevToolsActivePort written after spawn time is accepted."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    spawn_time = time.time() - 1.0
    port_file = profile_dir / "DevToolsActivePort"
    port_file.write_text("59999\n/devtools/browser\n", encoding="utf-8")
    os.utime(port_file, None)

    result = bs.read_devtools_active_port(profile_dir, spawned_after=spawn_time)  # type: ignore[call-arg]
    assert result == 59999


def test_d3_adaptive_wait_ceiling_is_20_to_25s() -> None:
    """D3: spawn CDP wait ceiling rises from 10 s to ~20-25 s."""
    steps = lifecycle._SPAWN_CDP_WAIT_STEPS
    interval = lifecycle._SPAWN_CDP_WAIT_INTERVAL
    ceiling = float(steps) * float(interval)
    assert 20.0 <= ceiling <= 25.0


@pytest.mark.asyncio
async def test_d3_failed_spawn_terminates_waits_and_retries_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D3: first unreachable CDP → terminate()+wait(timeout=5) then exactly one retry."""
    monkeypatch.setattr(lifecycle, "_SPAWN_CDP_WAIT_STEPS", 2)
    monkeypatch.setattr(lifecycle, "_SPAWN_CDP_WAIT_INTERVAL", 0.01)
    content_root = tmp_path / "ws"
    content_root.mkdir()
    session_id = "sess-retry"
    (content_root / ".sevn" / "browser-profiles" / session_id).mkdir(parents=True)

    waits: list[float | None] = []
    terminate_count = 0
    spawn_count = 0

    def _fake_spawn(*_a: object, **_k: object) -> tuple[MagicMock, int, str]:
        nonlocal spawn_count, terminate_count
        spawn_count += 1
        proc = MagicMock()
        proc.pid = 888000 + spawn_count
        proc.poll.return_value = None

        def _terminate() -> None:
            nonlocal terminate_count
            terminate_count += 1

        def _wait(timeout: float | None = None) -> int:
            waits.append(timeout)
            proc.poll.return_value = -15
            return -15

        proc.terminate.side_effect = _terminate
        proc.wait.side_effect = _wait
        return proc, 50000 + spawn_count, f"http://127.0.0.1:{50000 + spawn_count}"

    monkeypatch.setattr(bs, "spawn_chrome", _fake_spawn)
    monkeypatch.setattr(bs, "cdp_reachable", lambda _url: False)
    monkeypatch.setattr(bs, "resolve_cdp_url", lambda *_a, **_k: "http://127.0.0.1:1")

    with pytest.raises(RuntimeError, match=r"NO_CDP|CDP not reachable|not reachable"):
        await lifecycle.spawn_or_attach(content_root, session_id)

    assert spawn_count == 2, "exactly one clean retry after the first failure"
    assert terminate_count >= 1
    assert any(t == 5 or t == 5.0 for t in waits), "terminate must be followed by wait(timeout=5)"


def test_d4_spawn_chrome_redirects_stderr_to_session_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4: Chrome stdout/stderr go to logs/chrome-<session>.log, not DEVNULL."""
    logs = tmp_path / "logs"
    logs.mkdir()
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    session_id = "abc123sess"
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, *_a: object, **kwargs: object) -> None:
            captured.update(kwargs)
            self.pid = 777001

        def poll(self) -> int | None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

    monkeypatch.setattr(bs.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(bs, "resolve_chrome_executable", lambda _cfg=None: "/usr/bin/google-chrome")
    monkeypatch.setattr(bs, "resolve_browser_extra_args", list)
    monkeypatch.setattr(bs, "read_devtools_active_port", lambda *_a, **_k: 59999)

    try:
        bs.spawn_chrome(
            profile_dir,
            headless=True,
            session_id=session_id,  # type: ignore[call-arg]
            log_dir=logs,  # type: ignore[call-arg]
        )
    except TypeError:
        bs.spawn_chrome(profile_dir, headless=True)

    stderr = captured.get("stderr")
    assert stderr is not None
    assert stderr is not bs.subprocess.DEVNULL
    log_path = logs / f"chrome-{session_id}.log"
    assert log_path.exists() or (
        hasattr(stderr, "name") and "chrome-" in str(getattr(stderr, "name", ""))
    )


@pytest.mark.asyncio
async def test_d4_no_cdp_error_includes_chrome_log_path_or_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4: NO_CDP error surfaces the chrome log path or a stderr tail."""
    content_root = tmp_path / "ws"
    content_root.mkdir()
    (content_root / "logs").mkdir()
    session_id = "sess-nocdp"
    log_path = content_root / "logs" / f"chrome-{session_id}.log"
    log_path.write_text("ERROR SingletonLock File exists (17)\n", encoding="utf-8")

    proc = MagicMock()
    proc.pid = 666001
    proc.poll.return_value = None
    proc.wait.return_value = -15

    monkeypatch.setattr(
        bs,
        "spawn_chrome",
        lambda *_a, **_k: (proc, 51111, "http://127.0.0.1:51111"),
    )
    monkeypatch.setattr(bs, "cdp_reachable", lambda _url: False)
    monkeypatch.setattr(bs, "resolve_cdp_url", lambda *_a, **_k: "http://127.0.0.1:1")

    with pytest.raises(RuntimeError) as exc_info:
        await lifecycle.spawn_or_attach(content_root, session_id)

    msg = str(exc_info.value)
    assert "NO_CDP" in msg or "not reachable" in msg.lower()
    assert "chrome-" in msg or "SingletonLock" in msg or str(log_path) in msg


@pytest.mark.asyncio
async def test_d5_concurrent_spawn_or_attach_single_flights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D5: concurrent spawn_or_attach on one session_id spawn Chrome once."""
    content_root = tmp_path / "ws"
    content_root.mkdir()
    session_id = "sess-single-flight"
    spawn_count = 0

    def _fake_spawn(*_a: object, **_k: object) -> tuple[MagicMock, int, str]:
        nonlocal spawn_count
        spawn_count += 1
        time.sleep(0.05)  # force overlap window for concurrent callers
        proc = MagicMock()
        proc.pid = 555000 + spawn_count
        proc.poll.return_value = None
        return proc, 59000, "http://127.0.0.1:59000"

    monkeypatch.setattr(bs, "spawn_chrome", _fake_spawn)
    monkeypatch.setattr(bs, "cdp_reachable", lambda _url: "59000" in _url)
    monkeypatch.setattr(bs, "resolve_cdp_url", lambda *_a, **_k: "http://127.0.0.1:1")

    async def _attach(_cls: type, url: str) -> MagicMock:
        return MagicMock(cdp_url=url)

    monkeypatch.setattr(lifecycle.CDPBrowserSession, "attach", classmethod(_attach))

    results = await asyncio.gather(
        lifecycle.spawn_or_attach(content_root, session_id),
        lifecycle.spawn_or_attach(content_root, session_id),
    )

    assert spawn_count == 1, f"expected single-flight spawn, got {spawn_count}"
    assert getattr(results[0], "cdp_url", None) == getattr(results[1], "cdp_url", None)


def test_d6_gateway_shutdown_hook_terminates_sevn_browsers(tmp_path: Path) -> None:
    """D6: shutdown hook terminate()+wait()s all sevn-spawned browsers (presence/shape)."""
    from sevn.gateway.runtime import shutdown_cleanup

    content_root = tmp_path / "ws"
    content_root.mkdir()
    session_id = "sess-shutdown"
    profile_dir = content_root / ".sevn" / "browser-profiles" / session_id
    profile_dir.mkdir(parents=True)
    bs.write_registry(
        content_root,
        session_id,
        bs.BrowserSessionRegistry(
            pid=31337,
            cdp_url="http://127.0.0.1:9333",
            cdp_port=9333,
            profile_dir=str(profile_dir),
            headless=True,
            spawned_by_sevn=True,
            last_used_at="2026-07-15T00:00:00+00:00",
        ),
    )

    reap = getattr(lifecycle, "reap_sevn_browsers_on_shutdown", None) or getattr(
        shutdown_cleanup, "reap_sevn_browsers_on_shutdown", None
    )
    assert callable(reap), "gateway shutdown must register a browser reap hook"
    result = reap(content_root)  # type: ignore[misc]
    # Shape: either returns killed PIDs, or clears the registry entry.
    if isinstance(result, list):
        assert 31337 in result
    else:
        row = bs.read_registry(content_root, session_id)
        assert row is None or row.pid is None


@pytest.mark.asyncio
async def test_d7_failed_spawn_writes_no_half_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D7: failed spawn clears/omits registry - never cdp_url:'' / pid:null half-writes."""
    content_root = tmp_path / "ws"
    content_root.mkdir()
    session_id = "sess-half"
    (content_root / ".sevn" / "browser-profiles" / session_id).mkdir(parents=True)

    proc = MagicMock()
    proc.pid = 222001
    proc.poll.return_value = None
    proc.wait.return_value = -15

    monkeypatch.setattr(
        bs, "spawn_chrome", lambda *_a, **_k: (proc, 52222, "http://127.0.0.1:52222")
    )
    monkeypatch.setattr(bs, "cdp_reachable", lambda _url: False)
    monkeypatch.setattr(bs, "resolve_cdp_url", lambda *_a, **_k: "http://127.0.0.1:1")

    with pytest.raises(RuntimeError):
        await lifecycle.spawn_or_attach(content_root, session_id)

    row = bs.read_registry(content_root, session_id)
    assert row is None or (bool(row.cdp_url) and row.pid is not None and row.cdp_port > 0)
    # Preferred contract: no registry entry after failed spawn.
    assert row is None


@pytest.mark.asyncio
async def test_d7_confirmed_spawn_persists_full_record_for_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D7: confirmed CDP write full cdp_url/pid; resolve_cdp_url reuses it."""
    content_root = tmp_path / "ws"
    content_root.mkdir()
    session_id = "sess-full"
    (content_root / ".sevn" / "browser-profiles" / session_id).mkdir(parents=True)

    proc = MagicMock()
    proc.pid = 111001
    proc.poll.return_value = None

    monkeypatch.setattr(
        bs, "spawn_chrome", lambda *_a, **_k: (proc, 59991, "http://127.0.0.1:59991")
    )
    # First resolve misses; after spawn, registry must win.
    monkeypatch.setattr(bs, "cdp_reachable", lambda url: "59991" in str(url))

    async def _attach(_cls: type, url: str) -> MagicMock:
        return MagicMock(cdp_url=url)

    monkeypatch.setattr(lifecycle.CDPBrowserSession, "attach", classmethod(_attach))

    await lifecycle.spawn_or_attach(content_root, session_id)
    row = bs.read_registry(content_root, session_id)
    assert row is not None
    assert row.cdp_url == "http://127.0.0.1:59991"
    assert row.cdp_port == 59991
    assert row.pid == 111001

    resolved = bs.resolve_cdp_url(content_root, session_id)
    assert resolved == "http://127.0.0.1:59991"
