#!/usr/bin/env python3
"""File-back helper for the bundled ``second_brain`` skill.

Module: sevn.data.bundled_skills.core.second_brain.scripts.file_back
Depends: argparse, pathlib, ``sevn.second_brain``

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
    """Run file-back CLI (``--slug``, ``--title``, …).

    Returns:
        int: ``0`` on success; ``1`` when ``slug`` is invalid.

    Examples:
        >>> import io
        >>> import os
        >>> import sys
        >>> import tempfile
        >>> from contextlib import redirect_stdout
        >>> from pathlib import Path
        >>> base = tempfile.mkdtemp()
        >>> os.environ["SEVN_WORKSPACE"] = base
        >>> argv_hold = sys.argv
        >>> buf = io.StringIO()
        >>> try:
        ...     sys.argv = ["file_back", "--slug", "doc", "--title", "Title"]
        ...     with redirect_stdout(buf):
        ...         rc = main()
        ... finally:
        ...     sys.argv = argv_hold
        >>> rc == 0
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True, help="Filename stem (no .md).")
    parser.add_argument("--title", required=True)
    parser.add_argument("--text", default="")
    parser.add_argument("--body-file", default="")
    parser.add_argument("--scope", default="owner")
    args = parser.parse_args()
    workspace = Path(os.environ.get("SEVN_WORKSPACE", ".")).resolve()
    body = args.text
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    from sevn.config.loader import SevnJsonNotFoundError, load_workspace
    from sevn.second_brain.frontmatter import compose_page, normalise_agent_keys
    from sevn.second_brain.paths import resolve_scope_root, wiki_dir_for_scope

    try:
        cfg, _layout = load_workspace(sevn_json=workspace / "sevn.json")
        sb_cfg = cfg.second_brain
    except SevnJsonNotFoundError:
        sb_cfg = None
    wiki = wiki_dir_for_scope(resolve_scope_root(workspace, sb_cfg, args.scope))
    wiki.mkdir(parents=True, exist_ok=True)
    slug = args.slug.strip().replace("/", "").replace("..", "")
    if not slug:
        sys.stdout.write(
            json.dumps(
                {"ok": False, "error": "invalid slug", "code": "VALIDATION_ERROR"},
                separators=(",", ":"),
            )
        )
        return 1
    path = wiki / f"{slug}.md"
    fm = normalise_agent_keys(
        {
            "type": "Note",
            "title": args.title,
            "sevn_source": "tool:skill:file_back",
        },
    )
    md_body = f"# {args.title}\n\n{body}\n"
    path.write_text(compose_page(fm, md_body), encoding="utf-8")
    idx = wiki / "index.md"
    bullet = f"- [[{slug}]] — {args.title} (file-back)"
    if idx.is_file():
        idx.write_text(idx.read_text(encoding="utf-8").rstrip() + f"\n{bullet}\n", encoding="utf-8")
    else:
        idx.write_text(f"# Index\n\n{bullet}\n", encoding="utf-8")
    sys.stdout.write(
        json.dumps(
            {"ok": True, "data": {"path": path.relative_to(wiki).as_posix()}, "message": None},
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
