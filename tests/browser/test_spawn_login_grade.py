"""W1 RED - login-grade spawn + close/reopen contracts (DB1-DB3; green after W2)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sevn.skills.browser_session import (
    BrowserSessionRegistry,
    close_browser_session,
    resolve_browser_headless,
    write_registry,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_AUTOMATION_CONTROLLED = "--disable-blink-features=AutomationControlled"
_HYGIENE_FLAGS = (
    "--remote-allow-origins=*",
    "--no-service-autorun",
    "--homepage=about:blank",
    "--no-pings",
    "--password-store=basic",
    "--disable-infobars",
    "--disable-breakpad",
    "--disable-dev-shm-usage",
    "--disable-session-crashed-bubble",
    "--disable-search-engine-choice-screen",
    "--disable-features=IsolateOrigins,site-per-process",
)
_SINGLETON_NAMES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


class _FakeProc:
    """Minimal Popen stand-in for spawn argv capture."""

    pid = 4242

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        return None

    def wait(self, timeout: float = 0) -> None:
        _ = timeout


def _capture_spawn_args(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    extra_env: str | None = None,
) -> list[str]:
    captured: list[list[str]] = []

    def _popen(args: list[str], **_kwargs: object) -> _FakeProc:
        captured.append(list(args))
        return _FakeProc()

    monkeypatch.setattr(
        "sevn.skills.browser_session.resolve_chrome_executable",
        lambda *_a, **_k: "/usr/bin/google-chrome",
    )
    monkeypatch.setattr(
        "sevn.skills.browser_session.read_devtools_active_port",
        lambda *_a, **_k: 9333,
    )
    monkeypatch.setattr("sevn.skills.browser_session.subprocess.Popen", _popen)
    if extra_env is None:
        monkeypatch.delenv("SEVN_BROWSER_EXTRA_ARGS", raising=False)
    else:
        monkeypatch.setenv("SEVN_BROWSER_EXTRA_ARGS", extra_env)
    from sevn.skills.browser_session import spawn_chrome

    spawn_chrome(tmp_path / "profile", headless=False)
    assert captured, "spawn_chrome did not invoke Popen"
    return captured[0]


@pytest.mark.xfail(
    reason="green after W2: DB1 AutomationControlled + hygiene defaults", strict=False
)
def test_spawn_chrome_defaults_include_automation_controlled(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """DB1: every spawn includes AutomationControlled + hygiene flags."""
    args = _capture_spawn_args(tmp_path, monkeypatch)
    assert _AUTOMATION_CONTROLLED in args
    for flag in _HYGIENE_FLAGS:
        assert flag in args, f"missing hygiene flag: {flag}"


@pytest.mark.xfail(reason="green after W2: DB1 merges SEVN_BROWSER_EXTRA_ARGS", strict=False)
def test_spawn_chrome_merges_extra_args_with_defaults(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """DB1: SEVN_BROWSER_EXTRA_ARGS still merge alongside baked defaults."""
    args = _capture_spawn_args(
        tmp_path,
        monkeypatch,
        extra_env="--no-sandbox --custom-flag=1",
    )
    assert _AUTOMATION_CONTROLLED in args
    assert "--no-sandbox" in args
    assert "--custom-flag=1" in args


def _seed_profile_locks(profile: Path) -> None:
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "DevToolsActivePort").write_text("9999\n/devtools/browser/x\n", encoding="utf-8")
    for name in _SINGLETON_NAMES:
        (profile / name).write_text("lock", encoding="utf-8")


@pytest.mark.xfail(
    reason="green after W2: DB2 close clears DevToolsActivePort/Singleton* for sevn profile",
    strict=False,
)
def test_close_browser_session_clears_profile_locks_for_sevn_pid(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """DB2 + convention 11: sevn-spawned close deletes stale port/singleton files."""
    profile = tmp_path / "profiles" / "sevn"
    _seed_profile_locks(profile)
    write_registry(
        tmp_path,
        "sevn",
        BrowserSessionRegistry(
            pid=os.getpid(),
            cdp_url="http://127.0.0.1:9999",
            cdp_port=9999,
            profile_dir=str(profile),
            headless=False,
            spawned_by_sevn=True,
            last_used_at=datetime.now(tz=UTC).isoformat(),
        ),
    )
    monkeypatch.setattr("sevn.skills.browser_session._kill_pid", lambda _pid: True)
    monkeypatch.delenv("SEVN_CDP_URL", raising=False)
    result = close_browser_session(tmp_path, "sevn")
    assert result.ok is True
    assert not (profile / "DevToolsActivePort").exists()
    for name in _SINGLETON_NAMES:
        assert not (profile / name).exists(), f"{name} should be cleared"


@pytest.mark.xfail(
    reason="green after W2: DB2 foreign profile locks left untouched",
    strict=False,
)
def test_close_browser_session_leaves_foreign_profile_locks(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """DB2 + convention 11: foreign PID/profile locks are not touched."""
    sevn_profile = tmp_path / "profiles" / "sevn"
    foreign_profile = tmp_path / "profiles" / "foreign"
    _seed_profile_locks(sevn_profile)
    _seed_profile_locks(foreign_profile)
    write_registry(
        tmp_path,
        "sevn",
        BrowserSessionRegistry(
            pid=os.getpid(),
            cdp_url="http://127.0.0.1:9999",
            cdp_port=9999,
            profile_dir=str(sevn_profile),
            headless=False,
            spawned_by_sevn=True,
            last_used_at=datetime.now(tz=UTC).isoformat(),
        ),
    )
    monkeypatch.setattr("sevn.skills.browser_session._kill_pid", lambda _pid: True)
    monkeypatch.delenv("SEVN_CDP_URL", raising=False)
    close_browser_session(tmp_path, "sevn")
    assert (foreign_profile / "DevToolsActivePort").is_file()
    for name in _SINGLETON_NAMES:
        assert (foreign_profile / name).is_file()


@pytest.mark.xfail(
    reason="green after W2: DB2 freshness rejects stale DevToolsActivePort", strict=False
)
def test_read_devtools_active_port_rejects_stale_mtime(tmp_path: Path) -> None:
    """DB2: a DevToolsActivePort older than spawn start is rejected (stale-port race)."""
    from sevn.skills.browser_session import read_devtools_active_port

    profile = tmp_path / "profile"
    profile.mkdir(parents=True, exist_ok=True)
    port_file = profile / "DevToolsActivePort"
    port_file.write_text("9222\n/devtools/browser/stale\n", encoding="utf-8")
    stale_mtime = time.time() - 30.0
    os.utime(port_file, (stale_mtime, stale_mtime))
    spawn_started_at = time.time() - 5.0
    # Contract: callers pass spawn start so stale files from a prior process are ignored.
    port = read_devtools_active_port(profile, timeout=0.2, spawn_started_at=spawn_started_at)
    assert port is None


@pytest.mark.xfail(
    reason="green after W2: DB2 freshness accepts fresh DevToolsActivePort", strict=False
)
def test_read_devtools_active_port_accepts_fresh_mtime(tmp_path: Path) -> None:
    """DB2: a DevToolsActivePort newer than spawn start is accepted."""
    from sevn.skills.browser_session import read_devtools_active_port

    profile = tmp_path / "profile"
    profile.mkdir(parents=True, exist_ok=True)
    spawn_started_at = time.time() - 2.0
    time.sleep(0.05)
    port_file = profile / "DevToolsActivePort"
    port_file.write_text("9333\n/devtools/browser/fresh\n", encoding="utf-8")
    port = read_devtools_active_port(profile, timeout=0.5, spawn_started_at=spawn_started_at)
    assert port == 9333


@pytest.mark.xfail(reason="green after W2: DB3 headed default on host-with-Chrome", strict=False)
def test_resolve_browser_headless_false_when_chrome_present(monkeypatch: MonkeyPatch) -> None:
    """DB3: host with Chrome stays headed (headless=False) when env/config unset."""
    monkeypatch.delenv("SEVN_BROWSER_HEADLESS", raising=False)
    monkeypatch.setattr(
        "sevn.skills.browser_session.resolve_chrome_executable",
        lambda *_a, **_k: "/usr/bin/google-chrome",
    )
    assert resolve_browser_headless(None) is False
