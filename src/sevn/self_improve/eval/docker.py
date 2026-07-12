"""Docker compose runner for the improve evaluation graph.

Module: sevn.self_improve.eval.docker
Depends: json, subprocess, pathlib, sevn.self_improve.eval

Exports:
    run_eval_in_docker — subprocess ``docker compose run --rm improve-evals``.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404
from pathlib import Path  # noqa: TC003 — runtime path checks in compose helpers
from typing import TYPE_CHECKING, Literal, cast

from sevn.self_improve.eval.replay import EvalSegmentResult

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.self_improve.eval import ImproveJobResult

IMPROVE_EVALS_COMPOSE_FILE = "docker/docker-compose.improve-evals.yml"
IMPROVE_EVALS_SERVICE = "improve-evals"


def _job_bundle_relative_to_repo(job_bundle: Path, repo_root: Path) -> Path:
    """Return ``job_bundle`` as a path relative to ``repo_root``.

    Args:
        job_bundle (Path): Host directory for eval artefacts.
        repo_root (Path): Repository checkout root bind-mounted at ``/work``.

    Returns:
        Path: Relative bundle path passed to the container launcher.

    Raises:
        ValueError: When ``job_bundle`` is outside ``repo_root``.

    Examples:
        >>> from pathlib import Path
        >>> root = Path("/repo")
        >>> _job_bundle_relative_to_repo(Path("/repo/.sevn/j"), root).as_posix()
        '.sevn/j'
    """
    abs_bundle = job_bundle.resolve()
    abs_root = repo_root.resolve()
    try:
        return abs_bundle.relative_to(abs_root)
    except ValueError as exc:
        msg = f"job_bundle {job_bundle} must live under repo root {repo_root} for Docker eval"
        raise ValueError(msg) from exc


def _improve_job_result_from_report(report_path: Path) -> ImproveJobResult:
    """Rebuild ``ImproveJobResult`` from an on-disk ``eval_report.json``.

    Args:
        report_path (Path): Written report path under the job bundle.

    Returns:
        ImproveJobResult: Parsed aggregate outcome.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> p = td / "eval_report.json"
        >>> _ = p.write_text(
        ...     '{"passed": true, "segments": [{"name": "unit", "status": "passed", "detail": "ok"}]}',
        ...     encoding="utf-8",
        ... )
        >>> _improve_job_result_from_report(p).passed
        True
    """
    from sevn.self_improve.eval import ImproveJobResult

    data = json.loads(report_path.read_text(encoding="utf-8"))
    segments = tuple(
        EvalSegmentResult(
            name=str(seg["name"]),
            status=cast("Literal['passed', 'failed', 'skipped']", str(seg["status"])),
            detail=str(seg.get("detail", "")),
        )
        for seg in data.get("segments", [])
    )
    return ImproveJobResult(
        passed=bool(data.get("passed")),
        eval_report_path=report_path,
        segments=segments,
    )


def run_eval_in_docker(
    *,
    workspace: WorkspaceConfig,
    job_bundle: Path,
    repo_root: Path,
) -> ImproveJobResult:
    """Run the evaluation graph inside ``docker/docker-compose.improve-evals.yml``.

    Args:
        workspace (WorkspaceConfig): Active workspace configuration (unused today;
            reserved for future workspace-specific compose overrides).
        job_bundle (Path): On-disk artefact directory for the job.
        repo_root (Path): Repository checkout root containing the compose file.

    Returns:
        ImproveJobResult: Aggregate outcome after the container exits zero.

    Raises:
        FileNotFoundError: When the compose file is missing.
        RuntimeError: When compose exits non-zero or omits ``eval_report.json``.

    Examples:
        >>> run_eval_in_docker.__name__
        'run_eval_in_docker'
    """
    _ = workspace
    compose_path = repo_root / IMPROVE_EVALS_COMPOSE_FILE
    if not compose_path.is_file():
        msg = f"missing compose file: {compose_path}"
        raise FileNotFoundError(msg)
    rel_bundle = _job_bundle_relative_to_repo(job_bundle, repo_root)
    cmd = [
        "docker",
        "compose",
        "-f",
        str(compose_path),
        "run",
        "--rm",
        IMPROVE_EVALS_SERVICE,
        str(rel_bundle),
    ]
    proc = subprocess.run(  # nosec B603 — fixed docker compose argv; no shell
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        msg = f"docker eval failed (exit {proc.returncode}): {detail}"
        raise RuntimeError(msg)
    report_path = job_bundle / "eval_report.json"
    if not report_path.is_file():
        msg = f"eval_report.json missing after docker run: {report_path}"
        raise RuntimeError(msg)
    return _improve_job_result_from_report(report_path)


__all__ = [
    "IMPROVE_EVALS_COMPOSE_FILE",
    "IMPROVE_EVALS_SERVICE",
    "run_eval_in_docker",
]
