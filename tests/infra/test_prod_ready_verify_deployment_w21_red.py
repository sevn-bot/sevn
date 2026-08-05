"""Prod-readiness Batch F W21 RED - C14.1-C14.3 verify-deployment wiring (D52).

Contracts (``about-sevn.bot/specs/25-cicd-full.md``,
``.ignorelocal/waves/prod-readiness-0.0.1-wave-plan.md`` W21 / **D52**):

- **C14.1 / W21.5** - a workflow runs ``make verify-deployment`` on the daily
  cron (``ci-supplementary.yml``) and on ``refs/tags/v*`` (``ci-cd.yml``).
- **D52 / W21.6** - exit 2 (``driver_unavailable``) fails the tag path and is
  tolerated on the cron.
- **C14.2 / W21.7** - new drivers are registered in ``DRIVERS``.
- **C14.3 / W21.8** - captured ``evidence/verify/`` is attached to the release.

All assertions xfail until W23; driver name strings are the locked contract for
the impl wave.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_CD = _REPO_ROOT / ".github" / "workflows" / "ci-cd.yml"
_CI_SUPP = _REPO_ROOT / ".github" / "workflows" / "ci-supplementary.yml"
_VERIFY_SCRIPT = _REPO_ROOT / "scripts" / "verify_deployment.py"

# Locked driver ids for W23 / C14.2 - kebab-case matching existing DRIVERS keys.
REQUIRED_NEW_DRIVERS = frozenset(
    {
        "authenticated-proxy",
        "volume-upgrade",
        "multi-arch-browser-gui",
        "cancellation-cleanup",
    }
)

_VERIFY_MAKE_RE = re.compile(r"make\s+verify-deployment\b")
_EXIT_2_TOLERATE_RE = re.compile(
    r"(continue-on-error\s*:\s*true)"
    r"|(driver_unavailable)"
    r"|(\bec\b.*=.*2)"
    r"|(exit\s*[= ]*2)"
    r"|(\$\?\s*-eq\s*2)"
    r"|(EXIT_CODES\[.*UNAVAILABLE)",
    re.IGNORECASE | re.MULTILINE,
)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _workflow_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _jobs(path: Path) -> dict[str, Any]:
    jobs = _load_yaml(path).get("jobs")
    assert isinstance(jobs, dict)
    return jobs


def _step_blob(step: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("name", "run", "if", "shell"):
        val = step.get(key)
        if isinstance(val, str):
            parts.append(val)
    with_block = step.get("with")
    if isinstance(with_block, dict):
        parts.extend(str(v) for v in with_block.values() if v is not None)
    return "\n".join(parts)


def _job_blob(job: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("name", "if", "runs-on"):
        val = job.get(key)
        if isinstance(val, str):
            parts.append(val)
    steps = job.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                parts.append(_step_blob(step))
                if step.get("continue-on-error") is True:
                    parts.append("continue-on-error: true")
    return "\n".join(parts)


def _jobs_running_verify_deployment(path: Path) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for name, job in _jobs(path).items():
        if not isinstance(job, dict):
            continue
        if _VERIFY_MAKE_RE.search(_job_blob(job)):
            found[name] = job
    return found


def _load_drivers_keys() -> set[str]:
    """Parse ``DRIVERS`` keys from the verify script without executing drivers."""
    tree = ast.parse(_VERIFY_SCRIPT.read_text(encoding="utf-8"), filename=str(_VERIFY_SCRIPT))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "DRIVERS"
                and isinstance(node.value, ast.Dict)
            ):
                keys: set[str] = set()
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        keys.add(key.value)
                return keys
    # Fallback: import module (drivers are callables, import is side-effect light).
    spec = importlib.util.spec_from_file_location("verify_deployment", _VERIFY_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    drivers = getattr(mod, "DRIVERS", None)
    assert isinstance(drivers, dict)
    return {str(k) for k in drivers}


def _job_tolerates_exit_2(job: dict[str, Any]) -> bool:
    """Return whether the job treats ``driver_unavailable`` (exit 2) as non-fatal."""
    blob = _job_blob(job)
    if job.get("continue-on-error") is True:
        return True
    steps = job.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            if not _VERIFY_MAKE_RE.search(_step_blob(step)):
                continue
            if step.get("continue-on-error") is True:
                return True
            if _EXIT_2_TOLERATE_RE.search(_step_blob(step)):
                return True
    return bool(_EXIT_2_TOLERATE_RE.search(blob) and _VERIFY_MAKE_RE.search(blob))


def _release_attaches_verify_evidence(workflow_text: str, jobs: dict[str, Any]) -> bool:
    """Return whether release/tag path attaches ``evidence/verify`` artifacts."""
    if "evidence/verify" not in workflow_text and "evidence/verify/" not in workflow_text:
        return False
    # Prefer co-location with verify-deployment or gh-release / upload-artifact.
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        blob = _job_blob(job)
        has_evidence = "evidence/verify" in blob
        has_attach = (
            "upload-artifact" in blob
            or "action-gh-release" in blob
            or "softprops/action-gh-release" in blob
            or "files:" in blob
        )
        if has_evidence and (has_attach or _VERIFY_MAKE_RE.search(blob)):
            return True
    return "evidence/verify" in workflow_text and (
        "upload-artifact" in workflow_text or "action-gh-release" in workflow_text
    )


# ---------------------------------------------------------------------------
# W21.5 - workflow wiring (→ W23)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W23: verify-deployment on daily cron", strict=False)
def test_ci_supplementary_runs_verify_deployment_on_daily_cron() -> None:
    """W21.5 / C14.1 - daily cron job invokes ``make verify-deployment``."""
    text = _workflow_text(_CI_SUPP)
    assert "17 5 * * *" in text  # daily schedule already present
    jobs = _jobs_running_verify_deployment(_CI_SUPP)
    assert jobs, "ci-supplementary.yml must run make verify-deployment"
    # At least one verify job is gated on the daily cron (or workflow_dispatch).
    daily_ok = False
    for job in jobs.values():
        blob = _job_blob(job)
        if_expr = str(job.get("if", ""))
        if "17 5 * * *" in if_expr or "workflow_dispatch" in if_expr or "schedule" in if_expr:
            daily_ok = True
        if "17 5 * * *" in blob or "schedule" in blob:
            daily_ok = True
    assert daily_ok, "verify-deployment job must be reachable from the daily cron"


@pytest.mark.xfail(reason="green after W23: verify-deployment on refs/tags/v*", strict=False)
def test_ci_cd_runs_verify_deployment_on_release_tags() -> None:
    """W21.5 / C14.1 - tag path invokes ``make verify-deployment``."""
    jobs = _jobs_running_verify_deployment(_CI_CD)
    assert jobs, "ci-cd.yml must run make verify-deployment on the tag path"
    tag_ok = False
    for job in jobs.values():
        blob = _job_blob(job)
        if_expr = str(job.get("if", ""))
        combined = f"{if_expr}\n{blob}"
        if "refs/tags/v" in combined or "startsWith(github.ref, 'refs/tags/v')" in combined:
            tag_ok = True
    assert tag_ok, "verify-deployment must run under refs/tags/v* gating"


# ---------------------------------------------------------------------------
# W21.6 - D52 exit-2 policy (→ W23)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W23: D52 exit-2 tolerated on cron", strict=False)
def test_cron_verify_deployment_tolerates_driver_unavailable_exit_2() -> None:
    """W21.6 / D52 - daily cron may accept exit 2 (runner without Docker)."""
    jobs = _jobs_running_verify_deployment(_CI_SUPP)
    assert jobs, "cron verify-deployment job missing"
    assert any(_job_tolerates_exit_2(job) for job in jobs.values()), (
        "cron path must tolerate driver_unavailable (exit 2)"
    )


@pytest.mark.xfail(reason="green after W23: D52 exit-2 fails on tag path", strict=False)
def test_tag_verify_deployment_fails_on_driver_unavailable_exit_2() -> None:
    """W21.6 / D52 - release tags must not treat exit 2 as success."""
    jobs = _jobs_running_verify_deployment(_CI_CD)
    assert jobs, "tag verify-deployment job missing"
    tag_jobs = []
    for job in jobs.values():
        blob = _job_blob(job)
        if_expr = str(job.get("if", ""))
        if "refs/tags/v" in f"{if_expr}\n{blob}" or "startsWith(github.ref" in f"{if_expr}\n{blob}":
            tag_jobs.append(job)
    assert tag_jobs, "no tag-gated verify-deployment job"
    assert all(not _job_tolerates_exit_2(job) for job in tag_jobs), (
        "tag path must fail on driver_unavailable (exit 2)"
    )


# ---------------------------------------------------------------------------
# W21.7 - new drivers registered (→ W23)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W23: C14.2 new verify drivers registered", strict=False)
@pytest.mark.parametrize("driver", sorted(REQUIRED_NEW_DRIVERS))
def test_verify_deployment_registers_new_driver(driver: str) -> None:
    """W21.7 / C14.2 - each uncovered path has a registered ``DRIVERS`` entry."""
    keys = _load_drivers_keys()
    assert driver in keys, f"{driver!r} missing from scripts/verify_deployment.py DRIVERS"


# ---------------------------------------------------------------------------
# W21.8 - evidence attached to release (→ W23)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W23: C14.3 evidence attached to release", strict=False)
def test_release_attaches_verify_deployment_evidence() -> None:
    """W21.8 / C14.3 - ``evidence/verify/`` is a downloadable release artifact."""
    text = _workflow_text(_CI_CD)
    jobs = _jobs(_CI_CD)
    assert _release_attaches_verify_evidence(text, jobs), (
        "ci-cd.yml must attach evidence/verify/ on the release/tag path"
    )
