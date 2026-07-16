#!/usr/bin/env python3
"""Bundled ``media_generation`` skill — image-to-video via ``media_generator``.

Module: sevn.data.bundled_skills.core.media_generation.scripts.generate_video_from_image
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
    """Run image-to-video generation CLI.

    Returns:
        int: ``0`` on success; ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description="Generate video from image via media_generator")
    parser.add_argument("prompt", help="Short motion/scene intent (augmented with templates)")
    parser.add_argument("image", help="First-frame image path or URL")
    parser.add_argument("--template", default=None, help="Prompt template slug (default, subtle, dynamic)")
    parser.add_argument("--duration", type=int, default=6)
    parser.add_argument("--resolution", default="1080P")
    args = parser.parse_args()
    extra: dict[str, object] = {
        "first_frame_image": args.image,
        "duration": args.duration,
        "resolution": args.resolution,
    }
    if args.template:
        extra["template"] = args.template
    exit_code: int = run_media_generation("video_i2v", args.prompt, extra=extra)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
