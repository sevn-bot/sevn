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

_VERIFY_MAKE_RE = re.compile(
    r"make\s+verify-deployment\b"
    r"|verify_deployment\.py"
    r"|VERIFY_OVERALL",
)
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


# ---------------------------------------------------------------------------
# F-Thermos follow-up (mergecraft review 4885580594 / 3737950464) — drivers
# must actually exercise the published container images, not locally-rebuilt
# substitutes. The seam is opt-in via SEVN_VERIFY_IMAGE_OVERLAY=1 plus
# SEVN_VERIFY_IMAGE_TAG=<sha>, so local-dev stacks with no published digest
# stay on the local build path. Tests pin the topology so a regression to
# "build from source on the tag path" is caught.
# ---------------------------------------------------------------------------


_VERIFY_DIGESTS_OVERLAY = _REPO_ROOT / "docker" / "docker-compose.verify-digests.yml"


def test_verify_digests_overlay_exists_and_pins_images_to_tag() -> None:
    """F-Thermos-V1 — the digest overlay must pin ``image:`` to ``<IMAGE_REPOSITORY>/<name>:<tag>``."""
    assert _VERIFY_DIGESTS_OVERLAY.is_file(), (
        "docker/docker-compose.verify-digests.yml must exist so the verify "
        "drivers can exercise the published container images"
    )
    payload = yaml.safe_load(_VERIFY_DIGESTS_OVERLAY.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), "verify-digests overlay must be a YAML mapping"
    services = payload.get("services")
    assert isinstance(services, dict), "verify-digests overlay must declare services:"
    for name in ("sevn-proxy", "sevn-gateway"):
        service = services.get(name)
        assert isinstance(service, dict), f"verify-digests overlay missing service {name!r}"
        image = service.get("image")
        assert isinstance(image, str), (
            f"{name} must pin image: to a published-tag reference; got {image!r}"
        )
        assert "SEVN_VERIFY_IMAGE_TAG" in image, (
            f"{name} image must interpolate SEVN_VERIFY_IMAGE_TAG (the SHA tag "
            f"promoted by container-supply-chain); got {image!r}"
        )
        assert "IMAGE_REPOSITORY" in image, (
            f"{name} image must interpolate IMAGE_REPOSITORY; got {image!r}"
        )
        # The tags actually promoted by ``container-supply-chain`` live on
        # GHCR (``ghcr.io/${IMAGE_REPOSITORY}/<name>:${GITHUB_SHA}``); an
        # unprefixed reference resolves to ``docker.io`` and pulls fail,
        # which would block the C14.1 evidence job even though the images
        # are correctly published (mergecraft review 4886108618).
        assert image.startswith("ghcr.io/"), (
            f"{name} image must be published to GHCR (prefix 'ghcr.io/'); got {image!r}"
        )
        # The overlay does not redeclare ``build:`` — the driver switches
        # to ``--no-build`` when this overlay is active, so compose pulls
        # the published image instead of rebuilding from source. Plain
        # YAML works with the pre-commit ``check-yaml`` hook; ``!reset``
        # (compose merge) does not.


def test_ci_cd_exports_digest_overlay_env_to_verify_deployment() -> None:
    """F-Thermos-V1 — the tag-path job must opt the drivers into the overlay."""
    data = _load_yaml(_CI_CD)
    job = data["jobs"]["verify-deployment"]
    step_envs: list[dict[str, Any]] = []
    for step in job.get("steps", []):
        if not isinstance(step, dict):
            continue
        env = step.get("env")
        if isinstance(env, dict):
            step_envs.append(env)
    # Step envs are unmerged; pull from job env too.
    job_env = job.get("env") or {}
    assert any(
        str(env.get("SEVN_VERIFY_IMAGE_OVERLAY", "")) == "1" for env in (job_env, *step_envs)
    ), (
        "verify-deployment must set SEVN_VERIFY_IMAGE_OVERLAY=1 on the tag path "
        "so the drivers actually exercise the published container images "
        "(mergecraft review 3737950464)"
    )
    # The overlay image interpolates SEVN_VERIFY_IMAGE_TAG; the workflow
    # must export github.sha into that env so the merged overlay pulls the
    # SHA-tagged image promoted by container-supply-chain.
    assert any(
        "${{ github.sha }}" in str(env.get("SEVN_VERIFY_IMAGE_TAG", ""))
        or str(env.get("SEVN_VERIFY_IMAGE_TAG", "")).startswith("github.sha")
        for env in (job_env, *step_envs)
    ), (
        "verify-deployment must set SEVN_VERIFY_IMAGE_TAG=${{ github.sha }} "
        "so the digest overlay references the SHA-tagged image"
    )


def test_verify_deployment_phase6_needs_include_verify_deployment() -> None:
    """F-Thermos-V1 — phase6's download-artifact cannot race verify-deployment's upload.

    Job-level ``needs`` is the only ordering guarantee in GitHub Actions; a
    missing entry turns into a hard ``download-artifact`` failure the moment
    the deploy phases land and phase6 actually runs.
    """
    data = _load_yaml(_CI_CD)
    phase6 = data["jobs"]["phase6"]
    needs = phase6.get("needs")
    assert isinstance(needs, list), "phase6 must declare a list-form needs:"
    assert "verify-deployment" in needs, (
        "phase6 needs must include verify-deployment so the deployment "
        "evidence download is ordered after the upload (mergecraft review "
        "3737950458)"
    )


def test_verify_deployment_permissions_include_packages_write() -> None:
    """F-Thermos-V1 — the cleanup step calls ghcr packages API; needs ``packages: write``."""
    data = _load_yaml(_CI_CD)
    job = data["jobs"]["verify-deployment"]
    perms = job.get("permissions")
    assert isinstance(perms, dict), "verify-deployment must declare permissions:"
    assert perms.get("packages") == "write", (
        "verify-deployment permissions must include packages: write so "
        "delete_quarantine_tags (gh api DELETE on GHCR package versions) "
        "is not silently 403'd under continue-on-error: true "
        "(mergecraft review 3737950445)"
    )


def test_verify_digests_overlay_merges_to_pulled_image() -> None:
    """F-Thermos-V1 — when the overlay env is set, the driver compose argv pulls the digest.

    Source-level guard: ``_compose_base`` must append the overlay path and
    ``_compose_up_args`` must switch from ``--build`` to ``--no-build`` so
    compose pulls the published image instead of rebuilding from source.
    """
    source = _VERIFY_SCRIPT.read_text(encoding="utf-8")
    assert "VERIFY_DIGESTS_COMPOSE" in source, (
        "verify_deployment.py must declare VERIFY_DIGESTS_COMPOSE so the "
        "drivers can find the digest overlay"
    )
    assert "_compose_base" in source, (
        "verify_deployment.py must define _compose_base to append the "
        "digest overlay when SEVN_VERIFY_IMAGE_OVERLAY=1 is set"
    )
    assert "_compose_up_args" in source, (
        "verify_deployment.py must define _compose_up_args so the up "
        "command switches from --build to --no-build when the overlay is "
        "active (the overlay drops build: with !reset null)"
    )
    # Both helpers must read SEVN_VERIFY_IMAGE_OVERLAY to keep the seam
    # opt-in (local dev has no published digest to pull).
    overlay_window = source[
        source.index("_verify_image_overlay_path") : source.index("_verify_image_overlay_path")
        + 2400
    ]
    assert "SEVN_VERIFY_IMAGE_OVERLAY" in overlay_window, (
        "_compose_base / _compose_up_args must read SEVN_VERIFY_IMAGE_OVERLAY"
    )


def test_verify_deployment_sandbox_pull_step_present() -> None:
    """Mergecraft review 3738385557 — sandbox image must be pullable on a fresh runner.

    ``drive_sandbox_spawn`` and ``drive_cancellation_cleanup`` do
    ``docker image inspect`` and exit ``driver_unavailable`` (status 2)
    when the image is missing; under D52 that fail-the-tag exit is the
    exact silent-no-op failure mode this PR exists to close. The only
    path to an inspectable image on a fresh release runner is a
    ``docker pull`` step before ``make verify-deployment`` — building
    from source would skip the published image and defeat C14.1.
    """
    data = _load_yaml(_CI_CD)
    job = data["jobs"]["verify-deployment"]
    steps = job.get("steps", [])
    pull_steps = [
        step
        for step in steps
        if isinstance(step, dict) and "docker pull" in (step.get("run") or "")
    ]
    assert pull_steps, (
        "verify-deployment must include a `docker pull` step for the "
        "published sandbox image; without it drive_sandbox_spawn exits "
        "driver_unavailable on a fresh runner and D52 fails the tag gate "
        "(mergecraft review 3738385557)"
    )
    # The pull must reference both IMAGE_REPOSITORY and SANDBOX_DIGEST so
    # it pins the exact promoted digest, not a mutable tag. The refs can
    # be interpolated in the step's ``env`` block (built into a local
    # var like ``SANDBOX_IMAGE_REF``) or inlined in ``run``; accept either.
    pull_runs = [(s.get("run") or "") for s in pull_steps]
    pull_envs = [(s.get("env") or {}) for s in pull_steps if isinstance(s.get("env"), dict)]
    pull_text = "\n".join(pull_runs + [str(e) for env in pull_envs for e in (env,)])
    # Job-level env vars (set on the parent job env:) are inherited into
    # every step's shell environment, so `${IMAGE_REPOSITORY}` and
    # `${SANDBOX_DIGEST}` expand at runtime even if they are not spelled
    # inside the pull step's own env block. Allow both forms.
    job_env = job.get("env") or {}
    repo_in_step = "IMAGE_REPOSITORY" in pull_text
    repo_in_job = "IMAGE_REPOSITORY" in job_env
    digest_in_step = "SANDBOX_DIGEST" in pull_text
    digest_in_job = "SANDBOX_DIGEST" in job_env
    assert repo_in_step or repo_in_job, (
        "sandbox pull step (or its job-level env) must reference "
        "IMAGE_REPOSITORY so the pulled ref is the promoted digest "
        "(mergecraft review 3738385557)"
    )
    assert digest_in_step or digest_in_job, (
        "sandbox pull step (or its job-level env) must reference "
        "SANDBOX_DIGEST so the pulled ref is the promoted digest "
        "(mergecraft review 3738385557)"
    )


def test_verify_deployment_sandbox_image_env_override() -> None:
    """Mergecraft review 3738385557 / 3740249068 — driver must target the published image.

    ``drive_sandbox_spawn`` defaults to ``sevn-sandbox:local``, which is
    only present after ``make docker-build-ci``; on a CI runner with no
    local build it inspects absent and returns ``driver_unavailable``.
    The job-level env must wire ``SEVN_VERIFY_SANDBOX_IMAGE`` to the
    promoted GHCR digest so the driver exercises the C14.1 evidence
    path against what was actually published.

    F-PR-1 (mergecraft review 3740249068) relaxed the structural shape
    of that override: GHA does not recursively expand POSIX variables
    inside ``env:`` values, so the literal
    ``ghcr.io/${IMAGE_REPOSITORY}/sandbox@${SANDBOX_DIGEST}`` is no
    longer allowed in a step ``env:``. The contract is now satisfied
    when either (a) the value is exported via ``$GITHUB_ENV`` in a
    preceding ``run:`` step, or (b) the consuming ``run:`` shell builds
    the ref inline. Both are acceptable so long as no unexpanded
    ``${...}`` substitution leaks into an env value (see
    ``test_verify_deployment_env_values_have_no_unexpanded_shell_vars``).
    """
    data = _load_yaml(_CI_CD)
    job = data["jobs"]["verify-deployment"]
    job_env = job.get("env") or {}
    step_envs: list[dict[str, Any]] = []
    step_runs: list[str] = []
    for step in job.get("steps", []):
        if not isinstance(step, dict):
            continue
        env = step.get("env")
        if isinstance(env, dict):
            step_envs.append(env)
        run = step.get("run") or ""
        if isinstance(run, str):
            step_runs.append(run)
    merged = (job_env, *step_envs)
    # Job-level IMAGE_REPOSITORY + SANDBOX_DIGEST (set above for the pull
    # step) must be inherited so the SEVN_VERIFY_SANDBOX_IMAGE override
    # below expands to the published digest ref, not an empty string.
    assert str(job_env.get("IMAGE_REPOSITORY", "")).startswith("${{"), (
        "verify-deployment job env must export IMAGE_REPOSITORY from "
        "publish-ghcr.outputs.image_repository (mergecraft review 3738385557)"
    )
    assert str(job_env.get("SANDBOX_DIGEST", "")).startswith("${{"), (
        "verify-deployment job env must export SANDBOX_DIGEST from "
        "publish-ghcr.outputs.sandbox_digest so SEVN_VERIFY_SANDBOX_IMAGE "
        "expands to a real ref (mergecraft review 3738385557)"
    )
    direct_env_ok = any(
        "SEVN_VERIFY_SANDBOX_IMAGE" in env
        and "ghcr.io/" in str(env.get("SEVN_VERIFY_SANDBOX_IMAGE", ""))
        and "SANDBOX_DIGEST" in str(env.get("SEVN_VERIFY_SANDBOX_IMAGE", ""))
        for env in merged
    )
    github_env_ok = any(
        "SEVN_VERIFY_SANDBOX_IMAGE=" in run
        and "ghcr.io/" in run
        and "${SANDBOX_DIGEST}" in run
        and "GITHUB_ENV" in run
        for run in step_runs
    )
    assert direct_env_ok or github_env_ok, (
        "verify-deployment must set SEVN_VERIFY_SANDBOX_IMAGE to the "
        "published GHCR digest (ghcr.io/.../sandbox@${SANDBOX_DIGEST}) so "
        "drive_sandbox_spawn has an inspectable image on the release runner "
        "(mergecraft review 3738385557). Either export the value via "
        "$GITHUB_ENV in a `run:` step (F-PR-1 shape) or keep it as a "
        "literal step env value (the original shape)."
    )


def test_verify_deployment_does_not_export_dead_digest_vars() -> None:
    """Mergecraft review 3738385601 — no driver reads SANDBOX_DIGEST / PROXY_DIGEST / GATEWAY_*.

    ``scripts/verify_deployment.py`` only reads ``SEVN_VERIFY_IMAGE_OVERLAY``,
    ``SEVN_VERIFY_IMAGE_TAG``, and ``SEVN_VERIFY_SANDBOX_IMAGE``. Exporting
    the raw ``*_DIGEST`` outputs in the step env clutters the diff and
    suggests the drivers use them; keeping them dead makes the seam
    misleading. This test asserts the dead vars are gone from the step
    that runs ``make verify-deployment`` (they were removed from the
    container-supply-chain step earlier; this locks the same hygiene on
    verify-deployment).
    """
    data = _load_yaml(_CI_CD)
    job = data["jobs"]["verify-deployment"]
    dead_vars = ("SANDBOX_DIGEST", "PROXY_DIGEST", "GATEWAY_DIGEST")
    for step in job.get("steps", []):
        if not isinstance(step, dict):
            continue
        env = step.get("env")
        if not isinstance(env, dict):
            continue
        if "make verify-deployment" not in (step.get("run") or ""):
            continue
        leaked = [v for v in dead_vars if v in env]
        assert not leaked, (
            "verify-deployment step env must not export dead "
            f"{', '.join(dead_vars)} vars — no driver reads them "
            "(mergecraft review 3738385601); leaked: {leaked}"
        )


# ---------------------------------------------------------------------------
# F-PR-1 — IMAGE_REPOSITORY / SANDBOX_DIGEST must not leak as literal strings
# into step env values. GitHub Actions does NOT recursively expand shell
# syntax inside ``env:`` values, so a value like
# ``ghcr.io/${IMAGE_REPOSITORY}/sandbox@${SANDBOX_DIGEST}`` reaches Python
# with the dollar-brace text intact and ``docker pull`` / the driver both
# fail. The fix is to build the ref in ``run:`` and either export it into
# $GITHUB_ENV or assign it into the shell command directly.
# ---------------------------------------------------------------------------


def _verify_deployment_step_env_strings() -> list[tuple[str, dict[str, Any]]]:
    """Return ``(step_name, env_dict)`` pairs for every step in ``verify-deployment``."""
    data = _load_yaml(_CI_CD)
    job = data["jobs"]["verify-deployment"]
    out: list[tuple[str, dict[str, Any]]] = []
    for step in job.get("steps", []):
        if not isinstance(step, dict):
            continue
        env = step.get("env")
        if not isinstance(env, dict):
            continue
        out.append((str(step.get("name", "")), env))
    return out


def test_verify_deployment_env_values_have_no_unexpanded_shell_vars() -> None:
    """F-PR-1 — no step env value may contain a literal ``${...}`` substitution.

    GitHub Actions evaluates ``${{ ... }}`` expressions inside ``env:``
    values once but does NOT then re-expand POSIX shell variables such
    as ``${IMAGE_REPOSITORY}`` or ``${SANDBOX_DIGEST}``. The result is
    passed verbatim into the consuming process — so a Python string
    comparison against a real digest ref never matches and ``docker
    pull`` is handed a non-existent ref. Any unexpanded shell variable
    inside an env value is a bug (mergecraft review 3740249068).
    """
    bad: list[str] = []
    shell_var_re = re.compile(r"\$\{[A-Z_][A-Z0-9_]*\}")
    for step_name, env in _verify_deployment_step_env_strings():
        for key, value in env.items():
            if not isinstance(value, str):
                continue
            if shell_var_re.search(value):
                bad.append(f"{step_name}.env.{key}={value!r}")
    assert not bad, (
        "verify-deployment step env values must not contain unexpanded "
        "shell variables like ${IMAGE_REPOSITORY} / ${SANDBOX_DIGEST} — "
        "GitHub Actions does not recursively expand $env values, so the "
        "literal text leaks into Python and `docker pull` fails against "
        "a non-existent ref (mergecraft review 3740249068); bad: " + "; ".join(bad)
    )


def test_verify_deployment_sandbox_image_ref_is_built_at_runtime() -> None:
    """F-PR-1 — the sandbox-image ref must be assembled in ``run:`` shell, not env.

    The ``SEVN_VERIFY_SANDBOX_IMAGE`` value the driver reads must be the
    promoted GHCR digest ref, not a literal that Python sees as
    ``ghcr.io/${IMAGE_REPOSITORY}/sandbox@${SANDBOX_DIGEST}``. The clean
    shape is to build it inside ``run:`` (exporting to ``$GITHUB_ENV`` or
    inline) so the shell expands the variables. This test asserts that
    whatever path the workflow takes, the consuming step runs a shell
    command that contains the expanded variables (``docker pull
    ${SANDBOX_IMAGE_REF}`` or ``make verify-deployment`` preceded by a
    ``SANDBOX_IMAGE_REF=...`` export) — not just an env block with the
    unsubstituted literal.
    """
    data = _load_yaml(_CI_CD)
    job = data["jobs"]["verify-deployment"]
    pull_steps = [
        step
        for step in job.get("steps", [])
        if isinstance(step, dict) and "docker pull" in (step.get("run") or "")
    ]
    assert pull_steps, (
        "verify-deployment must include a `docker pull` step for the "
        "published sandbox image (see test_verify_deployment_sandbox_pull_step_present)"
    )
    # The sandbox pull must reference the SANDBOX_IMAGE_REF shell variable
    # (built inside the same step) — not a literal $... leak.
    for step in pull_steps:
        run = step.get("run") or ""
        assert "SANDBOX_IMAGE_REF" in run, (
            "sandbox pull step must build and consume $SANDBOX_IMAGE_REF "
            "via shell interpolation in `run:` (not via a literal "
            "ghcr.io/${IMAGE_REPOSITORY}/... value in `env:`); got "
            f"run={run[:200]!r}"
        )


# ---------------------------------------------------------------------------
# F-PR-2 — `make` exit-2 collision masks real driver failures as
# `driver_unavailable` on the daily cron. The Python driver
# (``scripts/verify_deployment.py``) emits ``VERIFY_OVERALL: <status> (exit
# <n>)`` and exits 0/1/2. ``make verify-deployment`` can return 2 for its own
# internal errors regardless of the underlying driver verdict, so a branch
# like ``if [ $rc -eq 2 ]; then exit 0; fi`` cannot reliably distinguish
# "cron runner without docker" (tolerated) from "driver verdict fail" (must
# fail). The fix is to invoke the python driver directly (or capture both
# ``make`` and ``python`` exit codes) so the cron path can route correctly.
# ---------------------------------------------------------------------------


def _cron_step_run() -> str:
    """Return the ``run:`` text of the cron verify-deployment step."""
    jobs = _jobs(_CI_SUPP)
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        if not _VERIFY_MAKE_RE.search(_job_blob(job)):
            continue
        for step in job.get("steps", []):
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if isinstance(run, str) and (
                "verify-deployment" in run or "verify_deployment.py" in run
            ):
                return run
    return ""


def test_cron_step_invokes_python_driver_directly() -> None:
    """F-PR-2 — cron path must inspect the driver verdict, not ``make``'s exit.

    The Python driver emits ``VERIFY_OVERALL: pass|fail|driver_unavailable``
    on stdout, and the cron routing logic must distinguish
    ``driver_unavailable`` (tolerated) from ``fail`` (must fail the gate).
    Going through ``make verify-deployment`` loses that distinction when
    ``make`` returns 2 for any non-recipe error, so a literal ``make
    verify-deployment`` invocation in the cron step is no longer
    sufficient — the cron step must invoke
    ``scripts/verify_deployment.py`` (or its runner) directly so its exit
    code reaches the branch logic intact (mergecraft review 3740249070).
    """
    run = _cron_step_run()
    assert run, (
        "ci-supplementary.yml cron path must include a step that runs the "
        "verify-deployment drivers (see test_ci_supplementary_runs_verify_deployment_on_daily_cron)"
    )
    has_python = "verify_deployment.py" in run
    assert has_python or "VERIFY_OVERALL" in run, (
        "cron step must invoke scripts/verify_deployment.py (or its "
        "runner) directly so the underlying exit code is distinguishable "
        "from `make`'s exit-2 recipe error. `make verify-deployment` "
        "alone collapses driver verdict to a single 0/1/2 with 2 "
        "ambiguous between `make` failure and `driver_unavailable` "
        "(mergecraft review 3740249070); got run: " + run[:400]
    )
