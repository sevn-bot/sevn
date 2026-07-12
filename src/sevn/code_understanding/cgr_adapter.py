"""Allowlisted CGR CLI argv builder + capped export reader.

Module: sevn.code_understanding.cgr_adapter
Depends: (stdlib only)

The module-level ``CGR_ALLOWED_SUBCOMMANDS`` frozenset names every subcommand
the wrapper accepts; everything else is rejected at argv-build time.

Exports:
    Functions:
        build_cgr_argv — build a safe argv list for a CGR subprocess.
        read_export_capped — truncate a CGR export payload at ``max_bytes``.
"""

from __future__ import annotations

CGR_ALLOWED_SUBCOMMANDS: frozenset[str] = frozenset({"export", "stats", "doctor", "graph-loader"})


def build_cgr_argv(subcommand: str, extra: list[str] | None = None) -> list[str]:
    """Return a safe argv list for the upstream ``cgr`` CLI.

    Model-supplied free-form argv is never accepted (`specs/28-code-understanding.md`
    §2.2). The caller chooses one allowlisted subcommand; everything after that
    is appended verbatim — callers must still validate ``extra`` content for
    their own subcommand semantics, but at minimum this function blocks shell
    invocations and unknown subcommands at construction time.

    Args:
        subcommand (str): Exactly one of :data:`CGR_ALLOWED_SUBCOMMANDS`.
        extra (list[str] | None, optional): Extra positional/flag tokens; not
            shell-interpreted. Defaults to None.

    Returns:
        list[str]: ``["cgr", subcommand, *extra]``.

    Raises:
        ValueError: When ``subcommand`` is not in the allowlist.

    Examples:
        >>> build_cgr_argv("export")
        ['cgr', 'export']
        >>> build_cgr_argv("stats", ["--repo", "/r"])
        ['cgr', 'stats', '--repo', '/r']
    """
    if subcommand not in CGR_ALLOWED_SUBCOMMANDS:
        msg = (
            f"code_graph_rag: disallowed cgr subcommand {subcommand!r}; "
            f"allowed: {sorted(CGR_ALLOWED_SUBCOMMANDS)} "
            f"(specs/28-code-understanding.md §2.2)"
        )
        raise ValueError(msg)
    argv: list[str] = ["cgr", subcommand]
    if extra:
        argv.extend(extra)
    return argv


def read_export_capped(payload: bytes, max_bytes: int) -> bytes:
    """Truncate ``payload`` to at most ``max_bytes`` bytes.

    The CGR ``code_graph_rag_read_export`` tool must never stream unbounded
    Memgraph dumps into the model (`specs/28-code-understanding.md` §2.2 / §8);
    this helper provides the cap.

    Args:
        payload (bytes): Raw export bytes returned by upstream.
        max_bytes (int): Maximum bytes to keep; ``0`` returns ``b""``.

    Returns:
        bytes: ``payload[:max_bytes]``.

    Raises:
        ValueError: When ``max_bytes`` is negative.

    Examples:
        >>> read_export_capped(b"abcdef", 3)
        b'abc'
        >>> read_export_capped(b"abc", 99)
        b'abc'
    """
    if max_bytes < 0:
        msg = "max_bytes must be non-negative"
        raise ValueError(msg)
    if max_bytes == 0:
        return b""
    return payload[:max_bytes]
