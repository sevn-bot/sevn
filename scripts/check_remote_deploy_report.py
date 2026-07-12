#!/usr/bin/env python3
"""Validate the latest remote deploy JSON report against its schema.

Module: scripts.check_remote_deploy_report
Depends: argparse, json, pathlib, sys

Exports:
    main — CLI entry for ``make deploy-remote-report-check``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _latest_report(reports_dir: Path) -> Path | None:
    """Return the newest ``remote-deploy-*.json`` under ``reports_dir``.

    Args:
        reports_dir (Path): Directory to scan.

    Returns:
        Path | None: Newest report path, if any exist.

    Examples:
        >>> _latest_report(Path("/nonexistent")) is None
        True
    """
    if not reports_dir.is_dir():
        return None
    candidates = sorted(
        reports_dir.glob("remote-deploy-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def main(argv: list[str] | None = None) -> int:
    """Validate the newest ``reports/remote-deploy-*.json`` file.

    Args:
        argv (list[str] | None): CLI arguments (schema path override for tests).

    Returns:
        int: Process exit code.

    Examples:
        >>> isinstance(main(["--reports-dir", "/nonexistent"]), int)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=_REPO / "reports",
        help="Directory containing remote deploy reports.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=_REPO / "infra" / "remote-deploy-report.schema.json",
        help="JSON Schema path.",
    )
    args = parser.parse_args(argv)
    report_path = _latest_report(args.reports_dir)
    if report_path is None:
        fixture = _REPO / "tests" / "fixtures" / "deploy" / "remote-deploy-check.json"
        if fixture.is_file():
            report_path = fixture
        else:
            print(
                f"no remote deploy report under {args.reports_dir} "
                "(run make deploy-remote or tests first)",
                file=sys.stderr,
            )
            return 1
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "check_jsonschema",
            "--schemafile",
            str(args.schema),
            str(report_path),
        ],
        check=False,
        cwd=_REPO,
    )
    if proc.returncode != 0:
        return proc.returncode
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    print(f"ok: {report_path} mode={payload.get('mode')} host_id={payload.get('host_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
