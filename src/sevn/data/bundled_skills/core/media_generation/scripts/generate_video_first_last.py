#!/usr/bin/env python3
"""First-and-last-frame video via media_generator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import add_prompt_var_args, prompt_vars_from_args, run_media_generation  # noqa: E402


def main() -> int:
    """Run first/last-frame video CLI.

    Returns:
        int: ``0`` on success; ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(
        description="Generate video morphing between first and last frames (FL2V)",
    )
    parser.add_argument("prompt", help="Short transition intent")
    parser.add_argument("first_frame", help="First-frame image path or URL")
    parser.add_argument("last_frame", help="Last-frame image path or URL")
    parser.add_argument("--template", default=None, help="default|growth|morph")
    parser.add_argument("--duration", type=int, default=6)
    parser.add_argument("--resolution", default="1080P")
    add_prompt_var_args(parser)
    args = parser.parse_args()
    extra: dict[str, object] = {
        "first_frame_image": args.first_frame,
        "last_frame_image": args.last_frame,
        "duration": args.duration,
        "resolution": args.resolution,
    }
    if args.template:
        extra["template"] = args.template
    extra.update(prompt_vars_from_args(args))
    return run_media_generation("video_fl2v", args.prompt, extra=extra)


if __name__ == "__main__":
    raise SystemExit(main())
