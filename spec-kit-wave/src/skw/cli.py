"""spec-kit-wave CLI entrypoint."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Dispatch ``skw`` subcommands."""
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
