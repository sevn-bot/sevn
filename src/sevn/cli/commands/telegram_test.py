"""``sevn telegram-test`` Playwright E2E harness (host machine only).

Module: sevn.cli.commands.telegram_test
Depends: json, subprocess, sys, pathlib, typer, sevn.cli.errors

Exports:
    register — attach ``sevn telegram-test`` subtree to the root Typer app.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Literal

import typer

TargetKind = Literal["local", "prod"]
KNOWN_SUITES: tuple[str, ...] = ("session",)
NEEDS_LOGIN_EXIT_CODE = 7


def _require_tester_package() -> None:
    """Ensure the workspace ``sevn-telegram-tester`` package is importable.

    Raises:
        typer.Exit: Exit code ``4`` when the tester package is not installed.

    Examples:
        >>> _require_tester_package()  # doctest: +SKIP
    """
    try:
        import sevn_telegram_tester  # noqa: F401
    except ImportError:
        typer.secho(
            "Telegram E2E tester is not installed. From the repo root run: uv sync --extra dev",
            err=True,
        )
        raise typer.Exit(4) from None


def _tester_module_argv(*tail: str) -> list[str]:
    """Build argv for ``python -m sevn_telegram_tester.runner``.

    Args:
        tail (str): Arguments after the module name.

    Returns:
        argv suitable for ``subprocess.run``.

    Examples:
        >>> argv = _tester_module_argv("list")
        >>> argv[-1]
        'list'
        >>> argv[0] == sys.executable
        True
    """
    return [sys.executable, "-m", "sevn_telegram_tester.runner", *tail]


def _run_tester(argv: list[str]) -> int:
    """Execute the tester runner subprocess with inherited stdio.

    Args:
        argv (list[str]): Full argv including the Python interpreter.

    Returns:
        Child process exit code.

    Examples:
        >>> import sys
        >>> from unittest.mock import patch
        >>> class _Proc:
        ...     returncode = 0
        >>> with patch("subprocess.run", return_value=_Proc()):
        ...     _run_tester([sys.executable, "-c", "pass"])
        0
    """
    completed = subprocess.run(argv, check=False)  # nosec B603
    return int(completed.returncode)


def _artifacts_dir() -> Path:
    """Resolve the tester artifacts directory from packaged settings.

    Returns:
        Path to ``tools/telegram-tester/artifacts`` (or env override).

    Examples:
        >>> path = _artifacts_dir()
        >>> path.name == "artifacts"
        True
    """
    from sevn_telegram_tester.config import TelegramTesterSettings

    return Path(TelegramTesterSettings().artifacts_dir)


def _latest_report_path(artifacts: Path) -> Path | None:
    """Return the newest JSON report under ``artifacts``, if any.

    Args:
        artifacts (Path): Tester artifacts root.

    Returns:
        Newest ``*.json`` by mtime, or ``None`` when empty.

    Examples:
        >>> from pathlib import Path
        >>> _latest_report_path(Path("/tmp/sevn-empty-artifacts-xyz")) is None
        True
    """
    if not artifacts.is_dir():
        return None
    candidates = sorted(
        artifacts.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def register(app: typer.Typer) -> None:
    """Attach ``sevn telegram-test`` subtree to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    tg = typer.Typer(
        help=(
            "Playwright E2E against Telegram Web K on the developer machine "
            "(not inside the gateway Docker image)."
        ),
    )
    app.add_typer(tg, name="telegram-test")

    @tg.command("login")
    def telegram_test_login() -> None:
        """Open headed Chromium for one-time Telegram Web QR login."""
        _require_tester_package()
        code = _run_tester(_tester_module_argv("login"))
        raise typer.Exit(code)

    @tg.command("list")
    def telegram_test_list() -> None:
        """Print available suite names (v1: session)."""
        for suite in KNOWN_SUITES:
            typer.echo(suite)

    @tg.command("run")
    def telegram_test_run(
        suite: str = typer.Argument(..., help="Suite name (see `list`)."),
        target: TargetKind = typer.Option(
            "local",
            "--target",
            help="local: docker compose on localhost; prod: remote bot via .env.",
        ),
        bot_username: str | None = typer.Option(
            None,
            "--bot-username",
            help="Override TG_TARGET_BOT for this run.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit structured JSON report on stdout.",
        ),
        headless: bool = typer.Option(
            False,
            "--headless",
            help="Run Chromium without a visible window (default: headed).",
        ),
    ) -> None:
        """Run a named Playwright suite against the configured bot."""
        if suite not in KNOWN_SUITES:
            typer.secho(
                f"unknown suite {suite!r}; available: {', '.join(KNOWN_SUITES)}",
                err=True,
            )
            raise typer.Exit(2)
        _require_tester_package()
        argv = [
            *_tester_module_argv(
                "run",
                suite,
                "--target",
                target,
            ),
        ]
        if json_out:
            argv.append("--json")
        if headless:
            argv.append("--headless")
        if bot_username:
            argv.extend(["--bot-username", bot_username])
        code = _run_tester(argv)
        raise typer.Exit(code)

    @tg.command("status")
    def telegram_test_status(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Print the last report JSON verbatim.",
        ),
    ) -> None:
        """Show summary of the most recent run from the artifacts directory."""
        _require_tester_package()
        report_path = _latest_report_path(_artifacts_dir())
        if report_path is None:
            typer.secho(
                "no telegram-test runs recorded yet "
                "(artifacts directory is empty; run `sevn telegram-test run` first)",
                err=True,
            )
            raise typer.Exit(4)
        raw = report_path.read_text(encoding="utf-8")
        if json_out:
            typer.echo(raw.rstrip())
            raise typer.Exit(0)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            typer.secho(f"last report is not valid JSON: {report_path}", err=True)
            raise typer.Exit(1) from None
        suite = payload.get("suite", "?")
        target = payload.get("target", "?")
        tests = payload.get("tests") or []
        passed = sum(1 for row in tests if row.get("status") == "passed")
        failed = sum(1 for row in tests if row.get("status") == "failed")
        skipped = sum(1 for row in tests if row.get("status") == "skipped")
        typer.echo(f"report: {report_path}")
        typer.echo(f"suite: {suite}  target: {target}")
        typer.echo(f"tests: {passed} passed, {failed} failed, {skipped} skipped")
        dep = payload.get("deployment_id_observed")
        if dep:
            typer.echo(f"deployment_id_observed: {dep}")
        raise typer.Exit(0)
