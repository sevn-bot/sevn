"""CLI entry for improve evaluation inside Docker (`specs/33-self-improvement.md` §4.3).

Module: sevn.self_improve.eval.launcher
Depends: argparse, sys, pathlib, sevn.config.workspace_config, sevn.self_improve.eval

Exports:
    main — parse argv and run the in-container eval graph.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sevn.config.workspace_config import WorkspaceConfig
from sevn.self_improve.eval import resolve_repo_root, run_eval_graph


def main(argv: list[str] | None = None) -> int:
    """Run the evaluation graph for a job bundle directory.

    Args:
        argv (list[str] | None): CLI arguments; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` when the graph passes, ``1`` on failure, ``2`` on usage error.

    Examples:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(
        description="Run the improve evaluation graph for a job bundle directory.",
    )
    parser.add_argument(
        "job_bundle",
        type=Path,
        help="Directory that receives eval_report.json",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository checkout root (default: SEVN_REPO_ROOT or cwd walk)",
    )
    args = parser.parse_args(argv)
    workspace = WorkspaceConfig.minimal()
    result = run_eval_graph(
        workspace=workspace,
        job_bundle=args.job_bundle,
        repo_root=resolve_repo_root(args.repo_root),
    )
    if result.passed:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
