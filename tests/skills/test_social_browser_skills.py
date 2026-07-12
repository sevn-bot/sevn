"""Bundled ``x-use`` and ``facebook-use`` social browser skill tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.manager import SkillsManager
from sevn.skills.social_browser import (
    FACEBOOK_USE_SKILL_ID,
    X_USE_SKILL_ID,
    facebook_search_url,
    host_allowed,
    merge_social_browser_proc_env,
    resolve_browser_profile,
    validate_social_url,
    x_search_url,
)

_X_ROOT = BUNDLED_SKILLS_ROOT / "core" / X_USE_SKILL_ID
_FB_ROOT = BUNDLED_SKILLS_ROOT / "core" / FACEBOOK_USE_SKILL_ID


@pytest.fixture(autouse=True)
def _reset_skills_manager() -> None:
    """Clear ``SkillsManager`` singletons between tests."""
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def _run_script(
    skill_root: Path,
    rel: str,
    workspace: Path,
    cli_args: list[str] | None = None,
    *,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    """Run one social browser skill script and parse JSON stdout."""
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


def test_bundled_skill_manifests_exist() -> None:
    """Core tree ships ``x-use`` and ``facebook-use`` manifests with egress frontmatter."""
    for skill_id in (X_USE_SKILL_ID, FACEBOOK_USE_SKILL_ID):
        skill_md = BUNDLED_SKILLS_ROOT / "core" / skill_id / "SKILL.md"
        assert skill_md.is_file()
        text = skill_md.read_text(encoding="utf-8")
        assert "egress:" in text
        assert "abortable:" in text


def test_host_allowed_x_and_facebook_domains() -> None:
    """Session-bound egress suffix matching accepts platform hosts."""
    assert host_allowed("www.x.com", allowlist=("x.com",))
    assert host_allowed("mobile.twitter.com", allowlist=("twitter.com",))
    assert host_allowed("www.facebook.com", allowlist=("facebook.com",))
    assert host_allowed("static.xx.fbcdn.net", allowlist=("fbcdn.net",))


def test_validate_social_url_rejects_cross_skill_hosts() -> None:
    """``validate_social_url`` blocks hosts outside the skill allowlist."""
    assert (
        validate_social_url("https://x.com/home", skill_id=X_USE_SKILL_ID) == "https://x.com/home"
    )
    with pytest.raises(ValueError, match="egress allowlist"):
        validate_social_url("https://www.facebook.com/", skill_id=X_USE_SKILL_ID)
    with pytest.raises(ValueError, match="egress allowlist"):
        validate_social_url("https://x.com/home", skill_id=FACEBOOK_USE_SKILL_ID)


def test_resolve_browser_profile_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile resolution prefers env, then workspace config, then default path."""
    custom = tmp_path / "profiles" / "operator"
    custom.mkdir(parents=True)
    monkeypatch.setenv("SEVN_BROWSER_PROFILE_DIR", str(custom))
    assert resolve_browser_profile(tmp_path, skill_id=X_USE_SKILL_ID, cfg=None) == custom.resolve()

    monkeypatch.delenv("SEVN_BROWSER_PROFILE_DIR", raising=False)
    cfg = WorkspaceConfig(
        schema_version=1,
        skills={"social_browser": {"profile_dir": str(custom)}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert (
        resolve_browser_profile(tmp_path, skill_id=FACEBOOK_USE_SKILL_ID, cfg=cfg)
        == custom.resolve()
    )

    default = (tmp_path / ".sevn" / "browser-profiles" / "default").resolve()
    assert resolve_browser_profile(tmp_path, skill_id=X_USE_SKILL_ID, cfg=None) == default


def test_search_url_helpers() -> None:
    """Search URL builders encode queries for X and Facebook."""
    assert x_search_url("hello world") == "https://x.com/search?q=hello+world"
    assert facebook_search_url("cats") == "https://www.facebook.com/search/top?q=cats"


def test_x_session_status_dry_run(tmp_path: Path) -> None:
    """``x-use`` session_status returns profile + CDP metadata without Playwright."""
    code, payload = _run_script(_X_ROOT, "scripts/session_status.py", tmp_path, ["--dry-run"])
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("skill_id") == X_USE_SKILL_ID
    assert data.get("mode") == "dry_run"
    assert data.get("cdp_reachable") is False


def test_x_timeline_dry_run(tmp_path: Path) -> None:
    """``x-use`` timeline script supports ``--dry-run`` plan output."""
    code, payload = _run_script(_X_ROOT, "scripts/timeline.py", tmp_path, ["--dry-run"])
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "dry_run"
    assert data.get("url") == "https://x.com/home"


def test_x_search_dry_run(tmp_path: Path) -> None:
    """``x-use`` search script validates query and dry-run envelope."""
    code, payload = _run_script(
        _X_ROOT,
        "scripts/search.py",
        tmp_path,
        ["--query", "sevn.bot", "--dry-run"],
    )
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("url") == "https://x.com/search?q=sevn.bot"


def test_facebook_feed_dry_run(tmp_path: Path) -> None:
    """``facebook-use`` feed script supports ``--dry-run`` plan output."""
    code, payload = _run_script(_FB_ROOT, "scripts/feed.py", tmp_path, ["--dry-run"])
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "dry_run"
    assert data.get("url") == "https://www.facebook.com/"


def test_facebook_search_dry_run(tmp_path: Path) -> None:
    """``facebook-use`` search script supports ``--dry-run`` plan output."""
    code, payload = _run_script(
        _FB_ROOT,
        "scripts/search.py",
        tmp_path,
        ["--query", "community", "--dry-run"],
    )
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert "facebook.com/search/top" in str(data.get("url"))


def test_skills_manager_injects_social_browser_env(tmp_path: Path) -> None:
    """``SkillsManager`` sets autoclose off and profile dir for social browser skills."""
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    cfg = WorkspaceConfig(
        schema_version=1,
        skills={"social_browser": {"profile_dir": str(profile)}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    man = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,), config=cfg)
    rec = man.get_record(X_USE_SKILL_ID)
    env = man._build_proc_env(tmp_path / "shadow", rec.skill_dir, skill_name=rec.canonical_id)
    assert env.get("SEVN_BROWSER_AUTOCLOSE") == "0"
    assert env.get("SEVN_CONTENT_ROOT") == str(tmp_path.resolve())
    assert env.get("SEVN_BROWSER_PROFILE_DIR") == str(profile.resolve())


def test_merge_social_browser_proc_env_noop_for_other_skills(tmp_path: Path) -> None:
    """``merge_social_browser_proc_env`` ignores unrelated skill ids."""
    env: dict[str, str] = {}
    merge_social_browser_proc_env(
        env,
        skill_id="playwright-browser",
        workspace=tmp_path,
        cfg=None,
    )
    assert "SEVN_BROWSER_PROFILE_DIR" not in env


@pytest.mark.integration
def test_x_timeline_live(tmp_path: Path) -> None:
    """Optional live smoke when ``SEVN_SOCIAL_BROWSER_LIVE=1`` and Playwright is installed."""
    if os.environ.get("SEVN_SOCIAL_BROWSER_LIVE", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("set SEVN_SOCIAL_BROWSER_LIVE=1 to run live social browser smoke")
    try:
        import playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed (uv sync --extra browser)")

    code, payload = _run_script(_X_ROOT, "scripts/timeline.py", tmp_path, ["--max-chars", "500"])
    assert code in (0, 1)
    assert "ok" in payload
