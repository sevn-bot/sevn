"""Log-safe redaction helper (`specs/17-gateway.md` §8).

Module: sevn.gateway.redact
Depends: (none)

Exports:
    redact_inline — shorten high-entropy literals for tracing.
"""

from __future__ import annotations


def redact_inline(value: str | None, *, mode: str = "strict") -> str:
    """Return a non-reversible abbreviated view for traces.

    Args:
        value (str | None): Secret-bearing value to abbreviate; ``None`` is
            rendered as ``[null]`` so callers can distinguish missing from short.
        mode (str, optional): Reserved for stricter modes (currently unused).
            Defaults to ``"strict"``.

    Returns:
        str: ``"***"`` for short values, otherwise ``"<head>...<tail>"``.

    Examples:
        >>> redact_inline("abcdefgh_secret")
        'abcd…cret'
        >>> redact_inline(None)
        '[null]'
    """

    _ = mode
    if value is None:
        return "[null]"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]}"
