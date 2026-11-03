"""Release wheel, ``make wheel``, the release workflow and the Linux CI jobs (plan 0025 D3, D12).

Workflows and the Makefile are parsed (``make -n``), never run. The wheel test builds
from the working tree with ``uv build`` offline and needs the SPA in
``host/src/sevn/_web`` (``make build-web``); it skips when either is unavailable.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from support.repo import repo_root

_ROOT = repo_root()


def _yaml(path: Path) -> dict[str, Any]:
    yaml = pytest.importorskip("yaml")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _on(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True.
    trigger = workflow.get("on", workflow.get(True))
    assert isinstance(trigger, dict), trigger
    return trigger


def _steps_text(job: dict[str, Any]) -> str:
    parts: list[str] = []
    for step in job.get("steps", []):
        parts.append(str(step.get("uses", "")))
        parts.append(str(step.get("run", "")))
        parts.append(str(step.get("with", "")))
    return "\n".join(parts)


def _make_dry_run(target: str) -> str:
    completed = subprocess.run(  # noqa: S603
        ["make", "-n", target],  # noqa: S607
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


# --- wheel (D3) --------------------------------------------------------------


def test_make_wheel_builds_the_spa_then_the_wheel_and_sums() -> None:
    plan = _make_dry_run("wheel")
    web_at = min(
        (plan.find(token) for token in ("pnpm", "build-web", "vite build") if token in plan),
        default=-1,
    )
    build_at = plan.find("uv build")
    assert web_at >= 0, plan
    assert build_at > web_at, plan
    assert "_web" in plan
    assert "SHA256SUMS" in plan


def test_built_wheel_contains_the_web_app(tmp_path: Path) -> None:
    index = _ROOT / "host" / "src" / "sevn" / "_web" / "index.html"
    if not index.is_file():
        pytest.skip("host/src/sevn/_web is not built (make build-web)")
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    completed = subprocess.run(  # noqa: S603
        [uv, "build", "--package", "sevn", "--wheel", "--out-dir", str(tmp_path)],
        cwd=_ROOT,
        env={**os.environ, "UV_OFFLINE": "1"},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"offline wheel build unavailable: {completed.stderr.strip()[-200:]}")
    wheels = list(tmp_path.glob("sevn-*-py3-none-any.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
    assert "sevn/_web/index.html" in names
    assert (
        "sevn/runtime/manifest.toml" in names
        or not (_ROOT / "host" / "src" / "sevn" / "runtime" / "manifest.toml").is_file()
    )


def test_release_workflow_publishes_wheel_and_sums_on_tags() -> None:
    path = _ROOT / ".github" / "workflows" / "release.yml"
    workflow = _yaml(path)
    tags = _on(workflow)["push"]["tags"]
    assert "v*" in tags
    text = path.read_text(encoding="utf-8")
    assert "pnpm" in text
    assert "_web" in text
    assert "uv build" in text
    assert "SHA256SUMS" in text
    assert re.search(r"contents:\s*write", text)
    jobs = workflow["jobs"]
    assert any(".whl" in _steps_text(job) for job in jobs.values())
    assert "${{ secrets.GITHUB_TOKEN }}" in text or "github.token" in text
    other_secrets = re.findall(r"\$\{\{\s*secrets\.(\w+)", text)
    assert set(other_secrets) <= {"GITHUB_TOKEN"}, other_secrets
    # A release build never restores a cache another workflow could have written.
    for job in jobs.values():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("astral-sh/setup-uv@"):
                assert step.get("with", {}).get("enable-cache") is False, step


# --- CI jobs (D12) -----------------------------------------------------------


def _ci() -> dict[str, Any]:
    return _yaml(_ROOT / ".github" / "workflows" / "ci.yml")


def test_existing_ci_job_keeps_its_name() -> None:
    jobs = _ci()["jobs"]
    assert "ci" in jobs
    assert "make ci" in _steps_text(jobs["ci"])


def test_host_arch_job_runs_host_tests_in_archlinux() -> None:
    job = _ci()["jobs"]["host-arch"]
    container = job["container"]
    image = container if isinstance(container, str) else container["image"]
    assert image.startswith("archlinux:base")
    text = _steps_text(job)
    assert "pacman" in text
    assert "bubblewrap" in text
    assert "make test-host" in text


def test_install_sh_job_runs_shellcheck_and_both_distros() -> None:
    job = _ci()["jobs"]["install-sh"]
    text = _steps_text(job) + str(job.get("strategy", ""))
    assert "shellcheck" in text
    assert "install.sh" in text
    assert "--no-service" in text
    assert "--wheel" in text
    assert "ubuntu:24.04" in text
    assert "archlinux:base" in text
    assert "doctor --json" in text


def test_images_job_builds_both_images_and_checks_runtimes() -> None:
    job = _ci()["jobs"]["images"]
    text = _steps_text(job) + str(job.get("strategy", ""))
    assert "Dockerfile.ubuntu" in text
    assert "deploy/Dockerfile" in text
    assert "/health" in text
    assert "runtimes list" in text


def test_new_ci_jobs_use_no_secrets() -> None:
    jobs = _ci()["jobs"]
    for name in ("host-arch", "install-sh", "images"):
        assert "${{ secrets" not in str(jobs[name]), name
