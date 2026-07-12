#!/usr/bin/env python3
"""Bundled ``media_generation`` skill — generate image via ``media_generator``.

Module: sevn.data.bundled_skills.core.media_generation.scripts.generate_image
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
    """Run image generation CLI.

    Returns:
        int: ``0`` on success; ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description="Generate an image via media_generator")
    parser.add_argument("prompt", help="Text prompt")
    parser.add_argument("--aspect-ratio", default="1:1", dest="aspect_ratio")
    args = parser.parse_args()
    exit_code: int = run_media_generation(
        "image",
        args.prompt,
        extra={"aspect_ratio": args.aspect_ratio},
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
