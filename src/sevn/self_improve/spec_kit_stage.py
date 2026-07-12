"""Optional spec-kit plan stage before patch author (`specs/33-self-improvement.md` §4.1 stage 4a).

Module: sevn.self_improve.spec_kit_stage
Depends: json, pathlib, sevn.config.workspace_config, sevn.evolution.spec_kit,
    sevn.self_improve.paths

Exports:
    improve_spec_kit_dir — per-job spec-kit artefact directory.
    write_context_pack — persist ``context_pack.json`` for ``speckit.plan``.
    spec_kit_plan_stage_enabled — whether plan-before-patch is active.
    run_improve_spec_kit_plan — allowlisted ``plan`` subprocess in job bundle.
    plan_hitl_blocks_patch — whether MC plan approval is still required.
    mark_plan_approved — write approval marker after operator review.
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 — runtime job bundle paths
from typing import TYPE_CHECKING, Any

from sevn.config.workspace_config import SelfImproveSpecKitConfig, WorkspaceConfig
from sevn.evolution.spec_kit import load_constitution, run_specify_allowlisted

if TYPE_CHECKING:
    from sevn.workspace.layout import WorkspaceLayout


def improve_spec_kit_dir(job_bundle: Path) -> Path:
    """Return ``<job_bundle>/spec-kit`` per [`specs/33-self-improvement.md`](specs/33) §3.5.

    Args:
        job_bundle (Path): ``.sevn/improve/<job_id>/`` directory.

    Returns:
        Path: Spec-kit artefact subdirectory (may not exist yet).

    Examples:
        >>> improve_spec_kit_dir(Path("/w/.sevn/improve/j1")).name
        'spec-kit'
    """
    return job_bundle / "spec-kit"


def _effective_si_spec_kit(ws: WorkspaceConfig) -> SelfImproveSpecKitConfig:
    """Return ``self_improve.spec_kit`` with defaults when absent.

    Args:
        ws (WorkspaceConfig): Parsed workspace.

    Returns:
        SelfImproveSpecKitConfig: Effective subtree.

    Examples:
        >>> _effective_si_spec_kit(WorkspaceConfig.minimal()).enabled
        False
    """
    si = ws.self_improve
    if si is not None and si.spec_kit is not None:
        return si.spec_kit
    return SelfImproveSpecKitConfig()


def spec_kit_plan_stage_enabled(ws: WorkspaceConfig) -> bool:
    """Return whether the improver must run ``speckit.plan`` before ``patch_author``.

    Args:
        ws (WorkspaceConfig): Parsed workspace.

    Returns:
        bool: ``True`` when ``self_improve.spec_kit.enabled`` and
            ``require_plan_before_patch``.

    Examples:
        >>> spec_kit_plan_stage_enabled(WorkspaceConfig.minimal())
        False
    """
    sk = _effective_si_spec_kit(ws)
    return bool(sk.enabled and sk.require_plan_before_patch)


def write_context_pack(
    job_bundle: Path,
    *,
    job_id: str,
    shortlist: dict[str, Any],
) -> Path:
    """Write ``context_pack.json`` beside the shortlist for spec-kit planning.

    Args:
        job_bundle (Path): Per-job artefact directory.
        job_id (str): Improve job id.
        shortlist (dict[str, Any]): Parsed ``shortlist.json`` body.

    Returns:
        Path: Written ``context_pack.json`` path.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     bundle = Path(td)
        ...     path = write_context_pack(
        ...         bundle,
        ...         job_id="j1",
        ...         shortlist={"candidates": [], "schema_version": 1},
        ...     )
        ...     path.name == "context_pack.json"
        True
    """
    job_bundle.mkdir(parents=True, exist_ok=True)
    pack_path = job_bundle / "context_pack.json"
    payload = {
        "schema_version": 1,
        "job_id": job_id,
        "shortlist": shortlist,
    }
    pack_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    spec_dir = improve_spec_kit_dir(job_bundle)
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "context_pack.json").write_text(
        pack_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return pack_path


def _write_plan_stub(
    plan_path: Path,
    *,
    job_id: str,
    constitution_excerpt: str,
    context_pack_path: Path,
) -> None:
    """Materialise a deterministic ``plan.md`` when the CLI is dry-run or absent.

    Args:
        plan_path (Path): Target plan artefact path.
        job_id (str): Improve job id.
        constitution_excerpt (str): First lines of constitution for context.
        context_pack_path (Path): On-disk context pack path.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     p = Path(td) / "plan.md"
        ...     _write_plan_stub(
        ...         p,
        ...         job_id="j",
        ...         constitution_excerpt="# c",
        ...         context_pack_path=Path(td) / "context_pack.json",
        ...     )
        ...     "j" in p.read_text(encoding="utf-8")
        True
    """
    excerpt = constitution_excerpt.strip().splitlines()[:12]
    body = "\n".join(excerpt)
    plan_path.write_text(
        (
            f"# Self-improve plan — {job_id}\n\n"
            f"## Constitution (excerpt)\n\n{body}\n\n"
            f"## Context\n\n"
            f"- context_pack: `{context_pack_path.name}`\n"
            f"- patch stage must respect `allowed_globs` and eval graph.\n"
        ),
        encoding="utf-8",
    )


def run_improve_spec_kit_plan(
    *,
    job_id: str,
    job_bundle: Path,
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    owner_principal: str = "owner",
    dry_run: bool | None = None,
) -> Path:
    """Run allowlisted ``plan`` under ``<job_bundle>/spec-kit/`` and ensure ``plan.md`` exists.

    Args:
        job_id (str): Improve job correlation id for audit rows.
        job_bundle (Path): Per-job artefact directory.
        ws (WorkspaceConfig): Workspace config.
        layout (WorkspaceLayout): Resolved layout.
        owner_principal (str): Owner principal for spec-kit audit.
        dry_run (bool | None): Force dry-run; ``None`` uses workspace default.

    Returns:
        Path: ``plan.md`` path under the job spec-kit directory.

    Raises:
        RuntimeError: When ``require_plan_before_patch`` is on and planning fails.

    Examples:
        >>> run_improve_spec_kit_plan.__name__
        'run_improve_spec_kit_plan'
    """
    spec_dir = improve_spec_kit_dir(job_bundle)
    spec_dir.mkdir(parents=True, exist_ok=True)
    plan_path = spec_dir / "plan.md"
    context_pack = job_bundle / "context_pack.json"
    if not context_pack.is_file():
        write_context_pack(job_bundle, job_id=job_id, shortlist={"candidates": []})

    result = run_specify_allowlisted(
        "plan",
        [],
        spec_dir,
        owner_principal=owner_principal,
        ws=ws,
        layout=layout,
        job_id=job_id,
        dry_run=dry_run,
    )
    constitution = load_constitution(ws, layout)
    if not plan_path.is_file() or result.status in ("dry_run", "rejected"):
        _write_plan_stub(
            plan_path,
            job_id=job_id,
            constitution_excerpt=constitution.text,
            context_pack_path=context_pack,
        )
    if result.status == "error" and spec_kit_plan_stage_enabled(ws):
        msg = f"spec_kit plan failed: {result.detail or result.stderr}"
        raise RuntimeError(msg)
    return plan_path


def plan_hitl_blocks_patch(job_bundle: Path, ws: WorkspaceConfig) -> bool:
    """Return whether patch stage must wait for MC plan approval.

    Args:
        job_bundle (Path): Per-job artefact directory.
        ws (WorkspaceConfig): Parsed workspace.

    Returns:
        bool: ``True`` when ``require_hitl_for_plan`` and no ``plan_approved`` marker.

    Examples:
        >>> plan_hitl_blocks_patch(Path("/tmp/x"), WorkspaceConfig.minimal())
        False
    """
    sk = _effective_si_spec_kit(ws)
    if not sk.require_hitl_for_plan:
        return False
    approved = improve_spec_kit_dir(job_bundle) / "plan_approved"
    return not approved.is_file()


def mark_plan_approved(job_bundle: Path) -> Path:
    """Write the HITL approval marker after operator review.

    Args:
        job_bundle (Path): Per-job artefact directory.

    Returns:
        Path: Marker file path.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     p = mark_plan_approved(Path(td))
        ...     p.is_file()
        True
    """
    spec_dir = improve_spec_kit_dir(job_bundle)
    spec_dir.mkdir(parents=True, exist_ok=True)
    marker = spec_dir / "plan_approved"
    marker.write_text('{"approved": true}\n', encoding="utf-8")
    return marker


__all__ = [
    "improve_spec_kit_dir",
    "mark_plan_approved",
    "plan_hitl_blocks_patch",
    "run_improve_spec_kit_plan",
    "spec_kit_plan_stage_enabled",
    "write_context_pack",
]
