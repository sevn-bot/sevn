#!/usr/bin/env python3
"""Live ingest step for the bundled ``second_brain`` skill.

Module: sevn.data.bundled_skills.core.second_brain.scripts.ingest
Depends: argparse, pathlib, ``sevn.second_brain.ingest``

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    """Run live ingest CLI (``--raw``, ``--scope``).

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import io
        >>> import os
        >>> import sys
        >>> import tempfile
        >>> from contextlib import redirect_stdout
        >>> from pathlib import Path
        >>> base = tempfile.mkdtemp()
        >>> os.environ["SEVN_WORKSPACE"] = base
        >>> raw_dir = Path(base) / "second_brain" / "users" / "owner" / "raw"
        >>> _ = raw_dir.mkdir(parents=True)
        >>> _ = (raw_dir / "note.md").write_text("# Note\\nbody", encoding="utf-8")
        >>> argv_hold = sys.argv
        >>> buf = io.StringIO()
        >>> try:
        ...     sys.argv = ["ingest", "--raw", "note.md"]
        ...     with redirect_stdout(buf):
        ...         rc = main()
        ... finally:
        ...     sys.argv = argv_hold
        >>> rc == 0
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True, help="Path relative to scope raw/ (POSIX).")
    parser.add_argument("--scope", default="owner")
    args = parser.parse_args()
    workspace = Path(os.environ.get("SEVN_WORKSPACE", ".")).resolve()
    from sevn.config.loader import SevnJsonNotFoundError, load_workspace
    from sevn.second_brain.ingest import run_ingest
    from sevn.second_brain.paths import resolve_scope_root

    try:
        cfg, _layout = load_workspace(sevn_json=workspace / "sevn.json")
        sb_cfg = cfg.second_brain
    except SevnJsonNotFoundError:
        sb_cfg = None
    scope_path = resolve_scope_root(workspace, sb_cfg, args.scope)
    try:
        out = run_ingest(
            workspace_root=workspace,
            vault_users_scope=scope_path,
            raw_relpath=args.raw,
            sevn_source="tool:skill:ingest",
        )
    except (OSError, FileNotFoundError) as exc:
        sys.stdout.write(
            json.dumps(
                {"ok": False, "error": str(exc), "code": "VALIDATION_ERROR"}, separators=(",", ":")
            )
        )
        return 1
    sys.stdout.write(json.dumps({"ok": True, "data": out, "message": None}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
