"""Backward-compatible re-export of :mod:`sevn.logging.log_redact`.

Module: sevn.cli.log_redact
Depends: sevn.logging.log_redact

Exports:
    redact_log_line — strip bearer tokens and common secret patterns.

Examples:
    >>> from sevn.cli.log_redact import redact_log_line
    >>> "abc123" not in redact_log_line("token=abc123")
    True
"""

from __future__ import annotations

from sevn.logging.log_redact import redact_log_line

__all__ = ["redact_log_line"]
