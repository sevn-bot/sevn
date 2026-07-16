#!/usr/bin/env python3
"""Bundled ``google-workspace`` skill — OAuth setup helpers.

Module: sevn.data.bundled_skills.core.google-workspace.scripts.setup
Depends: argparse, pathlib, sevn.lcm.script_cli, sevn.skills.google_workspace

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok
from sevn.skills.google_workspace import (
    check_auth,
    check_auth_live,
    exchange_auth_code,
    get_auth_url,
    install_deps,
    revoke_token,
    store_client_secret,
)


def _error_code(exc: Exception) -> str:
    """Map common library exceptions to stable script error codes."""

    if isinstance(exc, FileNotFoundError):
        return "NOT_AUTHENTICATED"
    if isinstance(exc, ImportError):
        return "DEPENDENCIES_MISSING"
    if isinstance(exc, ValueError):
        return "VALIDATION_ERROR"
    if isinstance(exc, RuntimeError):
        return "INSTALL_FAILED"
    return "GOOGLE_WORKSPACE_SETUP_FAILED"


def _check_failed(status: str) -> bool:
    """Return True when a setup ``--check`` style result should exit nonzero."""

    return status in {
        "NOT_AUTHENTICATED",
        "TOKEN_CORRUPT",
        "DEPS_MISSING",
        "REFRESH_FAILED",
        "REVOKE_FAILED",
    }


def main(argv: list[str] | None = None) -> int:
    """Run Google Workspace OAuth setup helpers."""

    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="Report auth state.")
    action.add_argument(
        "--check-live",
        action="store_true",
        help="Refresh token and probe a live Google API call.",
    )
    action.add_argument("--client-secret", metavar="PATH", help="Copy client secret JSON.")
    action.add_argument(
        "--auth-url", action="store_true", help="Create an OAuth authorization URL."
    )
    action.add_argument(
        "--auth-code",
        metavar="URL_OR_CODE",
        help="Exchange an OAuth code or redirect URL for a token.",
    )
    action.add_argument(
        "--revoke",
        action="store_true",
        help="Revoke and delete stored token material.",
    )
    action.add_argument(
        "--install-deps",
        action="store_true",
        help="Install optional Google client dependencies.",
    )
    parser.add_argument(
        "--services",
        default="all",
        help="Comma-delimited service set: email,calendar,drive,sheets,docs,contacts,all.",
    )
    args = parser.parse_args(argv)

    workspace = workspace_from_env()
    try:
        if args.check:
            result = check_auth(workspace)
            if _check_failed(str(result.get("status", ""))):
                write_error(
                    code=str(result.get("status", "NOT_AUTHENTICATED")),
                    error=str(
                        result.get("error") or result.get("status") or "Google auth unavailable"
                    ),
                )
                return 1
            write_ok(result)
            return 0
        if args.check_live:
            result = check_auth_live(workspace)
            if _check_failed(str(result.get("status", ""))):
                write_error(
                    code=str(result.get("status", "NOT_AUTHENTICATED")),
                    error=str(
                        result.get("error") or result.get("status") or "Google auth unavailable"
                    ),
                )
                return 1
            write_ok(result)
            return 0
        if args.client_secret:
            write_ok(store_client_secret(workspace, Path(args.client_secret)))
            return 0
        if args.auth_url:
            write_ok(get_auth_url(workspace, args.services))
            return 0
        if args.auth_code:
            write_ok(exchange_auth_code(workspace, args.auth_code))
            return 0
        if args.revoke:
            result = revoke_token(workspace)
            if str(result.get("status", "")) == "REVOKE_FAILED":
                write_error(
                    code="REVOKE_FAILED", error=str(result.get("error", "token revoke failed"))
                )
                return 1
            write_ok(result)
            return 0
        if args.install_deps:
            write_ok(install_deps())
            return 0
    except Exception as exc:
        write_error(code=_error_code(exc), error=str(exc))
        return 1
    write_error(code="VALIDATION_ERROR", error="no setup action selected")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
