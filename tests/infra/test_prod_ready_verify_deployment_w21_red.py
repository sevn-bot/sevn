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
import json
import re
import subprocess
import sys
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
        "authenticated-proxy-roundtrip",
        "volume-upgrade",
        "browser-gui-boot",
        "cancellation-cleanup",
        "sandbox-scoped-token",
    }
)

_VERIFY_MAKE_RE = re.compile(r"make\s+verify-deployment\b")
_EXIT_2_TOLERATE_RE = re.compile(
    r"continue-on-error\s*:\s*true"
    r"|driver_unavailable"
    r"|\$\?\s*-eq\s*2"
    r"|EXIT_CODES\[.*UNAVAILABLE",
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


def _semantic_step_blob(step: dict[str, Any]) -> str:
    """Return executable step fields without descriptive metadata."""
    parts: list[str] = []
    for key in ("run", "if", "shell"):
        val = step.get(key)
        if isinstance(val, str):
            parts.append(val)
    return "\n".join(parts)


def _semantic_blob(job: dict[str, Any]) -> str:
    """Return executable job fields without names or action inputs."""
    parts: list[str] = []
    for key in ("if", "runs-on"):
        val = job.get(key)
        if isinstance(val, str):
            parts.append(val)
    steps = job.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                parts.append(_semantic_step_blob(step))
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
    """Return whether the job treats ``driver_unavailable`` (exit 2) as non-fatal.

    Only the step that actually runs ``make verify-deployment`` is checked; cleanup
    / quarantine / artifact steps that ignore their own exit status do not change
    the verdict of the verify step itself.
    """
    steps = job.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            if not _VERIFY_MAKE_RE.search(_step_blob(step)):
                continue
            if step.get("continue-on-error") is True:
                return True
            if _EXIT_2_TOLERATE_RE.search(_semantic_step_blob(step)):
                return True
    return False


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


def test_ci_supplementary_runs_verify_deployment_on_daily_cron() -> None:
    """W21.5 / C14.1 - daily cron job invokes ``make verify-deployment``.

    Reconciled after W23 landed; retain this docstring as the regression contract.
    """
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


def test_ci_cd_runs_verify_deployment_on_release_tags() -> None:
    """W21.5 / C14.1 - tag path invokes ``make verify-deployment``.

    Reconciled after W23 landed; retain this docstring as the regression contract.
    """
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


def test_cron_verify_deployment_tolerates_driver_unavailable_exit_2() -> None:
    """W21.6 / D52 - daily cron may accept exit 2 (runner without Docker).

    Reconciled after W23 landed; retain this docstring as the regression contract.
    """
    jobs = _jobs_running_verify_deployment(_CI_SUPP)
    assert jobs, "cron verify-deployment job missing"
    assert any(_job_tolerates_exit_2(job) for job in jobs.values()), (
        "cron path must tolerate driver_unavailable (exit 2)"
    )


def test_tag_verify_deployment_fails_on_driver_unavailable_exit_2() -> None:
    """W21.6 / D52 - release tags must not treat exit 2 as success.

    Reconciled after W23 landed; retain this docstring as the regression contract.
    """
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


@pytest.mark.parametrize("driver", sorted(REQUIRED_NEW_DRIVERS))
def test_verify_deployment_registers_new_driver(driver: str) -> None:
    """W21.7 / C14.2 - each uncovered path has a registered ``DRIVERS`` entry.

    Reconciled after W23 landed; retain this docstring as the regression contract.
    """
    keys = _load_drivers_keys()
    assert driver in keys, f"{driver!r} missing from scripts/verify_deployment.py DRIVERS"


# ---------------------------------------------------------------------------
# W21.8 - evidence attached to release (→ W23)
# ---------------------------------------------------------------------------


def test_release_attaches_verify_deployment_evidence() -> None:
    """W21.8 / C14.3 - ``evidence/verify/`` is a downloadable release artifact.

    Reconciled after W23 landed; retain this docstring as the regression contract.
    """
    text = _workflow_text(_CI_CD)
    jobs = _jobs(_CI_CD)
    assert _release_attaches_verify_evidence(text, jobs), (
        "ci-cd.yml must attach evidence/verify/ on the release/tag path"
    )


# ---------------------------------------------------------------------------
# F-V3 - behavioural driver coverage (→ F-V4)
# ---------------------------------------------------------------------------


def _load_verify_module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_deployment_fv3", _VERIFY_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _healthy_driver_run(monkeypatch: pytest.MonkeyPatch, module: Any) -> Any:
    monkeypatch.setattr(module, "_docker_unavailable_reason", lambda: None)
    monkeypatch.setattr(module, "_run", lambda *args, **kwargs: (0, "stack ready"))

    def http_probe(url: str, *args: Any, **kwargs: Any) -> tuple[int, str]:
        if url.endswith("/healthz"):
            return 200, "healthy"
        return 401, "authentication required"

    def authenticated_probe(url: str, *args: Any, **kwargs: Any) -> tuple[int, str]:
        if "/llm/" in url:
            return 403, "scope denied"
        return 200, "authenticated"

    monkeypatch.setattr(module, "_http_probe", http_probe)
    monkeypatch.setattr(module, "_authenticated_probe", authenticated_probe)
    monkeypatch.setattr(
        "sevn.proxy.auth.mint_session_token",
        lambda **kwargs: "test-session-token",
    )
    monkeypatch.setenv("SEVN_VERIFY_STACK_TIMEOUT_S", "1")
    monkeypatch.setenv("SEVN_VERIFY_READY_TIMEOUT_S", "1")
    return module


def test_authenticated_proxy_roundtrip_driver_probes_via_live_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-V3 - driver runtime must succeed under a healthy mocked stack."""
    module = _healthy_driver_run(monkeypatch, _load_verify_module())
    result = module.drive_authenticated_proxy_roundtrip()
    assert result.name == "authenticated-proxy-roundtrip"
    assert result.status not in {module.STATUS_FAIL, module.STATUS_UNAVAILABLE}
    assert any(check.name == "proxy-healthz" for check in result.checks)


def test_sandbox_scoped_token_driver_probes_via_live_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-V3 - driver runtime must succeed under a healthy mocked stack."""
    module = _healthy_driver_run(monkeypatch, _load_verify_module())
    result = module.drive_sandbox_scoped_token()
    assert result.name == "sandbox-scoped-token"
    assert result.status not in {module.STATUS_FAIL, module.STATUS_UNAVAILABLE}
    assert any(check.name == "proxy-healthz" for check in result.checks)


def test_volume_upgrade_driver_probes_via_live_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-THERMOS-4 - driver must probe sentinel seed / stack-up / sentinel survives."""
    module = _healthy_driver_run(monkeypatch, _load_verify_module())

    # The helper's ``(0, "stack ready")`` mock would otherwise make the
    # ``sentinel in read_out`` check fail (the sentinel is generated by the
    # driver and not present in the helper's canned output). Capture the
    # sentinel from the seed ``docker run`` argv and echo it back on the
    # subsequent ``cat`` invocation.
    sentinel_holder: dict[str, str] = {}
    sentinel_re = re.compile(r"'(verify-volume-upgrade-[^']+)'")

    def volume_run(argv, *args, **kwargs):  # type: ignore[no-untyped-def]
        joined = " ".join(str(a) for a in argv)
        match = sentinel_re.search(joined)
        if match:
            sentinel_holder["value"] = match.group(1)
            return 0, sentinel_holder["value"]
        if "cat" in argv and "/mnt/.sevn-verify-sentinel" in joined:
            return 0, sentinel_holder.get("value", "stack ready")
        return 0, "stack ready"

    monkeypatch.setattr(module, "_run", volume_run)
    result = module.drive_volume_upgrade()
    assert result.name == "volume-upgrade"
    assert result.status not in {module.STATUS_FAIL, module.STATUS_UNAVAILABLE}
    check_names = {check.name for check in result.checks}
    assert "stack-up" in check_names or "sentinel-survives" in check_names, (
        f"volume-upgrade must emit stack-up / sentinel-survives checks; got {check_names!r}"
    )


def test_browser_gui_boot_driver_probes_via_live_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-THERMOS-4 - driver must probe browser + gui overlay config resolution."""
    module = _healthy_driver_run(monkeypatch, _load_verify_module())

    # ``docker compose config --format json`` must yield parseable JSON whose
    # ``services.sevn-gateway.build.dockerfile`` matches the overlay's
    # Dockerfile. The helper's ``(0, "stack ready")`` mock is not valid JSON;
    # echo a minimal valid config back so ``json.loads`` and the dockerfile
    # check succeed.
    dockerfile_re = re.compile(r"docker-compose\.(browser|gui)\.yml")

    def config_run(argv, *args, **kwargs):  # type: ignore[no-untyped-def]
        joined = " ".join(str(a) for a in argv)
        match = dockerfile_re.search(joined)
        dockerfile = (
            "Dockerfile.gateway.browser"
            if match and match.group(1) == "browser"
            else "Dockerfile.gateway.gui"
        )
        return 0, json.dumps(
            {"services": {"sevn-gateway": {"build": {"dockerfile": dockerfile, "context": "."}}}}
        )

    monkeypatch.setattr(module, "_run", config_run)
    result = module.drive_browser_gui_boot()
    assert result.name == "browser-gui-boot"
    assert result.status not in {module.STATUS_FAIL, module.STATUS_UNAVAILABLE}
    check_names = {check.name for check in result.checks}
    assert any(name.startswith(("browser-override/", "gui-override/")) for name in check_names), (
        "browser-gui-boot must emit browser-override/* / gui-override/* checks; "
        f"got {check_names!r}"
    )


def test_cancellation_cleanup_driver_probes_via_live_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-THERMOS-4 - driver must probe cancel-triggered + orphan diff checks."""
    module = _healthy_driver_run(monkeypatch, _load_verify_module())
    result = module.drive_cancellation_cleanup()
    assert result.name == "cancellation-cleanup"
    assert result.status not in {module.STATUS_FAIL, module.STATUS_UNAVAILABLE}
    check_names = {check.name for check in result.checks}
    assert (
        "cancel-triggered" in check_names
        or "no-orphan-containers" in check_names
        or "no-leaked-volumes" in check_names
    ), f"cancellation-cleanup must emit cancel-triggered / orphan checks; got {check_names!r}"


def test_no_driver_probes_unmapped_host_proxy_port() -> None:
    """F-V3 - the proxy URL constant must be published by the verify compose overlay.

    The F-V1/F-V2 fix introduced ``VERIFY_PROXY_URL`` and a verify-only compose
    overlay that publishes the proxy port to the host. This test pins the
    topology: the literal ``http://127.0.0.1:3102`` URL must be present **only**
    as a single ``VERIFY_PROXY_URL`` constant, and the corresponding host:port
    must be published by ``docker/docker-compose.verify.yml``. If anyone
    re-introduces an inline ``f"http://127.0.0.1:{proxy_port}"`` interpolation
    or drops the verify overlay, the topology breaks and this test fails.
    """
    source = _VERIFY_SCRIPT.read_text(encoding="utf-8")
    inline = 'f"http://127.0.0.1:{proxy_port}"'
    assert inline not in source, (
        "no verify-deployment driver may inline the host proxy URL — "
        "use the VERIFY_PROXY_URL constant backed by docker-compose.verify.yml"
    )
    assert source.count('VERIFY_PROXY_URL = "http://127.0.0.1:3102"') == 1, (
        "VERIFY_PROXY_URL must be defined exactly once as http://127.0.0.1:3102"
    )

    verify_compose = _REPO_ROOT / "docker" / "docker-compose.verify.yml"
    assert verify_compose.is_file(), (
        "docker/docker-compose.verify.yml must publish the proxy host port for verify"
    )
    assert "127.0.0.1:3102:8787" in verify_compose.read_text(encoding="utf-8"), (
        "docker-compose.verify.yml must publish 127.0.0.1:3102 → 8787 for verify probes"
    )


def test_no_dead_sevn_verify_proxy_port_reference() -> None:
    """F-V4 - keep the removed proxy-port environment variable out of shipped code."""
    completed = subprocess.run(
        ["git", "grep", "-n", "SEVN_VERIFY_PROXY_PORT", "--", "src/", "docker/", "scripts/"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1, completed.stdout or completed.stderr
