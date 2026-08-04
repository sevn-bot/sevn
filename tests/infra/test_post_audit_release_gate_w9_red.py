"""Post-audit Batch C W9 RED — release gate honesty (#172; D21, D22) and coverage (#179; D32).

Contracts (``about-sevn.bot/specs/25-cicd-full.md``): phase6 publishes ``draft: true`` until
deploy phases are real; ``delivery-chain`` rejects phase4/phase5 ``failure`` on tag builds;
workflow header does not advertise a full six-phase pipeline while phases 4-5 are stubs;
optional ``dev`` extra (``coverage`` / ``pytest-cov``) survives in-test ``uv sync`` from
skill install actions.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_CD = _REPO_ROOT / ".github" / "workflows" / "ci-cd.yml"
_EXECUTORS = _REPO_ROOT / "src" / "sevn" / "onboarding" / "install_actions" / "executors.py"


def _load_ci_cd_workflow() -> dict[str, Any]:
    data = yaml.safe_load(_CI_CD.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _delivery_chain_run_script() -> str:
    steps = _load_ci_cd_workflow()["jobs"]["delivery-chain"]["steps"]
    for step in steps:
        if step.get("name") == "Verify delivery chain results":
            run = step.get("run")
            assert isinstance(run, str)
            return run
    raise AssertionError("delivery-chain verify step missing")


def _phase6_release_step() -> dict[str, Any]:
    steps = _load_ci_cd_workflow()["jobs"]["phase6"]["steps"]
    for step in steps:
        uses = step.get("uses", "")
        if "softprops/action-gh-release" in uses:
            return step
    raise AssertionError("phase6 softprops/action-gh-release step missing")


def _deploy_phase_failure_tolerated_on_tag_build(script: str, phase: str) -> bool:
    """Return True when *phase* ``failure`` is accepted on tag builds (pre-W10 bug)."""
    marker = f'require_needs_impl "{phase}"'
    if marker not in script:
        return False
    if "workflow_dispatch" not in script:
        return True
    phase_block = script.split(marker, 1)[0]
    return "workflow_dispatch" not in phase_block[-400:]


def _workflow_text() -> str:
    return _CI_CD.read_text(encoding="utf-8")


def _uv_extra_sync_block() -> str:
    text = _EXECUTORS.read_text(encoding="utf-8")
    marker = 'if action.kind == "uv_extra":'
    assert marker in text
    return text.split(marker, 1)[1].split("\n    if action.kind", 1)[0]


@pytest.mark.xfail(reason="green after W10", strict=False)
def test_phase6_release_step_sets_draft_true() -> None:
    """W9.1 / #172: tagged releases must stay draft until deploy phases are honest."""
    step = _phase6_release_step()
    assert step.get("with", {}).get("draft") is True


@pytest.mark.xfail(reason="green after W10", strict=False)
@pytest.mark.parametrize("phase", ["phase4", "phase5"])
def test_delivery_chain_rejects_deploy_phase_failure_on_tag_build(phase: str) -> None:
    """W9.2 / D22: ``needs_impl_ok`` tolerance is dispatch-only, not on ``refs/tags/v*``."""
    script = _delivery_chain_run_script()
    assert not _deploy_phase_failure_tolerated_on_tag_build(script, phase), (
        f"{phase} failure must not pass delivery-chain on tag builds"
    )


@pytest.mark.xfail(reason="green after W10", strict=False)
def test_workflow_header_honest_while_deploy_phases_are_stubs() -> None:
    """W9.3 / D21: do not advertise a full six-phase pipeline while phase4/5 are stubs."""
    text = _workflow_text()
    deploy_stubs = "needs-implementation" in text and "Phase 4" in text and "Phase 5" in text
    misleading = bool(re.search(r"Six-phase delivery pipeline", text, re.IGNORECASE))
    assert not (deploy_stubs and misleading), (
        "ci-cd.yml must not claim a complete six-phase pipeline while deploy phases stub"
    )


@pytest.mark.xfail(reason="green after W12", strict=False)
def test_uv_extra_install_sync_preserves_optional_dev_extra() -> None:
    """W9.6 / #179 / D32: ``uv_extra`` sync must pass ``--extra dev`` when dev group exists."""
    block = _uv_extra_sync_block()
    assert '"--group", "dev"' in block or "'--group', 'dev'" in block
    assert '"--extra", "dev"' in block or "'--extra', 'dev'" in block
