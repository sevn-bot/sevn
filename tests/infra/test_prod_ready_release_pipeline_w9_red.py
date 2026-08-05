"""Prod-readiness Batch C W9 RED — release pipeline & supply chain (C2.*, C11.*, C12.3, C13.*).

Contracts (``about-sevn.bot/specs/25-cicd-full.md``; plan D44-D47):

- Aggregator job name states artifact publication, not delivery readiness (C2.1 → W10).
- ``phase2`` / ``phase3`` and ``needs_impl_ok`` are deleted (C2.2, D44 → W10).
- No ``:latest`` tag is written on a ``main`` push (C13.1 → W11).
- Publish pushes a quarantine tag only; stable tags are promoted by digest after scan
  (C12.3, D45 → W11).
- No ``curl … | sh`` under ``.github/`` or ``Makefile`` (C11.3 → W12).
- syft / trivy install via SHA-pinned actions (or checksum-verified downloads); ``uv``
  installer is version-pinned and checksum-verified (C11.1, C11.2, D46, D47 → W12).

Landed guards (C2.3 / C12.1 / C12.2 / C12.4) live in
``tests/infra/test_post_audit_release_gate_w9_red.py`` and
``tests/security/test_post_audit_trivy_allowlist_w9_red.py`` — do not re-assert them here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_CD = _REPO_ROOT / ".github" / "workflows" / "ci-cd.yml"
_MAKEFILE = _REPO_ROOT / "Makefile"
_GITHUB_DIR = _REPO_ROOT / ".github"

_CURL_PIPE_SH_RE = re.compile(
    r"(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b",
    re.IGNORECASE,
)
_SHA_PINNED_ACTION_RE = re.compile(r"@[0-9a-f]{40}\b", re.IGNORECASE)
_CHECKSUM_VERIFY_RE = re.compile(
    r"(sha256sum|shasum|sha256|checksum|cosign\s+verify)",
    re.IGNORECASE,
)
_UV_VERSION_PIN_RE = re.compile(
    r"(UV_VERSION\s*[:=]|astral\.sh/uv/(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))",
    re.IGNORECASE,
)
_QUARANTINE_TAG_RE = re.compile(r"quarantine", re.IGNORECASE)
_LATEST_TAG_RE = re.compile(r":latest\b")
_DIGEST_PROMOTE_RE = re.compile(
    r"(crane\s+copy|docker\s+buildx\s+imagetools|cosign\s+copy|skopeo\s+copy|"
    r"retag|promote\s+.*digest|by\s+digest)",
    re.IGNORECASE,
)

_IMAGE_BUILD_STEP_IDS = (
    "sandbox",
    "proxy",
    "gateway",
    "gateway_browser",
    "gateway_gui",
)


def _load_ci_cd_workflow() -> dict[str, Any]:
    data = yaml.safe_load(_CI_CD.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _delivery_chain_job() -> dict[str, Any]:
    jobs = _load_ci_cd_workflow()["jobs"]
    assert "delivery-chain" in jobs, "required aggregator job id delivery-chain missing"
    job = jobs["delivery-chain"]
    assert isinstance(job, dict)
    return job


def _delivery_chain_run_script() -> str:
    for step in _delivery_chain_job().get("steps", []):
        if step.get("name") == "Verify delivery chain results":
            run = step.get("run")
            assert isinstance(run, str)
            return run
    # After W10 rename the step name may change; fall back to the first run script.
    for step in _delivery_chain_job().get("steps", []):
        run = step.get("run")
        if isinstance(run, str) and ("require " in run or "needs_impl" in run or "PHASE1" in run):
            return run
    raise AssertionError("delivery-chain verify step missing")


def _publish_ghcr_build_steps() -> list[dict[str, Any]]:
    steps = _load_ci_cd_workflow()["jobs"]["publish-ghcr"]["steps"]
    found: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        uses = str(step.get("uses", ""))
        if "docker/build-push-action" not in uses:
            continue
        found.append(step)
    return found


def _publish_tag_blocks() -> dict[str, str]:
    """Map build-push step id → tags multiline string."""
    blocks: dict[str, str] = {}
    for step in _publish_ghcr_build_steps():
        step_id = step.get("id")
        tags = step.get("with", {}).get("tags")
        if isinstance(step_id, str) and isinstance(tags, str):
            blocks[step_id] = tags
    return blocks


def _ensure_uv_makefile_block() -> str:
    text = _MAKEFILE.read_text(encoding="utf-8")
    marker = "ensure-uv:"
    assert marker in text, "Makefile ensure-uv target missing"
    after = text.split(marker, 1)[1]
    # Next Make target at column 0 ending with ':'
    next_target = re.search(r"\n[A-Za-z0-9_.-]+:", after)
    return after[: next_target.start()] if next_target else after


def _iter_github_and_makefile_texts() -> list[tuple[Path, str]]:
    texts: list[tuple[Path, str]] = [(_MAKEFILE, _MAKEFILE.read_text(encoding="utf-8"))]
    allowed_suffixes = {".yml", ".yaml", ".sh", ".md"}
    for path in sorted(_GITHUB_DIR.rglob("*")):
        if not path.is_file():
            continue
        # Workflows + shell helpers under .github/; skip binary / large blobs.
        if path.suffix.lower() not in allowed_suffixes and path.name != "Makefile":
            continue
        try:
            texts.append((path, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return texts


def _install_step(name_substr: str) -> dict[str, Any]:
    steps = _load_ci_cd_workflow()["jobs"]["container-supply-chain"]["steps"]
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_name = str(step.get("name", ""))
        if name_substr.lower() in step_name.lower():
            return step
    raise AssertionError(f"container-supply-chain step matching {name_substr!r} missing")


def _step_is_sha_pinned_action_or_checksum_verified(step: dict[str, Any]) -> bool:
    uses = step.get("uses")
    if isinstance(uses, str) and _SHA_PINNED_ACTION_RE.search(uses):
        return True
    run = step.get("run")
    return (
        isinstance(run, str)
        and bool(_CHECKSUM_VERIFY_RE.search(run))
        and not bool(_CURL_PIPE_SH_RE.search(run))
    )


# ---------------------------------------------------------------------------
# W9.1 — aggregator honesty (C2.1 → W10)
# ---------------------------------------------------------------------------


def test_required_aggregator_name_states_publication_not_delivery() -> None:
    """W9.1 / C2.1: required check name must not imply deployment readiness."""
    name = _delivery_chain_job().get("name")
    assert isinstance(name, str), "delivery-chain job name missing"
    assert name.strip(), "delivery-chain job name empty"
    lowered = name.lower()
    assert "delivery" not in lowered, (
        f"aggregator name {name!r} still implies delivery readiness — "
        "rename to an artifact-publication gate (C2.1)"
    )
    assert "publication" in lowered or "artifact" in lowered or "publish" in lowered, (
        f"aggregator name {name!r} must state artifact publication (C2.1)"
    )


# ---------------------------------------------------------------------------
# W9.2 — delete tolerated stubs (C2.2, D44 → W10)
# ---------------------------------------------------------------------------


def test_phase2_and_phase3_jobs_absent() -> None:
    """W9.2 / D44: Dev deploy/smoke stubs are deleted, not permanently tolerated."""
    jobs = _load_ci_cd_workflow()["jobs"]
    assert "phase2" not in jobs, "phase2 must be deleted (C2.2 / D44)"
    assert "phase3" not in jobs, "phase3 must be deleted (C2.2 / D44)"


def test_needs_impl_ok_escape_hatch_absent() -> None:
    """W9.2 / D44: required aggregator must not classify ``failure`` as OK."""
    script = _delivery_chain_run_script()
    assert "needs_impl_ok" not in script, "needs_impl_ok must be deleted (C2.2 / D44)"
    assert "require_needs_impl" not in script, "require_needs_impl must be deleted (C2.2 / D44)"
    # P3: no annotation that tolerates failure in the required check.
    assert not re.search(r"\bfailure\b.*\b(allowed|ok|tolerat)", script, re.IGNORECASE), (
        "required aggregator must not tolerate failure results"
    )


# ---------------------------------------------------------------------------
# W9.3 — no :latest from main (C13.1 → W11)
# ---------------------------------------------------------------------------


def test_publish_ghcr_does_not_write_latest_tag() -> None:
    """W9.3 / C13.1: while deploy phases are stubs, ``:latest`` is not published."""
    blocks = _publish_tag_blocks()
    assert set(blocks) >= set(_IMAGE_BUILD_STEP_IDS), (
        f"expected build-push ids {_IMAGE_BUILD_STEP_IDS}, got {sorted(blocks)}"
    )
    offenders: list[str] = []
    for step_id, tags in blocks.items():
        if _LATEST_TAG_RE.search(tags):
            offenders.append(step_id)
    assert offenders == [], (
        f"publish-ghcr still writes :latest for {offenders} — "
        "SHA (and latest only behind a real gate) after quarantine (C13.1 / D45)"
    )


# ---------------------------------------------------------------------------
# W9.4 — quarantine then promote by digest (C12.3, D45 → W11)
# ---------------------------------------------------------------------------


def test_publish_ghcr_pushes_quarantine_tags_only() -> None:
    """W9.4 / C12.3 / D45: build-push writes quarantine tags, not consumable stables."""
    blocks = _publish_tag_blocks()
    assert blocks, "publish-ghcr has no build-push tag blocks"
    bare_sha_re = re.compile(r":\$\{\{\s*github\.sha\s*\}\}")
    for step_id, tags in blocks.items():
        tag_lines = [line.strip() for line in tags.splitlines() if line.strip()]
        assert tag_lines, f"{step_id} has empty tags block"
        assert any(_QUARANTINE_TAG_RE.search(line) for line in tag_lines), (
            f"{step_id} must push a quarantine tag (C12.3 / D45); got:\n{tags}"
        )
        for line in tag_lines:
            assert not _LATEST_TAG_RE.search(line), (
                f"{step_id} must not push :latest before scan/promote (C12.3 / C13.1)"
            )
            if bare_sha_re.search(line) and not _QUARANTINE_TAG_RE.search(line):
                raise AssertionError(
                    f"{step_id} still pushes a bare SHA tag before scan: {line!r} (C12.3)"
                )


def test_stable_tags_promoted_by_digest_after_scan() -> None:
    """W9.4 / D45: after container-supply-chain, promote SHA (etc.) by digest."""
    jobs = _load_ci_cd_workflow()["jobs"]
    promote_hits: list[str] = []
    for key, job in jobs.items():
        if not isinstance(job, dict):
            continue
        label = f"job:{key}"
        if "promote" in key.lower() or "promote" in str(job.get("name", "")).lower():
            promote_hits.append(label)
            continue
        for step in job.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            step_name = str(step.get("name", ""))
            run = step.get("run") if isinstance(step.get("run"), str) else ""
            if "promote" in step_name.lower() or _DIGEST_PROMOTE_RE.search(run):
                promote_hits.append(f"{key}/{step_name or 'run'}")
    assert promote_hits, "no digest-promotion job/step found after quarantine publish (C12.3 / D45)"


# ---------------------------------------------------------------------------
# W9.5 — no curl|sh under .github/ or Makefile (C11.3 → W12)
# ---------------------------------------------------------------------------


def test_no_curl_pipe_sh_under_github_or_makefile() -> None:
    """W9.5 / C11.3: ``curl|sh`` / ``wget|sh`` must not appear in release installers."""
    offenders: list[str] = []
    for path, text in _iter_github_and_makefile_texts():
        if _CURL_PIPE_SH_RE.search(text):
            offenders.append(str(path.relative_to(_REPO_ROOT)))
    assert offenders == [], (
        "curl|sh / wget|sh still present in: " + ", ".join(offenders) + " (C11.3)"
    )


# ---------------------------------------------------------------------------
# W9.6 — pinned/verified installers (C11.1, C11.2, D46, D47 → W12)
# ---------------------------------------------------------------------------


def test_syft_and_trivy_install_via_pinned_action_or_checksum() -> None:
    """W9.6 / C11.1 / D46: match the in-repo cosign SHA-pinned action pattern."""
    for tool in ("syft", "trivy"):
        step = _install_step(f"Install {tool}")
        assert _step_is_sha_pinned_action_or_checksum_verified(step), (
            f"{tool} install must use a SHA-pinned action or checksum-verified download "
            f"(C11.1 / D46); step={step!r}"
        )
        run = step.get("run")
        if isinstance(run, str):
            assert not _CURL_PIPE_SH_RE.search(run), (
                f"{tool} install still pipes curl/wget to sh (C11.1)"
            )


def test_uv_installer_is_version_pinned_and_checksum_verified() -> None:
    """W9.6 / C11.2 / D47: ``make ensure-uv`` must pin and verify before execution."""
    block = _ensure_uv_makefile_block()
    assert not _CURL_PIPE_SH_RE.search(block), (
        "ensure-uv still uses curl|sh without pin+verify (C11.2 / D47)"
    )
    assert _UV_VERSION_PIN_RE.search(block), "ensure-uv must pin a uv version (C11.2 / D47)"
    assert _CHECKSUM_VERIFY_RE.search(block), (
        "ensure-uv must checksum-verify the installer before running it (C11.2 / D47)"
    )
