"""Docker evaluation launcher (`specs/33-self-improvement.md` §4.3).

Module: sevn.self_improve.eval
Depends: json, os, pathlib, sevn.config.defaults, sevn.config.workspace_config, sevn.self_improve.eval.replay

Exports:
    ImproveJobResult — aggregate eval graph outcome for job-store wiring.
    eval_docker_required — whether workspace config requires Docker eval.
    eval_in_process_override — host bypass via ``SEVN_IMPROVE_EVAL_IN_PROCESS``.
    eval_report_passed — read passing flag from eval_report.json.
    golden_routing_fixture_path — resolve Wave 5 corpus on disk.
    resolve_repo_root — locate checkout root for golden corpus.
    run_docker_eval_graph — public alias; Docker or in-process per config.
    run_eval_graph — in-process evaluation graph (segments + eval_report.json).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sevn.config.defaults import DEFAULT_SELF_IMPROVE_EVAL_DOCKER_REQUIRED
from sevn.self_improve.eval.baseline import (
    baseline_path_for_job_bundle,
    baseline_section_for_report,
    compute_metric_deltas,
    load_last_known_good,
)
from sevn.self_improve.eval.replay import (
    DEFAULT_INTENT_MATCH_THRESHOLD,
    EvalSegmentResult,
    GoldenRoutingReplayResult,
    LiveReplaySmokeResult,
    run_golden_routing_replay,
    run_live_replay_smoke,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

GOLDEN_ROUTING_CORPUS_REL = "tests/fixtures/triager/golden_routing.jsonl"


def golden_routing_fixture_path(*, repo_root: Path) -> Path:
    """Resolve the Wave 5 golden routing corpus under a repository root.

    Args:
        repo_root (Path): Checkout root containing ``tests/fixtures/triager/``.

    Returns:
        Path: Absolute path to ``golden_routing.jsonl``.

    Examples:
        >>> from pathlib import Path
        >>> golden_routing_fixture_path(repo_root=Path("/repo")).as_posix()
        '/repo/tests/fixtures/triager/golden_routing.jsonl'
    """
    return repo_root / GOLDEN_ROUTING_CORPUS_REL


@dataclass(frozen=True, slots=True)
class ImproveJobResult:
    """Aggregate outcome after running the improve evaluation graph."""

    passed: bool
    eval_report_path: Path
    segments: tuple[EvalSegmentResult, ...]


def resolve_repo_root(explicit: Path | None = None) -> Path:
    """Locate the repository root containing the golden routing corpus.

    Args:
        explicit (Path | None): Caller-provided root when known.

    Returns:
        Path: Best-effort repository checkout root.

    Examples:
        >>> from pathlib import Path
        >>> resolve_repo_root(Path("/repo")).as_posix()
        '/repo'
    """
    if explicit is not None:
        return explicit
    env = os.environ.get("SEVN_REPO_ROOT", "").strip()
    if env:
        return Path(env)
    here = Path.cwd()
    for candidate in (here, *here.parents):
        if golden_routing_fixture_path(repo_root=candidate).is_file():
            return candidate
    return here


def eval_docker_required(workspace: WorkspaceConfig) -> bool:
    """Return whether workspace config requires Docker-isolated eval.

    Args:
        workspace (WorkspaceConfig): Active workspace configuration.

    Returns:
        bool: ``True`` when ``self_improve.eval.docker_required`` defaults apply.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> eval_docker_required(WorkspaceConfig.minimal())
        True
    """
    si = workspace.self_improve
    if si is None or si.eval is None:
        return DEFAULT_SELF_IMPROVE_EVAL_DOCKER_REQUIRED
    return si.eval.docker_required


def eval_in_process_override() -> bool:
    """Return whether host in-process eval is explicitly allowed.

    Returns:
        bool: ``True`` when ``SEVN_IMPROVE_EVAL_IN_PROCESS`` is a truthy token.

    Examples:
        >>> import os
        >>> os.environ["SEVN_IMPROVE_EVAL_IN_PROCESS"] = "1"
        >>> eval_in_process_override()
        True
        >>> del os.environ["SEVN_IMPROVE_EVAL_IN_PROCESS"]
        >>> eval_in_process_override()
        False
    """
    token = os.environ.get("SEVN_IMPROVE_EVAL_IN_PROCESS", "").strip().lower()
    return token in ("1", "true", "yes")


def _run_unit_segment() -> EvalSegmentResult:
    """Smoke-import self-improve modules as the lightweight unit segment.

    Returns:
        EvalSegmentResult: ``passed`` when core modules import cleanly.

    Examples:
        >>> _run_unit_segment().name
        'unit'
    """
    try:
        import sevn.self_improve.facade
        import sevn.self_improve.sampler  # noqa: F401
    except ImportError as exc:
        return EvalSegmentResult(name="unit", status="failed", detail=str(exc))
    return EvalSegmentResult(name="unit", status="passed", detail="self_improve imports ok")


def _golden_metrics_dict(golden: GoldenRoutingReplayResult) -> dict[str, float]:
    """Extract report metric keys from a golden routing replay result.

    Args:
        golden (GoldenRoutingReplayResult): Replay outcome from the graph.

    Returns:
        dict[str, float]: Flat metric map for ``eval_report.json`` v2.

    Examples:
        >>> _golden_metrics_dict.__name__
        '_golden_metrics_dict'
    """
    m = golden.metrics
    return {
        "golden_routing.intent_match_rate": m.intent_match_rate,
        "golden_routing.complexity_match_rate": m.complexity_match_rate,
        "golden_routing.intent_matches": float(m.intent_matches),
        "golden_routing.complexity_matches": float(m.complexity_matches),
        "golden_routing.tools_match_rate": m.tools_match_rate,
        "golden_routing.tools_matches": float(m.tools_matches),
        "golden_routing.sampled": float(m.sampled),
        "golden_routing.total": float(m.total),
    }


def run_eval_graph(
    *,
    workspace: WorkspaceConfig,
    job_bundle: Path,
    repo_root: Path | None = None,
) -> ImproveJobResult:
    """Run the evaluation graph in-process and return an aggregate job result.

    Writes ``eval_report.json`` under ``job_bundle`` with segment metrics and a
    top-level ``passed`` flag.

    Args:
        workspace (WorkspaceConfig): Active workspace configuration.
        job_bundle (Path): On-disk artefact directory for the job.
        repo_root (Path | None): Optional repository checkout root.

    Returns:
        ImproveJobResult: Paths and per-segment outcomes for job-store wiring.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> def _demo() -> bool:
        ...     td = tempfile.mkdtemp()
        ...     bundle = Path(td)
        ...     bundle.mkdir()
        ...     ws = WorkspaceConfig.minimal()
        ...     os.environ["SEVN_IMPROVE_EVAL_IN_PROCESS"] = "1"
        ...     os.environ["SEVN_REPO_ROOT"] = str(Path.cwd())
        ...     result = run_eval_graph(workspace=ws, job_bundle=bundle)
        ...     return result.eval_report_path.name == "eval_report.json"
        >>> _demo()  # doctest: +SKIP
        True
    """
    job_bundle.mkdir(parents=True, exist_ok=True)
    root = resolve_repo_root(repo_root)
    segments: list[EvalSegmentResult] = [_run_unit_segment()]
    golden = run_golden_routing_replay(repo_root=root)
    segments.append(golden.segment)
    live = run_live_replay_smoke(workspace=workspace, job_bundle=job_bundle, repo_root=root)
    if live.status == "skipped":
        segments.append(
            EvalSegmentResult(name="live_replay_smoke", status="skipped", detail=live.reason),
        )
    elif live.status == "passed":
        segments.append(
            EvalSegmentResult(name="live_replay_smoke", status="passed", detail=live.reason),
        )
    else:
        segments.append(
            EvalSegmentResult(name="live_replay_smoke", status="failed", detail=live.reason),
        )
    passed = all(seg.status in ("passed", "skipped") for seg in segments)
    metrics = _golden_metrics_dict(golden)
    thresholds = {"golden_routing.intent_match_rate": DEFAULT_INTENT_MATCH_THRESHOLD}
    baseline_path = baseline_path_for_job_bundle(job_bundle)
    baseline_record = load_last_known_good(baseline_path)
    baseline_section = baseline_section_for_report(baseline_record)
    deltas = (
        compute_metric_deltas(current=metrics, baseline=baseline_record.metrics)
        if baseline_record is not None
        else {}
    )
    report_path = job_bundle / "eval_report.json"
    report = {
        "schema_version": 2,
        "passed": passed,
        "metrics": metrics,
        "thresholds": thresholds,
        "baseline": baseline_section,
        "deltas": deltas,
        "segments": [
            {"name": seg.name, "status": seg.status, "detail": seg.detail} for seg in segments
        ],
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    seg_tuple = tuple(segments)
    return ImproveJobResult(passed=passed, eval_report_path=report_path, segments=seg_tuple)


def run_docker_eval_graph(
    *,
    workspace: WorkspaceConfig,
    job_bundle: Path,
    repo_root: Path | None = None,
) -> ImproveJobResult:
    """Run the evaluation graph, delegating to Docker when config requires it.

    When ``eval.docker_required`` is true and ``SEVN_IMPROVE_EVAL_IN_PROCESS`` is
    unset, subprocesses ``docker compose -f docker/docker-compose.improve-evals.yml run``.
    Otherwise runs :func:`run_eval_graph` on the host.

    Args:
        workspace (WorkspaceConfig): Active workspace configuration.
        job_bundle (Path): On-disk artefact directory for the job.
        repo_root (Path | None): Optional repository checkout root.

    Returns:
        ImproveJobResult: Paths and per-segment outcomes for job-store wiring.

    Examples:
        >>> run_docker_eval_graph.__name__
        'run_docker_eval_graph'
    """
    root = resolve_repo_root(repo_root)
    if eval_docker_required(workspace) and not eval_in_process_override():
        from sevn.self_improve.eval.docker import run_eval_in_docker

        return run_eval_in_docker(workspace=workspace, job_bundle=job_bundle, repo_root=root)
    return run_eval_graph(workspace=workspace, job_bundle=job_bundle, repo_root=root)


def eval_report_passed(eval_report_path: Path) -> bool:
    """Return whether ``eval_report.json`` records a passing graph run.

    Args:
        eval_report_path (Path): On-disk eval report path.

    Returns:
        bool: ``True`` when the report exists and ``passed`` is true.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> p = td / "eval_report.json"
        >>> _ = p.write_text('{"passed": true}', encoding="utf-8")
        >>> eval_report_passed(p)
        True
    """
    if not eval_report_path.is_file():
        return False
    data = json.loads(eval_report_path.read_text(encoding="utf-8"))
    return bool(data.get("passed"))


__all__ = [
    "DEFAULT_INTENT_MATCH_THRESHOLD",
    "GOLDEN_ROUTING_CORPUS_REL",
    "EvalSegmentResult",
    "GoldenRoutingReplayResult",
    "ImproveJobResult",
    "LiveReplaySmokeResult",
    "eval_docker_required",
    "eval_in_process_override",
    "eval_report_passed",
    "golden_routing_fixture_path",
    "resolve_repo_root",
    "run_docker_eval_graph",
    "run_eval_graph",
    "run_live_replay_smoke",
]

# Back-compat alias for launcher import path used during Wave E-0A rollout.
_resolve_repo_root = resolve_repo_root
