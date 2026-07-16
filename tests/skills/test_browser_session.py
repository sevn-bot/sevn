"""Unit tests for ``sevn.skills.browser_session`` (Wave W1)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.skills.browser_session import (
    EXTERNAL_CDP,
    BrowserSessionRegistry,
    browser_autoclose_enabled,
    cdp_port_seed,
    clear_registry,
    close_browser_session,
    merge_browser_proc_env,
    read_registry,
    registry_path,
    resolve_cdp_url,
    resolve_profile_dir,
    session_status_payload,
    write_registry,
)


def test_resolve_profile_session_scoped(tmp_path: Path) -> None:
    """Profile directories are scoped per session id under content root (D1)."""
    session_a = resolve_profile_dir(tmp_path, "conv-a", cfg=None)
    session_b = resolve_profile_dir(tmp_path, "conv-b", cfg=None)
    default = resolve_profile_dir(tmp_path, "", cfg=None)
    assert session_a == (tmp_path / ".sevn" / "browser-profiles" / "conv-a").resolve()
    assert session_b == (tmp_path / ".sevn" / "browser-profiles" / "conv-b").resolve()
    assert default == (tmp_path / ".sevn" / "browser-profiles" / "default").resolve()
    assert session_a != session_b


def test_resolve_cdp_port_deterministic() -> None:
    """CDP seed port is stable and within the 9300..9399 hint range (D2)."""
    first = cdp_port_seed("gateway-session-42")
    second = cdp_port_seed("gateway-session-42")
    other = cdp_port_seed("other-session")
    assert first == second
    assert 9300 <= first <= 9399
    assert first != other or "other-session" == "gateway-session-42"


def test_registry_write_read_clear(tmp_path: Path) -> None:
    """Registry JSON round-trips via atomic write and clear removes the file (D3)."""
    row = BrowserSessionRegistry(
        pid=4242,
        cdp_url="http://127.0.0.1:9342",
        cdp_port=9342,
        profile_dir=str(tmp_path / "profiles" / "s1"),
        headless=False,
        spawned_by_sevn=True,
        last_used_at=datetime.now(tz=UTC).isoformat(),
        active_target_id="page-guid-1",
    )
    write_registry(tmp_path, "s1", row)
    path = registry_path(tmp_path, "s1")
    assert path.is_file()
    loaded = read_registry(tmp_path, "s1")
    assert loaded is not None
    assert loaded.pid == 4242
    assert loaded.cdp_url == "http://127.0.0.1:9342"
    assert loaded.active_target_id == "page-guid-1"
    clear_registry(tmp_path, "s1")
    assert read_registry(tmp_path, "s1") is None


def test_close_browser_skips_external_cdp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Close returns EXTERNAL_CDP for attach-only sessions unless force=True (D6)."""
    row = BrowserSessionRegistry(
        pid=99999,
        cdp_url="http://127.0.0.1:9222",
        cdp_port=9222,
        profile_dir=str(tmp_path / "profiles" / "ext"),
        headless=False,
        spawned_by_sevn=False,
        last_used_at=datetime.now(tz=UTC).isoformat(),
    )
    write_registry(tmp_path, "ext", row)
    result = close_browser_session(tmp_path, "ext")
    assert result.ok is False
    assert result.code == EXTERNAL_CDP
    assert read_registry(tmp_path, "ext") is not None

    forced = close_browser_session(tmp_path, "ext", force=True)
    assert forced.code in {"CLOSED", "ALREADY_DEAD"}
    assert read_registry(tmp_path, "ext") is None

    monkeypatch.setenv("SEVN_CDP_URL", "http://127.0.0.1:9222")
    write_registry(
        tmp_path,
        "op",
        BrowserSessionRegistry(
            pid=88888,
            cdp_url="http://127.0.0.1:9222",
            cdp_port=9222,
            profile_dir=str(tmp_path / "profiles" / "op"),
            headless=False,
            spawned_by_sevn=True,
            last_used_at=datetime.now(tz=UTC).isoformat(),
        ),
    )
    op_result = close_browser_session(tmp_path, "op")
    assert op_result.code == EXTERNAL_CDP


def test_browser_autoclose_default_respected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Browser skills default to keep-alive via merge_browser_proc_env (D4)."""
    env: dict[str, str] = {}
    merge_browser_proc_env(
        env,
        content_root=tmp_path,
        session_id="s1",
        cfg=None,
        skill_name="playwright-browser",
    )
    assert env.get("SEVN_BROWSER_AUTOCLOSE") == "0"
    assert env.get("SEVN_CONTENT_ROOT") == str(tmp_path.resolve())
    assert "SEVN_BROWSER_PROFILE_DIR" in env
    assert env["SEVN_BROWSER_PROFILE_DIR"].endswith("browser-profiles/s1")

    monkeypatch.setenv("SEVN_BROWSER_AUTOCLOSE", "0")
    assert browser_autoclose_enabled() is False
    monkeypatch.setenv("SEVN_BROWSER_AUTOCLOSE", "1")
    assert browser_autoclose_enabled() is True

    env2: dict[str, str] = {"SEVN_BROWSER_AUTOCLOSE": "1"}
    merge_browser_proc_env(
        env2,
        content_root=tmp_path,
        session_id="s1",
        cfg=None,
        skill_name="playwright-browser",
    )
    assert env2["SEVN_BROWSER_AUTOCLOSE"] == "1"


def test_resolve_cdp_url_prefers_registry(tmp_path: Path) -> None:
    """Registry cdp_url is used when operator override is absent."""
    seed_url = resolve_cdp_url(tmp_path, "sess-x", cfg=None)
    assert seed_url.startswith("http://127.0.0.1:")
    row = BrowserSessionRegistry(
        pid=1,
        cdp_url="http://127.0.0.1:9400",
        cdp_port=9400,
        profile_dir="/tmp/p",
        headless=False,
        spawned_by_sevn=True,
        last_used_at=datetime.now(tz=UTC).isoformat(),
    )
    write_registry(tmp_path, "sess-x", row)
    assert resolve_cdp_url(tmp_path, "sess-x", cfg=None) == "http://127.0.0.1:9400"


def test_resolve_profile_config_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Profile resolution honours env then skills.browser.profile_dir."""
    custom = tmp_path / "cfg-profile"
    custom.mkdir()
    cfg = WorkspaceConfig(
        schema_version=1,
        skills={"browser": {"profile_dir": str(custom)}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert resolve_profile_dir(tmp_path, "s1", cfg=cfg) == custom.resolve()

    monkeypatch.setenv("SEVN_BROWSER_PROFILE_DIR", str(tmp_path / "env-profile"))
    assert resolve_profile_dir(tmp_path, "s1", cfg=cfg) == (tmp_path / "env-profile").resolve()


def test_merge_browser_proc_env_ignores_non_browser_skill(tmp_path: Path) -> None:
    """Non-browser skills do not receive browser env injection."""
    env: dict[str, str] = {}
    merge_browser_proc_env(
        env,
        content_root=tmp_path,
        session_id="s1",
        cfg=None,
        skill_name="pdf",
    )
    assert "SEVN_CONTENT_ROOT" not in env


def test_merge_browser_proc_env_injects_content_root(tmp_path: Path) -> None:
    """Browser skills receive content root and session-scoped profile on shadow runs."""
    env: dict[str, str] = {}
    merge_browser_proc_env(
        env,
        content_root=tmp_path,
        session_id="sess-scoped",
        cfg=None,
        skill_name="playwright-browser",
    )
    assert env.get("SEVN_CONTENT_ROOT") == str(tmp_path.resolve())
    assert env.get("SEVN_BROWSER_AUTOCLOSE") == "0"
    assert env.get("SEVN_SESSION_ID") == "sess-scoped"
    profile = env.get("SEVN_BROWSER_PROFILE_DIR", "")
    assert "sess-scoped" in profile
    assert "SEVN_CDP_URL" not in env


def test_merge_browser_proc_env_does_not_inject_seed_cdp(tmp_path: Path) -> None:
    """Fresh sessions must not receive a seed-hint SEVN_CDP_URL (blocks Chrome spawn)."""
    env: dict[str, str] = {}
    merge_browser_proc_env(
        env,
        content_root=tmp_path,
        session_id="fresh-session",
        cfg=None,
        skill_name="playwright-browser",
    )
    assert "SEVN_CDP_URL" not in env


def test_merge_browser_proc_env_preserves_operator_cdp(tmp_path: Path) -> None:
    """Operator attach URLs in env are left unchanged by merge_browser_proc_env."""
    operator_url = "http://127.0.0.1:9222"
    env: dict[str, str] = {"SEVN_CDP_URL": operator_url}
    merge_browser_proc_env(
        env,
        content_root=tmp_path,
        session_id="attach-session",
        cfg=None,
        skill_name="playwright-browser",
    )
    assert env["SEVN_CDP_URL"] == operator_url


def test_session_status_seed_hint_without_registry(tmp_path: Path) -> None:
    """Seed-hint CDP URLs are flagged separately from operator_cdp_override."""
    payload = session_status_payload(content_root=tmp_path, session_id="s1", cfg=None)
    assert payload["cdp_url_is_seed_hint"] is True
    assert payload["operator_cdp_override"] is False


def test_session_status_not_seed_hint_with_registry(tmp_path: Path) -> None:
    """Registry rows with cdp_url are not reported as seed hints."""
    write_registry(
        tmp_path,
        "s1",
        BrowserSessionRegistry(
            pid=1,
            cdp_url="http://127.0.0.1:9400",
            cdp_port=9400,
            profile_dir="/tmp/p",
            headless=False,
            spawned_by_sevn=True,
            last_used_at=datetime.now(tz=UTC).isoformat(),
        ),
    )
    payload = session_status_payload(content_root=tmp_path, session_id="s1", cfg=None)
    assert payload["cdp_url_is_seed_hint"] is False


@pytest.mark.asyncio
async def test_session_browser_resources_spawns_without_env_cdp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh session without SEVN_CDP_URL env spawns Chrome instead of attach-only fail."""
    monkeypatch.delenv("SEVN_CDP_URL", raising=False)
    spawn_calls: list[tuple[Path, bool, int | None]] = []
    reachable_urls: set[str] = set()

    class FakeProc:
        pid = 12345

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float = 0) -> None:
            pass

    def fake_spawn(
        profile_dir: Path,
        *,
        headless: bool = False,
        seed_port: int | None = None,
        cfg: WorkspaceConfig | None = None,
        session_id: str | None = None,
        log_dir: Path | None = None,
    ) -> tuple[FakeProc, int, str]:
        _ = (cfg, session_id, log_dir)
        spawn_calls.append((profile_dir, headless, seed_port))
        port = seed_port or 9333
        url = f"http://127.0.0.1:{port}"
        reachable_urls.add(url)
        return FakeProc(), port, url

    def fake_reachable(url: str, *, timeout: float = 2.0) -> bool:
        return url.rstrip("/") in reachable_urls

    mock_browser = MagicMock()
    mock_playwright = MagicMock()
    mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    mock_pw_factory = MagicMock()
    mock_pw_factory.start = AsyncMock(return_value=mock_playwright)

    monkeypatch.setattr("sevn.skills.browser_session.spawn_chrome", fake_spawn)
    monkeypatch.setattr("sevn.skills.browser_session.cdp_reachable", fake_reachable)
    monkeypatch.setattr(
        "sevn.skills.browser_session.resolve_chrome_executable",
        lambda *_a, **_k: "/fake/chrome",
    )
    monkeypatch.setattr(
        "playwright.async_api.async_playwright",
        lambda: mock_pw_factory,
    )

    from sevn.skills.browser_session import _session_browser_resources

    (
        _playwright,
        browser,
        _persistent_context,
        _chrome_proc,
        _launched_headless_fallback,
        we_spawned_chrome,
        sid,
        registry_row,
        _profile_dir,
        _headless,
    ) = await _session_browser_resources(
        content_root=tmp_path,
        session_id="sess-spawn",
        cfg=None,
        headless_fallback=False,
    )

    assert len(spawn_calls) == 1
    assert we_spawned_chrome is True
    assert browser is mock_browser
    assert sid == "sess-spawn"
    assert registry_row is not None
    assert registry_row.spawned_by_sevn is True
    assert registry_row.cdp_url.startswith("http://127.0.0.1:")


def test_resolve_chrome_executable_env_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEVN_CHROME_EXECUTABLE takes precedence over discovery."""
    exe = tmp_path / "custom-brave"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("SEVN_CHROME_EXECUTABLE", str(exe))
    monkeypatch.setattr(
        "sevn.skills.browser_session.shutil.which", lambda _n: "/usr/bin/google-chrome-stable"
    )
    from sevn.skills.browser_session import resolve_chrome_executable

    assert resolve_chrome_executable() == str(exe)


def test_resolve_chrome_executable_brave_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Brave resolves from PATH when engine is brave."""
    monkeypatch.delenv("SEVN_CHROME_EXECUTABLE", raising=False)
    monkeypatch.setenv("SEVN_BROWSER_ENGINE", "brave")

    def _which(name: str) -> str | None:
        if name == "brave-browser":
            return "/usr/bin/brave-browser"
        return None

    monkeypatch.setattr("sevn.skills.browser_session.shutil.which", _which)
    from sevn.skills.browser_session import is_brave_executable, resolve_chrome_executable

    resolved = resolve_chrome_executable()
    assert resolved == "/usr/bin/brave-browser"
    assert is_brave_executable(resolved)


def test_resolve_chrome_executable_auto_prefers_chrome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto engine prefers Chrome/Chromium before Brave."""
    monkeypatch.delenv("SEVN_CHROME_EXECUTABLE", raising=False)
    monkeypatch.delenv("SEVN_BROWSER_ENGINE", raising=False)

    def _which(name: str) -> str | None:
        if name == "google-chrome-stable":
            return "/usr/bin/google-chrome-stable"
        if name == "brave-browser":
            return "/usr/bin/brave-browser"
        return None

    monkeypatch.setattr(
        "sevn.skills.browser_session._first_existing_file",
        lambda _candidates: None,
    )
    monkeypatch.setattr("sevn.skills.browser_session.shutil.which", _which)
    from sevn.skills.browser_session import resolve_chrome_executable

    assert resolve_chrome_executable() == "/usr/bin/google-chrome-stable"


def test_resolve_browser_engine_from_config() -> None:
    """skills.browser.engine is honored when env is unset."""
    cfg = WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "gateway": {"token": "test-token"},
            "skills": {"browser": {"engine": "brave"}},
        },
    )
    from sevn.skills.browser_session import resolve_browser_engine

    assert resolve_browser_engine(cfg) == "brave"


def test_spawn_chrome_appends_extra_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEVN_BROWSER_EXTRA_ARGS are appended to the spawn argv."""
    captured: list[list[str]] = []

    class _Proc:
        pid = 1234

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float = 0) -> None:
            pass

    def _popen(args: list[str], **_kwargs: object) -> _Proc:
        captured.append(args)
        return _Proc()

    monkeypatch.setenv("SEVN_BROWSER_EXTRA_ARGS", "--no-sandbox --disable-dev-shm-usage")
    monkeypatch.setattr(
        "sevn.skills.browser_session.resolve_chrome_executable",
        lambda *_a, **_k: "/usr/bin/brave-browser",
    )
    monkeypatch.setattr(
        "sevn.skills.browser_session.read_devtools_active_port",
        lambda *_a, **_k: 9333,
    )
    monkeypatch.setattr("sevn.skills.browser_session.subprocess.Popen", _popen)
    from sevn.skills.browser_session import spawn_chrome

    spawn_chrome(tmp_path / "profile", headless=True)
    assert captured
    assert "--no-sandbox" in captured[0]
    assert "--disable-dev-shm-usage" in captured[0]
    assert "--headless=new" in captured[0]


@pytest.mark.asyncio
async def test_headless_fallback_uses_executable_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Playwright tier-3 fallback honors SEVN_CHROME_EXECUTABLE."""
    launch_kwargs: dict[str, object] = {}

    class _FakeProc:
        pid = 1

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float = 0) -> None:
            pass

    async def _launch_persistent_context(profile: str, **kwargs: object) -> MagicMock:
        launch_kwargs.update(kwargs)
        return MagicMock()

    mock_playwright = MagicMock()
    mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=None)
    mock_playwright.chromium.launch_persistent_context = _launch_persistent_context
    mock_pw_factory = MagicMock()
    mock_pw_factory.start = AsyncMock(return_value=mock_playwright)

    brave = tmp_path / "brave-bin"
    brave.write_text("", encoding="utf-8")
    monkeypatch.setenv("SEVN_CHROME_EXECUTABLE", str(brave))
    monkeypatch.setattr(
        "sevn.skills.browser_session.resolve_chrome_executable",
        lambda *_a, **_k: str(brave),
    )
    monkeypatch.setattr(
        "sevn.skills.browser_session.spawn_chrome",
        lambda *_a, **_k: (_FakeProc(), 9333, "http://127.0.0.1:9333"),
    )
    monkeypatch.setattr("sevn.skills.browser_session.cdp_reachable", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "playwright.async_api.async_playwright",
        lambda: mock_pw_factory,
    )

    from sevn.skills.browser_session import _session_browser_resources

    await _session_browser_resources(
        content_root=tmp_path,
        session_id="fb",
        cfg=None,
        headless_fallback=True,
    )
    assert launch_kwargs.get("executable_path") == str(brave)


def test_spawn_chrome_respects_engine_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spawn_chrome honors skills.browser.engine via cfg."""
    captured: list[list[str]] = []

    class _Proc:
        pid = 1

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float = 0) -> None:
            pass

    def _which(name: str) -> str | None:
        if name == "brave-browser":
            return "/usr/bin/brave-browser"
        return None

    monkeypatch.setattr("sevn.skills.browser_session.shutil.which", _which)
    monkeypatch.setattr(
        "sevn.skills.browser_session.read_devtools_active_port",
        lambda *_a, **_k: 9333,
    )
    monkeypatch.setattr(
        "sevn.skills.browser_session.subprocess.Popen",
        lambda args, **_kwargs: captured.append(args) or _Proc(),
    )
    cfg = WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "gateway": {"token": "test-token"},
            "skills": {"browser": {"engine": "brave"}},
        },
    )
    from sevn.skills.browser_session import spawn_chrome

    spawn_chrome(tmp_path / "profile", headless=True, cfg=cfg)
    assert captured[0][0] == "/usr/bin/brave-browser"


@pytest.mark.asyncio
async def test_headless_fallback_appends_extra_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Playwright tier-3 fallback forwards SEVN_BROWSER_EXTRA_ARGS."""
    launch_kwargs: dict[str, object] = {}

    class _FakeProc:
        pid = 1

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float = 0) -> None:
            pass

    async def _launch_persistent_context(profile: str, **kwargs: object) -> MagicMock:
        launch_kwargs.update(kwargs)
        return MagicMock()

    mock_playwright = MagicMock()
    mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=None)
    mock_playwright.chromium.launch_persistent_context = _launch_persistent_context
    mock_pw_factory = MagicMock()
    mock_pw_factory.start = AsyncMock(return_value=mock_playwright)

    brave = tmp_path / "brave-bin"
    brave.write_text("", encoding="utf-8")
    monkeypatch.setenv("SEVN_BROWSER_EXTRA_ARGS", "--no-sandbox")
    monkeypatch.setattr(
        "sevn.skills.browser_session.resolve_chrome_executable",
        lambda *_a, **_k: str(brave),
    )
    monkeypatch.setattr(
        "sevn.skills.browser_session.spawn_chrome",
        lambda *_a, **_k: (_FakeProc(), 9333, "http://127.0.0.1:9333"),
    )
    monkeypatch.setattr("sevn.skills.browser_session.cdp_reachable", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "playwright.async_api.async_playwright",
        lambda: mock_pw_factory,
    )

    from sevn.skills.browser_session import _session_browser_resources

    await _session_browser_resources(
        content_root=tmp_path,
        session_id="fb-args",
        cfg=None,
        headless_fallback=True,
    )
    assert launch_kwargs.get("args") == ["--no-sandbox"]


def test_resolve_browser_headless_env_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEVN_BROWSER_HEADLESS wins over skills.browser.headless when set."""
    monkeypatch.setenv("SEVN_BROWSER_HEADLESS", "0")
    monkeypatch.setattr(
        "sevn.skills.browser_session.resolve_chrome_executable",
        lambda *_a, **_k: "/usr/bin/brave-browser",
    )
    cfg = WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "gateway": {"token": "test-token"},
            "skills": {"browser": {"headless": True}},
        },
    )
    from sevn.skills.browser_session import resolve_browser_headless

    assert resolve_browser_headless(cfg) is False
