"""CLI entry for ``python -m sevn_telegram_tester.runner``.

Module: sevn_telegram_tester.runner
Depends: sevn_telegram_tester.config, sevn_telegram_tester.reporting.json_report,
    sevn_telegram_tester.suites.session, sevn_telegram_tester.compose

Exports:
    main — argparse entry; dispatches login and suite runs.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from loguru import logger

from sevn_telegram_tester import NEEDS_LOGIN_EXIT_CODE
from sevn_telegram_tester.config import TelegramTesterSettings

if TYPE_CHECKING:
    from sevn_telegram_tester.reporting.json_report import JsonReport


def _write_report(
    report: JsonReport,
    settings: TelegramTesterSettings,
    suite: str,
) -> None:
    """Persist report JSON under ``artifacts/``."""
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    report_path = settings.artifacts_dir / f"{suite}-latest.json"
    report_path.write_text(report.to_json() + "\n", encoding="utf-8")
    logger.info("wrote report {}", report_path)


def _run_session(settings: TelegramTesterSettings, *, emit_json: bool) -> int:
    """Run the session Playwright suite and return a process exit code.

    Args:
        settings: Resolved tester settings.
        emit_json: When True, print the report JSON on stdout.

    Returns:
        0 when all tests pass; 1 when any fail; 7 when Telegram login is required.
    """
    from sevn_telegram_tester.auth import is_logged_in
    from sevn_telegram_tester.browser import BrowserSession
    from sevn_telegram_tester.compose import apply_local_e2e_compose
    from sevn_telegram_tester.suites.session import run_session_suite

    try:
        settings.require_bot_username()
    except ValueError as exc:
        logger.error("{}", exc)
        return 1

    if settings.target == "local":
        try:
            apply_local_e2e_compose(settings)
        except (RuntimeError, TimeoutError) as exc:
            logger.error("local compose E2E setup failed: {}", exc)
            return 1

    session = BrowserSession(settings)
    with session.open() as page:
        if not is_logged_in(page):
            logger.error(
                "Telegram Web is not logged in — run `sevn telegram-test login` first (exit {})",
                NEEDS_LOGIN_EXIT_CODE,
            )
            return NEEDS_LOGIN_EXIT_CODE

        report = run_session_suite(page, settings)

    _write_report(report, settings, "session")
    if emit_json:
        print(report.to_json())

    failed = sum(1 for row in report.tests if row.status == "failed")
    skipped = sum(1 for row in report.tests if row.status == "skipped")
    if failed:
        logger.error("session suite: {} failed of {}", failed, len(report.tests))
        return 1
    if skipped:
        logger.info(
            "session suite: {} passed, {} skipped (echo probes)",
            len(report.tests) - skipped,
            skipped,
        )
    else:
        logger.info("session suite: all {} tests passed", len(report.tests))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch suite runs.

    Args:
        argv: Optional argument vector; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code (0 success; 1 failure; 7 NEEDS_LOGIN).

    Examples:
        >>> import sys
        >>> old = sys.argv
        >>> sys.argv = ["runner", "run", "session", "--target", "local"]
        >>> try:
        ...     code = main()
        ... finally:
        ...     sys.argv = old
        >>> code in (0, 1, 7)
        True
    """
    parser = argparse.ArgumentParser(prog="sevn-telegram-tester")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run a named test suite")
    run_parser.add_argument("suite", choices=["session"])
    run_parser.add_argument("--target", choices=["local", "prod"], default="local")
    run_parser.add_argument("--json", action="store_true", help="Emit JsonReport on stdout")
    run_parser.add_argument(
        "--bot-username",
        default=None,
        help="Override TG_TARGET_BOT for this run.",
    )
    run_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium without a visible window (default: headed).",
    )

    sub.add_parser("login", help="Headed QR login for Telegram Web K")

    args = parser.parse_args(argv)

    if args.command == "run":
        overrides: dict[str, object] = {"target": args.target, "headless": args.headless}
        if args.bot_username:
            overrides["tg_target_bot"] = args.bot_username
        settings = TelegramTesterSettings(**overrides)
        if args.suite == "session":
            return _run_session(settings, emit_json=args.json)
        return 1

    if args.command == "login":
        settings = TelegramTesterSettings(headless=False)
        from sevn_telegram_tester.auth import is_logged_in, wait_for_login
        from sevn_telegram_tester.browser import BrowserSession

        session = BrowserSession(settings)
        with session.open() as page:
            if is_logged_in(page):
                logger.info("Telegram Web session already active")
                return 0
            logger.info("Scan the QR code in the Chromium window to log in")
            try:
                wait_for_login(page)
            except TimeoutError:
                logger.error("Telegram Web login timed out")
                return NEEDS_LOGIN_EXIT_CODE
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
