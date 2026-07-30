"""W13.2-W13.4 - skill dependency setup, PATH resolution, guardrails (-> W14)."""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from tests.open_issues_sweep.batch_c.conftest import (
    install_fake_yt_dlp,
    skills_manager_for_tree,
    write_min_skill,
)

from sevn.media.yt_dlp_skill import yt_dlp_available
from sevn.runtime.operator_path import augment_operator_path

_JOBSPY_SCRIPTS = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "job-ops"
    / "scripts"
)


def _execute_skill_setup(
    skill_id: str,
    *,
    confirmed: bool,
    workspace_root: Path,
) -> dict[str, Any]:
    """Call the W14 setup orchestrator (lazy import)."""
    from sevn.skills.setup import execute_skill_setup

    return execute_skill_setup(
        skill_id,
        workspace_root=workspace_root,
        confirmed=confirmed,
    )


def _jobspy_guard_message() -> str:
    """Return the JobSpy missing-dependency error from the bundled extractor."""
    scripts = str(_JOBSPY_SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from lib.extractors import jobspy_source
    from lib.models import SearchQuery

    result = jobspy_source.run(SearchQuery(search_terms=["engineer"]))
    assert result.success is False
    assert result.error is not None
    return result.error


@pytest.mark.xfail(reason="green after W14: job-ops uv extra install (#93)", strict=False)
def test_setup_job_ops_installs_jobspy_extra(tmp_path: Path) -> None:
    """Setting up ``job-ops`` installs its uv extra and clears the JobSpy guard."""
    guard_before = _jobspy_guard_message()
    assert "python-jobspy is not installed" in guard_before

    write_min_skill(
        tmp_path / "skills" / "user" / "job-ops",
        dependencies_yaml=textwrap.dedent(
            """\
            dependencies:
              uv_extras:
                - job-ops"""
        ),
    )
    result = _execute_skill_setup("job-ops", confirmed=True, workspace_root=tmp_path)
    assert result["ok"] is True

    guard_after = _jobspy_guard_message()
    assert "python-jobspy is not installed" not in guard_after


@pytest.mark.xfail(reason="green after W14: venv bin on PATH for skill runner (#69)", strict=False)
def test_skill_runner_finds_yt_dlp_after_setup(
    tmp_path: Path,
    batch_c_skills_root: Path,
    venv_bin_on_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After setup, a skill subprocess finds a uv-extra executable without manual PATH fixes."""
    fake_bin = install_fake_yt_dlp(tmp_path)
    target = venv_bin_on_path / "yt-dlp"
    if target.exists():
        target.unlink()
    target.write_bytes((fake_bin / "yt-dlp").read_bytes())
    target.chmod(0o755)

    write_min_skill(
        batch_c_skills_root / "user" / "yt-dlp",
        dependencies_yaml=textwrap.dedent(
            """\
            dependencies:
              executables:
                - yt-dlp"""
        ),
    )
    result = _execute_skill_setup("yt-dlp", confirmed=True, workspace_root=tmp_path)
    assert result["ok"] is True

    man = skills_manager_for_tree(tmp_path, batch_c_skills_root)
    env = man._build_proc_env(tmp_path / "shadow", batch_c_skills_root / "user" / "yt-dlp")
    merged = augment_operator_path(env)
    path_entries = merged.get("PATH", "").split(os.pathsep)
    assert str(venv_bin_on_path) in path_entries
    with monkeypatch.dict(os.environ, merged, clear=False):
        assert yt_dlp_available() is True


@pytest.mark.xfail(reason="green after W14: install confirmation guardrail", strict=False)
def test_install_requires_operator_confirmation(tmp_path: Path) -> None:
    """Install actions require explicit operator confirmation."""
    from sevn.skills.setup import InstallConfirmationRequired

    write_min_skill(
        tmp_path / "skills" / "user" / "needs-setup",
        dependencies_yaml=textwrap.dedent(
            """\
            dependencies:
              uv_extras:
                - job-ops"""
        ),
    )
    with pytest.raises(InstallConfirmationRequired) as excinfo:
        _execute_skill_setup("needs-setup", confirmed=False, workspace_root=tmp_path)
    assert "confirm" in str(excinfo.value).lower()


@pytest.mark.xfail(
    reason="green after W14: unsupported dependency manual-next-step message", strict=False
)
def test_unsupported_dependency_names_manual_next_step(tmp_path: Path) -> None:
    """Unsupported dependencies produce a clear message naming the manual next step."""
    write_min_skill(
        tmp_path / "skills" / "user" / "exotic",
        dependencies_yaml=textwrap.dedent(
            """\
            dependencies:
              executables:
                - totally-unknown-binary-xyz"""
        ),
    )
    result = _execute_skill_setup("exotic", confirmed=True, workspace_root=tmp_path)
    assert result["ok"] is False
    message = str(result.get("message", ""))
    assert "totally-unknown-binary-xyz" in message
    assert "manual" in message.lower() or "next step" in message.lower()


@pytest.mark.xfail(
    reason="green after W14: skill setup status lists pending requirements", strict=False
)
def test_skill_setup_status_lists_unmet_requirements(tmp_path: Path) -> None:
    """Setup status enumerates missing uv extras and executables before install."""
    from sevn.skills.setup import skill_setup_requirements

    skills_root = tmp_path / "skills"
    for sub in ("core", "generated", "user"):
        (skills_root / sub).mkdir(parents=True, exist_ok=True)
    write_min_skill(
        skills_root / "user" / "combo",
        dependencies_yaml=textwrap.dedent(
            """\
            dependencies:
              uv_extras:
                - job-ops
              executables:
                - yt-dlp"""
        ),
    )
    man = skills_manager_for_tree(tmp_path, skills_root)
    record = man.get_record("combo")
    reqs = skill_setup_requirements(record.manifest)
    kinds = {row["kind"] for row in reqs}
    assert "uv_extra" in kinds
    assert "executable" in kinds
