"""Redact secrets from operator log lines before persistence or TTY output.

Module: sevn.logging.log_redact
Depends: re

Exports:
    redact_log_line — strip bearer tokens and common secret patterns.

Examples:
    >>> from sevn.logging.log_redact import redact_log_line
    >>> "abc123" not in redact_log_line("token=abc123")
    True
"""

from __future__ import annotations

import re

_LOG_REDACT = re.compile(
    r"(?i)(bearer\s+[a-z0-9._\-]+|api[_-]?key[=:\s]+[a-z0-9._\-]+|token[=:\s]+[a-z0-9._\-]+|"
    r"password[=:\s]+\S+|secret[=:\s]+\S+)"
)


def redact_log_line(line: str) -> str:
    """Redact obvious secret material from one log line.

    Args:
        line (str): Raw log line.

    Returns:
        str: Redacted line without trailing newline.

    Examples:
        >>> "abc123" not in redact_log_line("token=abc123")
        True
    """
    return _LOG_REDACT.sub("<redacted>", line.rstrip("\n"))


__all__ = ["redact_log_line"]
