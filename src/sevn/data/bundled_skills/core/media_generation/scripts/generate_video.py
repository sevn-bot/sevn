#!/usr/bin/env python3
"""Bundled ``media_generation`` skill — generate video via ``media_generator``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import add_prompt_var_args, prompt_vars_from_args, run_media_generation  # noqa: E402


def main() -> int:
    """Run video generation CLI.

    Returns:
        int: ``0`` on success; ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description="Generate a video via media_generator")
    parser.add_argument("prompt", help="Short video intent (augmented with templates)")
    parser.add_argument("--duration", type=int, default=6)
    parser.add_argument("--resolution", default="720P")
    parser.add_argument("--template", default=None, help="Template slug: default, commercial, nature, …")
    parser.add_argument(
        "--image",
        default=None,
        dest="first_frame_image",
        help="Optional first-frame image for image-to-video",
    )
    add_prompt_var_args(parser)
    args = parser.parse_args()
    extra: dict[str, object] = {"duration": args.duration, "resolution": args.resolution}
    if args.template:
        extra["template"] = args.template
    if args.first_frame_image:
        extra["first_frame_image"] = args.first_frame_image
    extra.update(prompt_vars_from_args(args))
    return run_media_generation("video", args.prompt, extra=extra)


if __name__ == "__main__":
    raise SystemExit(main())
