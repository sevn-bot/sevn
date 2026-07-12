#!/usr/bin/env python3
"""Bundled ``code_graph_rag`` skill — capped CGR export reader.

Module: sevn.data.bundled_skills.core.code_graph_rag.scripts.read_export
Depends: argparse, asyncio, sevn.code_understanding.cgr_runner, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import asyncio

from sevn.code_understanding.cgr_adapter import read_export_capped
from sevn.code_understanding.cgr_runner import read_export_file, run_cgr_subprocess
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok


def main(argv: list[str] | None = None) -> int:
    """Read a capped CGR export preview from disk or via ``cgr export``.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on failure envelope.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> cgr_dir = ws / ".sevn" / "cgr"
        >>> cgr_dir.mkdir(parents=True)
        >>> export = cgr_dir / "export.json"
        >>> _ = export.write_bytes(b'{"nodes":[]}')
        >>> import os
        >>> os.environ["SEVN_WORKSPACE"] = str(ws)
        >>> main(["--max-bytes", "100"])
        0
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="", help="Filter or search hint (echoed in payload).")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=65536,
        help="Maximum export bytes to read (default 65536).",
    )
    args = parser.parse_args(argv)

    workspace = workspace_from_env()
    export_path = workspace / ".index" / "code_graph_rag" / "export.json"
    if export_path.is_file():
        payload = read_export_file(export_path, max_bytes=args.max_bytes)
        preview = payload[: min(len(payload), 4096)].decode("utf-8", errors="replace")
        write_ok({"bytes": len(payload), "query": args.query, "preview": preview})
        return 0

    try:
        code, stdout, stderr = asyncio.run(run_cgr_subprocess("export"))
    except FileNotFoundError as exc:
        write_error(str(exc))
        return 1
    if code != 0:
        write_error(stderr.decode("utf-8", errors="replace") or f"cgr export exited {code}")
        return 1

    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_bytes(stdout)
    payload = read_export_capped(stdout, args.max_bytes)
    preview = payload[: min(len(payload), 4096)].decode("utf-8", errors="replace")
    write_ok({"bytes": len(payload), "query": args.query, "preview": preview})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
