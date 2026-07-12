"""CLI-specific exceptions mapped to stable exit codes (`specs/23-cli.md` §2.10).

Module: sevn.cli.errors
Depends: (none)

Exports:
    CliError — base with ``exit_code``.
    CliAuthError — exit ``3`` (auth / missing token / HTTP 401/403).
    CliPreconditionError — exit ``4`` (workspace, lock, not implemented, transport to local).
    CliUsageError — exit ``2`` (argv / malformed env URL).
"""

from __future__ import annotations


class CliError(Exception):
    """Raised for controlled ``typer.Exit`` mapping."""

    exit_code: int = 1

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        """Build a CLI error with optional exit override.

        Args:
            message (str): Human-readable message.
            exit_code (int | None): When set, overrides the class default exit code.

        Examples:
            >>> CliError("x").args[0]
            'x'
        """
        if exit_code is not None:
            self.exit_code = exit_code
        super().__init__(message)


class CliAuthError(CliError):
    """Missing ``SEVN_GATEWAY_TOKEN`` or HTTP 401/403."""

    exit_code = 3


class CliPreconditionError(CliError):
    """Workspace not bound, lock held, not implemented, or local precondition."""

    exit_code = 4


class CliUsageError(CliError):
    """Argv / usage (maps to Typer ``BadParameter`` class of failures, exit ``2``)."""

    exit_code = 2
