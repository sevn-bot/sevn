#!/usr/bin/env python3
"""Render README Jinja2 templates with fixture data for visual preview (Wave 1).

Module: scripts.readme_render_fixtures
Depends: argparse, pathlib, sys, sevn.docs.readme

Exports:
    main — render all profiles to an output directory; validate GitHub-safe output.

Examples:
    >>> from pathlib import Path
    >>> Path(__file__).name.startswith('readme_render')
    True
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from sevn.docs.readme import PROFILE_TEMPLATES, render_profile  # noqa: E402
from sevn.docs.readme.fixtures import FIXTURE_CONTEXTS  # noqa: E402
from sevn.docs.readme.render import validate_rendered_markdown  # noqa: E402

__all__ = ["main"]


def _output_name(profile: str) -> str:
    """Map profile to preview filename.

        Args:
    profile (str): §C0 profile key.

        Returns:
            str: Markdown filename for preview output.

        Examples:
            >>> _output_name('root')
            'README.preview.md'
            >>> _output_name('subsystem')
            'gateway.preview.md'
    """
    if profile == "root":
        return "README.preview.md"
    slug = FIXTURE_CONTEXTS[profile].get("slug", profile)
    return f"{slug}.preview.md"


def main(argv: list[str] | None = None) -> int:
    """Render every template with fixture data and validate structural rules.

        Args:
    argv (list[str] | None): CLI arguments (``--output-dir``).

        Returns:
            int: 0 when all profiles render and validate; 1 on failure.

        Examples:
            >>> isinstance(main(['--output-dir', '/tmp/sevn-readme-preview-test']), int)
            True
    """
    parser = argparse.ArgumentParser(description="Render README template fixtures for preview.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/sevn-readme-preview"),
        help="Directory for rendered markdown previews (default: /tmp/sevn-readme-preview)",
    )
    args = parser.parse_args(argv)
    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    for profile in PROFILE_TEMPLATES:
        context = FIXTURE_CONTEXTS[profile]
        markdown = render_profile(profile, context)
        validation = validate_rendered_markdown(markdown, repo_root=_REPO)
        if validation:
            errors.extend(f"{profile}: {err}" for err in validation)
        out_path = out_dir / _output_name(profile)
        out_path.write_text(markdown, encoding="utf-8")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print(f"Rendered {len(PROFILE_TEMPLATES)} profiles to {out_dir}")
    for profile in PROFILE_TEMPLATES:
        print(f"  - {_output_name(profile)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
