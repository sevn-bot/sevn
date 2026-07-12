#!/usr/bin/env python3
"""Monthly lint report writer for the bundled ``second_brain`` skill.

Module: sevn.data.bundled_skills.core.second_brain.scripts.lint
Depends: argparse, pathlib, ``sevn.second_brain``

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path


def main() -> int:
    """Run lint CLI (``--scope``) and write ``lint-report-*.md``.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import io
        >>> import os
        >>> import sys
        >>> import tempfile
        >>> from contextlib import redirect_stdout
        >>> from pathlib import Path
        >>> base = tempfile.mkdtemp()
        >>> os.environ["SEVN_WORKSPACE"] = base
        >>> wiki = Path(base) / "second_brain" / "users" / "owner" / "wiki"
        >>> _ = wiki.mkdir(parents=True)
        >>> argv_hold = sys.argv
        >>> buf = io.StringIO()
        >>> try:
        ...     sys.argv = ["lint", "--scope", "owner"]
        ...     with redirect_stdout(buf):
        ...         rc = main()
        ... finally:
        ...     sys.argv = argv_hold
        >>> rc == 0
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", default="owner")
    args = parser.parse_args()
    workspace = Path(os.environ.get("SEVN_WORKSPACE", ".")).resolve()
    from sevn.config.loader import SevnJsonNotFoundError, load_workspace
    from sevn.second_brain.lint_local import lint_wiki_tree
    from sevn.second_brain.paths import resolve_scope_root, wiki_dir_for_scope

    try:
        cfg, _layout = load_workspace(sevn_json=workspace / "sevn.json")
        sb_cfg = cfg.second_brain
    except SevnJsonNotFoundError:
        sb_cfg = None
    wiki = wiki_dir_for_scope(resolve_scope_root(workspace, sb_cfg, args.scope))
    issues = lint_wiki_tree(wiki)
    today = date.today().isoformat()
    report = wiki / f"lint-report-{today}.md"
    lines = [
        f"# Lint report {today}",
        "",
        "## Findings",
    ]
    for i in issues:
        lines.append(f"- **{i.severity}** `{i.path}` — {i.message}")
    if not issues:
        lines.append("- (no issues)")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {"report_path": report.relative_to(wiki).as_posix(), "issue_count": len(issues)}
    sys.stdout.write(
        json.dumps({"ok": True, "data": payload, "message": None}, separators=(",", ":"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
