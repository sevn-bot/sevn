"""Bundled browser skill subprocess tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.manager import SkillsManager

_PW_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "playwright-browser"
)
_BH_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "browser-harness"
)


def _run_script(
    skill_root: Path,
    rel: str,
    workspace: Path,
    cli_args: list[str] | None = None,
    *,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    """Run one skill script and parse its JSON stdout envelope."""
    script = skill_root / rel
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    env["SEVN_CDP_URL"] = "http://127.0.0.1:59999"
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(script), *(cli_args or [])],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def test_github_blob_to_raw_converts_blob_url(tmp_path: Path) -> None:
    """``github_blob_to_raw.py`` returns a raw.githubusercontent.com URL."""
    code, payload = _run_script(
        _PW_ROOT,
        "scripts/github_blob_to_raw.py",
        tmp_path,
        ["https://github.com/octocat/Hello-World/blob/master/README"],
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert (
        data.get("raw_url") == "https://raw.githubusercontent.com/octocat/Hello-World/master/README"
    )


def test_playwright_cdp_probe_unreachable(tmp_path: Path) -> None:
    """``cdp_probe.py`` returns ``CDP_UNREACHABLE`` when nothing listens."""
    code, payload = _run_script(_PW_ROOT, "scripts/cdp_probe.py", tmp_path)
    assert code == 1
    assert payload.get("ok") is False
    assert payload.get("code") == "CDP_UNREACHABLE"


def test_playwright_scripts_do_not_shadow_click_package(tmp_path: Path) -> None:
    """Regression: no ``scripts/click.py`` — PyPI ``click`` must stay importable."""
    assert not (_PW_ROOT / "scripts" / "click.py").exists()
    assert (_PW_ROOT / "scripts" / "click_element.py").is_file()
    _code, payload = _run_script(
        _PW_ROOT,
        "scripts/capture.py",
        tmp_path,
        ["https://example.com"],
    )
    message = str(payload.get("message", ""))
    assert "Choice" not in message
    assert payload.get("code") != "SCRIPT_FAILED" or "Choice" not in message


def test_playwright_screenshot_default_path_uses_artifact_prefix(tmp_path: Path) -> None:
    """``screenshot.py`` rebases output under the session artifact prefix (persists on content root)."""
    from sevn.pdf import resolve_path_under_workspace
    from sevn.security.sandbox_runtime import materialize_shadow_workspace

    content = tmp_path / "ws"
    (content / "out").mkdir(parents=True)
    shadow = tmp_path / "shadow"
    materialize_shadow_workspace(content, shadow)
    rel = "screenshots/pw-123.png"
    dest = resolve_path_under_workspace(
        shadow,
        rel,
        artifact=True,
        output_prefix="out/sess-1",
    )
    assert dest == shadow / "out" / "sess-1" / "screenshots" / "pw-123.png"
    assert dest.resolve() == (content / "out" / "sess-1" / "screenshots" / "pw-123.png").resolve()


def test_playwright_session_status_without_live_browser(tmp_path: Path) -> None:
    """``session_status.py`` returns profile + CDP metadata without spawning Chrome."""
    code, payload = _run_script(_PW_ROOT, "scripts/session_status.py", tmp_path)
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("skill_name") == "playwright-browser"
    assert data.get("cdp_reachable") is False
    assert "profile_dir" in data


def test_playwright_close_browser_refuses_external_cdp(tmp_path: Path) -> None:
    """``close_browser.py`` returns ``EXTERNAL_CDP`` when ``SEVN_CDP_URL`` is set."""
    code, payload = _run_script(_PW_ROOT, "scripts/close_browser.py", tmp_path)
    assert code == 1
    assert payload.get("ok") is False
    assert payload.get("code") == "EXTERNAL_CDP"


def test_playwright_close_browser_not_found_without_registry(tmp_path: Path) -> None:
    """``close_browser.py`` reports ``NOT_FOUND`` when no registry and no operator CDP."""
    code, payload = _run_script(
        _PW_ROOT,
        "scripts/close_browser.py",
        tmp_path,
        extra_env={"SEVN_CDP_URL": ""},
    )
    assert code == 1
    assert payload.get("ok") is False
    assert payload.get("code") == "NOT_FOUND"


def test_browser_harness_probe_unreachable(tmp_path: Path) -> None:
    """``browser-harness`` probe returns ``CDP_UNREACHABLE`` when CDP is down."""
    code, payload = _run_script(_BH_ROOT, "scripts/probe.py", tmp_path)
    assert code == 1
    assert payload.get("ok") is False
    assert payload.get("code") == "CDP_UNREACHABLE"


def test_classify_obstacles_google_sorry() -> None:
    """Obstacle heuristics flag Google sorry pages without Playwright."""
    sys.path.insert(0, str(_PW_ROOT / "scripts" / "_lib"))
    from _page_intel import classify_obstacles

    flags = classify_obstacles(
        "https://www.google.com/sorry/index?continue=https://example.com/",
        "Sorry",
        "unusual traffic from your computer network",
    )
    assert flags["google_sorry_page"] is True
    assert flags["suspicious_bot_wall"] is True


def test_control_scoring_prioritises_form_fields() -> None:
    """``enrich_controls`` ranks required inputs above generic buttons."""
    sys.path.insert(0, str(_PW_ROOT / "scripts" / "_lib"))
    from _controls import enrich_controls, suggest_selector

    rows = enrich_controls(
        [
            {"tag": "button", "type": "submit", "visible": True},
            {
                "tag": "input",
                "type": "email",
                "required": True,
                "visible": True,
                "id": "email",
            },
        ],
    )
    assert rows[0]["tag"] == "input"
    assert suggest_selector({"id": "email", "tag": "input"}) == "#email"


@pytest.mark.asyncio
async def test_extract_page_text_emits_json_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """``extract_page_text.py`` returns ``emit_ok`` JSON with ``text`` (not raw stdout)."""
    sys.path.insert(0, str(_PW_ROOT / "scripts"))
    import extract_page_text as ept  # type: ignore[import-not-found]

    class _Loc:
        async def count(self) -> int:
            return 1

        @property
        def first(self) -> _Loc:
            return self

        async def inner_text(self, **kwargs: object) -> str:
            return "Sample article body for live facts extraction test."

    class _Page:
        url = "https://www.nba.com/playoffs/2026"

        def locator(self, sel: str) -> _Loc:
            return _Loc()

    class _Session:
        async def __aenter__(self) -> _Page:
            return _Page()

        async def __aexit__(self, *args: object) -> None:
            return None

    async def fake_wait(page: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(ept, "browser_session", lambda **kwargs: _Session())
    monkeypatch.setattr(ept, "wait_for_page_ready", fake_wait)
    monkeypatch.setattr(sys, "argv", ["extract_page_text.py"])

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = await ept.main()
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert "Sample article body" in str(data.get("text"))
    assert data.get("chars", 0) >= 40
    assert data.get("selector") == "article"
    assert data.get("preset") == "generic"


@pytest.mark.asyncio
async def test_human_pause_uses_wait_for_timeout() -> None:
    """``human_pause`` delegates to Playwright ``wait_for_timeout``."""
    sys.path.insert(0, str(_PW_ROOT / "scripts" / "_lib"))
    from _timing import human_pause

    class _Page:
        def __init__(self) -> None:
            self.ms: int | None = None

        async def wait_for_timeout(self, ms: int) -> None:
            self.ms = ms

    page = _Page()
    delay = await human_pause(page, min_ms=100, max_ms=100)
    assert delay == 100
    assert page.ms == 100


class _MockLocator:
    def __init__(self, *, count: int = 0) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count

    @property
    def first(self) -> _MockLocator:
        return self

    async def wait_for(self, **kwargs: object) -> None:
        return None

    async def click(self, **kwargs: object) -> None:
        return None

    def filter(self, **kwargs: object) -> _MockLocator:
        return self


class _MockFrame:
    def __init__(self, url: str = "https://consent.google.com/") -> None:
        self.url = url

    def locator(self, sel: str) -> _MockLocator:
        if sel == "#L2AGLb":
            return _MockLocator(count=1)
        return _MockLocator(count=0)

    def get_by_role(self, role: str, name: object = None) -> _MockLocator:
        return _MockLocator(count=0)


class _MockPage:
    def __init__(self) -> None:
        self.frames = [_MockFrame()]

    async def wait_for_timeout(self, ms: int) -> None:
        return None

    def locator(self, sel: str) -> _MockLocator:
        if sel == "#L2AGLb":
            return _MockLocator(count=1)
        return _MockLocator(count=0)

    def get_by_role(self, role: str, name: object = None) -> _MockLocator:
        return _MockLocator(count=0)


@pytest.mark.asyncio
async def test_try_dismiss_cookie_banners_clicks_google_accept() -> None:
    """Google consent accept-all selector is attempted before generic CMP heuristics."""
    sys.path.insert(0, str(_PW_ROOT / "scripts" / "_lib"))
    from _page_intel import try_dismiss_cookie_banners

    log = await try_dismiss_cookie_banners(_MockPage())
    assert log == ["clicked:google:#L2AGLb"]


@pytest.mark.asyncio
async def test_wait_for_page_ready_auto_dismisses_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bundled ``wait_for_page_ready`` accepts cookie banners after load."""
    sys.path.insert(0, str(_PW_ROOT / "scripts" / "_lib"))
    import _page_intel
    import _pw_session

    core_calls: list[float] = []
    dismiss_calls: list[bool] = []

    async def fake_core(page: object, *, network_idle_ms: float = 15_000.0) -> None:
        core_calls.append(network_idle_ms)

    async def fake_dismiss(page: object, *, timeout_ms: int = 8_000) -> list[str]:
        dismiss_calls.append(True)
        return ["clicked:google:#L2AGLb"]

    monkeypatch.setattr(_pw_session, "_core_wait_for_page_ready", fake_core)
    monkeypatch.setattr(_page_intel, "try_dismiss_cookie_banners", fake_dismiss)

    await _pw_session.wait_for_page_ready(object())
    assert dismiss_calls == [True]
    assert core_calls == [15_000.0, 3_000.0]


def test_skills_manager_sets_browser_autoclose_default(tmp_path: Path) -> None:
    """``SkillsManager`` defaults ``SEVN_BROWSER_AUTOCLOSE=0`` for playwright-browser."""
    SkillsManager.reset_singletons_for_tests()
    man = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,))
    rec = man.get_record("playwright-browser")
    shadow = tmp_path / "shadow"
    env = man._build_proc_env(
        shadow,
        rec.skill_dir,
        skill_name=rec.canonical_id,
        session_id="web:scoped",
    )
    assert env.get("SEVN_BROWSER_AUTOCLOSE") == "0"
    assert env.get("SEVN_CONTENT_ROOT") == str(tmp_path.resolve())
    assert env.get("SEVN_WORKSPACE") == str(shadow.resolve())
    assert "web:scoped" in env.get("SEVN_BROWSER_PROFILE_DIR", "")
    SkillsManager.reset_singletons_for_tests()


@pytest.mark.integration
def test_playwright_lifecycle_close_restart_live(tmp_path: Path) -> None:
    """Optional live smoke: goto → session_status → close → restart → goto."""
    if os.environ.get("SEVN_BROWSER_LIVE", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("set SEVN_BROWSER_LIVE=1 to run live Playwright lifecycle smoke")
    try:
        import playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed (uv sync --extra browser)")

    live_env = {"SEVN_CDP_URL": ""}

    code, payload = _run_script(
        _PW_ROOT,
        "scripts/goto.py",
        tmp_path,
        ["https://example.com"],
        extra_env=live_env,
    )
    assert code == 0
    assert payload.get("ok") is True

    code, payload = _run_script(
        _PW_ROOT,
        "scripts/session_status.py",
        tmp_path,
        extra_env=live_env,
    )
    assert code == 0
    assert payload.get("ok") is True
    status = payload.get("data")
    assert isinstance(status, dict)
    assert status.get("profile_dir")
    assert status.get("cdp_url")

    code, payload = _run_script(
        _PW_ROOT,
        "scripts/close_browser.py",
        tmp_path,
        extra_env=live_env,
    )
    assert code == 0
    assert payload.get("ok") is True

    code, payload = _run_script(
        _PW_ROOT,
        "scripts/restart_browser.py",
        tmp_path,
        extra_env=live_env,
    )
    assert code == 0
    assert payload.get("ok") is True
    restart_data = payload.get("data")
    assert isinstance(restart_data, dict)
    assert restart_data.get("cdp_url")

    code, payload = _run_script(
        _PW_ROOT,
        "scripts/goto.py",
        tmp_path,
        ["https://example.com"],
        extra_env=live_env,
    )
    assert code == 0
    assert payload.get("ok") is True


@pytest.mark.integration
def test_playwright_goto_live(tmp_path: Path) -> None:
    """Optional live smoke when ``SEVN_BROWSER_LIVE=1`` and Playwright is installed."""
    if os.environ.get("SEVN_BROWSER_LIVE", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("set SEVN_BROWSER_LIVE=1 to run live Playwright goto smoke")
    try:
        import playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed (uv sync --extra browser)")

    code, payload = _run_script(
        _PW_ROOT,
        "scripts/goto.py",
        tmp_path,
        ["https://example.com"],
    )
    assert code == 0
    assert payload.get("ok") is True
