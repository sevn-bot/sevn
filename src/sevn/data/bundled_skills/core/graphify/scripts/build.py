#!/usr/bin/env python3
"""graphify skill driver — build a knowledge graph from a profile.

Module: sevn.data.bundled_skills.core.graphify.scripts.build
Depends: argparse, os, shutil, subprocess, sevn.code_understanding.models, sevn.lcm.script_cli

Exports:
    build_graphify_argv — construct allowlisted ``graphify build`` argv from a profile.
    main — CLI entry; JSON envelope on stdout (dry-run or live graphify subprocess).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess

from sevn.code_understanding.models import GraphifyProfile
from sevn.lcm.script_cli import write_error, write_ok

_BUILD_TIMEOUT_SECONDS = 3600.0
_DRY_RUN_ENV = "SEVN_GRAPHIFY_DRY_RUN"


def _dry_run_requested(*, cli_flag: bool) -> bool:
    """Return True when dry-run mode is selected via CLI or environment.

    Args:
        cli_flag (bool): Whether ``--dry-run`` was passed on the CLI.

    Returns:
        bool: True when the script should print argv only (no subprocess).

    Examples:
        >>> _dry_run_requested(cli_flag=True)
        True
    """
    if cli_flag:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes"}


def _graphify_missing_message() -> str:
    """Return the standard error when ``graphify`` is missing from PATH.

    Returns:
        str: Install hint naming the ``graphify`` optional extra.

    Examples:
        >>> "graphify" in _graphify_missing_message()
        True
    """
    return (
        "graphify: `graphify` not found on PATH "
        "(install with `uv sync --extra graphify` or `pip install graphifyy`)"
    )


def build_graphify_argv(profile: GraphifyProfile) -> list[str]:
    """Build allowlisted argv for ``graphify build`` from a resolved profile.

    Args:
        profile (GraphifyProfile): Validated profile with root and output paths.

    Returns:
        list[str]: Process argv starting with ``graphify``.

    Examples:
        >>> from sevn.code_understanding.models import GraphifyProfile
        >>> build_graphify_argv(
        ...     GraphifyProfile(id="d", root_path="/r", output_dir="/o"),
        ... )
        ['graphify', 'build', '--root', '/r', '--output', '/o']
    """
    flags = profile.validated_cli_flags()
    return [
        "graphify",
        "build",
        "--root",
        profile.root_path,
        "--output",
        profile.output_dir,
        *flags,
    ]


def _run_graphify_build(profile: GraphifyProfile, argv: list[str]) -> tuple[bool, str, int]:
    """Execute ``graphify build`` when the CLI is present on PATH.

    Args:
        profile (GraphifyProfile): Profile whose ``root_path`` becomes subprocess cwd.
        argv (list[str]): Allowlisted argv from :func:`build_graphify_argv`.

    Returns:
        tuple[bool, str, int]: ``(ok, detail, returncode)`` where ``detail`` is stdout
            or stderr text on failure.

    Examples:
        >>> _run_graphify_build.__name__
        '_run_graphify_build'
    """
    if shutil.which("graphify") is None:
        return False, _graphify_missing_message(), 127
    completed = subprocess.run(
        argv,
        cwd=profile.root_path,
        capture_output=True,
        timeout=_BUILD_TIMEOUT_SECONDS,
        check=False,
    )
    code = completed.returncode or 0
    if code != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        if not detail:
            detail = completed.stdout.decode("utf-8", errors="replace").strip()
        if not detail:
            detail = f"graphify build exited {code}"
        return False, detail, code
    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    return True, stdout, code


def main(argv: list[str] | None = None) -> int:
    """Build a Graphify knowledge graph or return a dry-run argv plan.

    When ``--dry-run`` or ``SEVN_GRAPHIFY_DRY_RUN=1`` is set, prints a success
    envelope with the argv plan only. Otherwise invokes ``graphify build`` when
    the optional ``graphify`` extra is installed; missing CLI returns
    ``DEPENDENCY_MISSING``.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on validation or execution failure.

    Examples:
        >>> import io, contextlib
        >>> buf = io.StringIO()
        >>> with contextlib.redirect_stdout(buf):
        ...     rc = main([
        ...         "--dry-run",
        ...         "--profile-id", "default",
        ...         "--root", "/r",
        ...         "--output", "/o",
        ...     ])
        >>> rc
        0
        >>> '"mode":"dry_run"' in buf.getvalue()
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-id", default="default")
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--flag",
        action="append",
        default=[],
        help="Allowlisted Graphify CLI flag; pass repeatedly.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print argv plan only (also via SEVN_GRAPHIFY_DRY_RUN=1).",
    )
    args = parser.parse_args(argv)

    try:
        profile = GraphifyProfile(
            id=args.profile_id,
            root_path=args.root,
            output_dir=args.output,
            cli_flags=args.flag,
        )
        argv_plan = build_graphify_argv(profile)
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1

    if _dry_run_requested(cli_flag=args.dry_run):
        write_ok(
            {
                "mode": "dry_run",
                "argv": argv_plan,
                "profile_id": profile.id,
                "root": profile.root_path,
                "output": profile.output_dir,
            },
        )
        return 0

    ok, detail, returncode = _run_graphify_build(profile, argv_plan)
    if not ok:
        if returncode == 127:
            write_error(code="DEPENDENCY_MISSING", error=detail)
        else:
            write_error(code="BUILD_FAILED", error=f"graphify: {detail}")
        return 1

    write_ok(
        {
            "mode": "live",
            "argv": argv_plan,
            "profile_id": profile.id,
            "root": profile.root_path,
            "output": profile.output_dir,
            "returncode": returncode,
            "stdout": detail[:8192],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
