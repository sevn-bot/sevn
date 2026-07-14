"""spec-kit-wave CLI entrypoint.

Exports:
    main — dispatch ``skw`` subcommands.

Examples:
    >>> import skw.cli as cli
    >>> cli.main.__name__
    'main'
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Dispatch ``skw`` subcommands.

    Args:
        argv (list[str] | None, optional): Arguments after ``skw``. Defaults to
            ``sys.argv[1:]``.

    Returns:
        int: Process exit code (``0`` success, ``2`` usage error).

    Examples:
        >>> main([])
        2
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(
            "usage: skw docs validate|score|sync --kind {spec,prd} --dir <folder>", file=sys.stderr
        )
        return 2
    if argv[0] == "docs":
        from skw.doc_folder import main as docs_main

        return docs_main(argv[1:])
    print(f"unknown command: {argv[0]!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
