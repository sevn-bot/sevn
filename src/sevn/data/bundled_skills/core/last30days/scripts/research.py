#!/usr/bin/env python3
"""sevn wrapper for the bundled last30days v3 research engine.

Module: sevn.data.bundled_skills.core.last30days.scripts.research
Depends: argparse, os, subprocess, sys, pathlib, sevn.lcm.script_cli

Exports:
    resolve_python312 — locate a Python 3.12+ interpreter.
    build_engine_argv — construct argv for ``scripts/last30days.py``.
    main — CLI entry; JSON envelope on stdout (dry-run or live subprocess).

Examples:
    >>> from sevn.data.bundled_skills.core.last30days.scripts.research import build_engine_argv
    >>> argv = build_engine_argv(
    ...     engine_path="/tmp/last30days/scripts/last30days.py",
    ...     topic="sevn.bot",
    ...     extra_args=["--emit", "compact"],
    ... )
    >>> argv[-1]
    'sevn.bot'
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok

_ENGINE_TIMEOUT_SECONDS = 900.0
_DRY_RUN_ENV = "SEVN_LAST30DAYS_DRY_RUN"
_MEMORY_SUBDIR = "out/last30days"


def resolve_python312() -> str | None:
    """Return the path to a Python 3.12+ interpreter when one exists on PATH.

    Returns:
        str | None: Executable path, or ``None`` when no suitable interpreter is found.

    Examples:
        >>> resolve_python312() is None or isinstance(resolve_python312(), str)
        True
    """
    from shutil import which

    candidates: list[str] = []
    for name in ("python3.14", "python3.13", "python3.12", "python3"):
        found = which(name)
        if found:
            candidates.append(found)
    if sys.executable:
        candidates.append(sys.executable)
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            completed = subprocess.run(
                [
                    candidate,
                    "-c",
                    "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)",
                ],
                capture_output=True,
                check=False,
                timeout=10.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0:
            return candidate
    return None


def skill_dir_from_env() -> Path:
    """Resolve the bundled skill directory from ``SEVN_SKILL_DIR``.

    Returns:
        Path: Absolute skill root directory.

    Examples:
        >>> skill_dir_from_env().name
        'last30days'
    """
    raw = os.environ.get("SEVN_SKILL_DIR", "").strip()
    if raw:
        return Path(raw).resolve()
    return Path(__file__).resolve().parents[1]


def default_memory_dir(workspace: Path) -> Path:
    """Return the workspace-relative last30days output directory.

    Args:
        workspace (Path): Operator workspace root (``SEVN_WORKSPACE``).

    Returns:
        Path: Absolute path under ``out/last30days``.

    Examples:
        >>> default_memory_dir(Path("/tmp/ws")).as_posix().endswith("out/last30days")
        True
    """
    return (workspace / _MEMORY_SUBDIR).resolve()


def build_engine_argv(
    *,
    engine_path: Path,
    topic: str,
    extra_args: list[str],
) -> list[str]:
    """Build argv for the upstream ``last30days.py`` CLI.

    Args:
        engine_path (Path): Path to ``scripts/last30days.py``.
        topic (str): Research topic string passed as positional arg.
        extra_args (list[str]): Additional flags forwarded before the topic.

    Returns:
        list[str]: Process argv starting with the Python interpreter placeholder.

    Examples:
        >>> tail = build_engine_argv(
        ...     engine_path=Path("/s/last30days.py"),
        ...     topic="OpenClaw",
        ...     extra_args=["--emit", "compact"],
        ... )
        >>> tail[-2:]
        ['--emit', 'compact']
        >>> tail[-1]
        'OpenClaw'
    """
    return [str(engine_path), *extra_args, topic]


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


def main(argv: list[str] | None = None) -> int:
    """Run last30days research or return a dry-run argv plan.

    Forwards unknown flags to ``scripts/last30days.py``. Sets
    ``LAST30DAYS_MEMORY_DIR`` under the workspace when unset.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on validation or execution failure.

    Examples:
        >>> import io, contextlib
        >>> buf = io.StringIO()
        >>> with contextlib.redirect_stdout(buf):
        ...     rc = main(["--dry-run", "--topic", "sevn.bot", "--emit", "compact"])
        >>> rc
        0
        >>> '"mode":"dry_run"' in buf.getvalue()
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True, help="Research topic (positional for engine).")
    parser.add_argument("--dry-run", action="store_true", help="Return argv plan without running.")
    parser.add_argument(
        "--python",
        default="",
        help="Override Python 3.12+ interpreter (default: auto-detect).",
    )
    args, forwarded = parser.parse_known_args(argv)

    topic = args.topic.strip()
    if not topic:
        write_error(code="VALIDATION_FAILED", error="--topic must be non-empty")
        return 1

    skill_dir = skill_dir_from_env()
    engine_path = skill_dir / "scripts" / "last30days.py"
    if not engine_path.is_file():
        write_error(
            code="DEPENDENCY_MISSING",
            error=f"last30days engine missing at {engine_path}",
        )
        return 1

    python_bin = args.python.strip() or resolve_python312() or sys.executable
    workspace = workspace_from_env()
    memory_dir = os.environ.get("LAST30DAYS_MEMORY_DIR", "").strip()
    if not memory_dir:
        memory_dir = str(default_memory_dir(workspace))

    engine_argv_tail = build_engine_argv(
        engine_path=engine_path,
        topic=topic,
        extra_args=forwarded,
    )
    full_argv = [python_bin, *engine_argv_tail]

    if _dry_run_requested(cli_flag=args.dry_run):
        write_ok(
            {
                "mode": "dry_run",
                "argv": full_argv,
                "topic": topic,
                "memory_dir": memory_dir,
                "skill_dir": str(skill_dir),
            }
        )
        return 0

    env = os.environ.copy()
    env.setdefault("LAST30DAYS_MEMORY_DIR", memory_dir)
    env.setdefault("SEVN_SKILL_DIR", str(skill_dir))

    try:
        completed = subprocess.run(
            full_argv,
            cwd=str(skill_dir),
            capture_output=True,
            timeout=_ENGINE_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        write_error(
            code="TOOL_TIMEOUT",
            error=f"last30days engine exceeded {_ENGINE_TIMEOUT_SECONDS:.0f}s wall timeout",
        )
        return 1

    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    code = completed.returncode or 0

    if code != 0:
        write_error(
            code="ENGINE_FAILED",
            error=f"last30days engine exited {code}",
            data={
                "exit_code": code,
                "stdout_tail": stdout[-4096:] if stdout else "",
                "stderr_tail": stderr[-4096:] if stderr else "",
            },
        )
        return 1

    write_ok(
        {
            "mode": "live",
            "topic": topic,
            "stdout": stdout,
            "stderr_tail": stderr[-2048:] if stderr else "",
            "exit_code": code,
            "memory_dir": memory_dir,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
