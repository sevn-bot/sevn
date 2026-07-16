#!/usr/bin/env python3
"""Bundled ``media_generation`` skill — Video Agent template via ``media_generator``.

Module: sevn.data.bundled_skills.core.media_generation.scripts.generate_video_template
Depends: argparse, sevn.data.bundled_skills.core.media_generation.scripts._common

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import run_media_generation  # noqa: E402


def main() -> int:
    """Run Video Agent template generation CLI.

    Returns:
        int: ``0`` on success; ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(
        description="Generate video from a MiniMax Video Agent template via media_generator",
    )
    parser.add_argument(
        "template",
        help="Template slug (e.g. run_for_life) or numeric id",
    )
    parser.add_argument(
        "--prompt",
        default="",
        help="Short user intent (fills text slot when template requires text)",
    )
    parser.add_argument(
        "--text",
        action="append",
        default=[],
        dest="text_inputs",
        help="Text input slot (repeatable)",
    )
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        dest="media_inputs",
        help="Image input path or URL (repeatable)",
    )
    args = parser.parse_args()
    extra: dict[str, object] = {
        "template_id": args.template,
        "text_inputs": args.text_inputs or ([args.prompt] if args.prompt else []),
        "media_inputs": args.media_inputs,
    }
    if args.prompt:
        extra["prompt"] = args.prompt
    exit_code: int = run_media_generation(
        "video_template", args.prompt or args.template, extra=extra
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
