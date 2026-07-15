#!/usr/bin/env python3
"""File-back helper for the bundled ``second_brain`` skill.

Module: sevn.data.bundled_skills.core.second_brain.scripts.file_back
Depends: argparse, pathlib, ``sevn.second_brain``

Exports:
    main — CLI entry; JSON envelope on stdout.

Writes pages under :meth:`~sevn.second_brain.paths.VaultLayout.role_dir` ``curated``
and updates :meth:`~sevn.second_brain.paths.VaultLayout.index_note`.
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
    from sevn.config.workspace_config import SecondBrainWorkspaceConfig
    from sevn.second_brain.frontmatter import compose_page, normalise_agent_keys
    from sevn.second_brain.paths import VaultLayout

    try:
        cfg, _layout = load_workspace(sevn_json=workspace / "sevn.json")
        sb_cfg = cfg.second_brain
    except SevnJsonNotFoundError:
        sb_cfg = None
    sb = sb_cfg or SecondBrainWorkspaceConfig()
    layout = VaultLayout(workspace, sb, args.scope)
    curated = layout.role_dir("curated")
    curated.mkdir(parents=True, exist_ok=True)
    slug = args.slug.strip().replace("/", "").replace("..", "")
    if not slug:
        sys.stdout.write(
            json.dumps(
                {"ok": False, "error": "invalid slug", "code": "VALIDATION_ERROR"},
                separators=(",", ":"),
            )
        )
        return 1
    path = curated / f"{slug}.md"
    fm_keys: dict[str, str] = {
        "title": args.title,
        "sevn_source": "tool:skill:file_back",
    }
    if sb.layout == "legacy":
        fm_keys["type"] = "Note"
    fm = normalise_agent_keys(fm_keys, layout=sb.layout)
    md_body = f"# {args.title}\n\n{body}\n"
    path.write_text(compose_page(fm, md_body), encoding="utf-8")
    idx = layout.index_note()
    bullet = f"- [[{slug}]] — {args.title} (file-back)"
    if idx.is_file():
        idx.write_text(idx.read_text(encoding="utf-8").rstrip() + f"\n{bullet}\n", encoding="utf-8")
    else:
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text(f"# Index\n\n{bullet}\n", encoding="utf-8")
    rel = path.relative_to(curated).as_posix()
    sys.stdout.write(
        json.dumps(
            {"ok": True, "data": {"path": rel}, "message": None},
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
