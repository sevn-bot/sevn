#!/usr/bin/env python3
"""Image-to-image via media_generator (reference portrait + style/scene vars)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import add_prompt_var_args, prompt_vars_from_args, run_media_generation  # noqa: E402


def main() -> int:
    """Run image-to-image CLI.

    Returns:
        int: ``0`` on success; ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description="Image-to-image via media_generator")
    parser.add_argument("prompt", help="Short transformation intent")
    parser.add_argument("reference", help="Reference portrait path or URL")
    parser.add_argument(
        "--template",
        default=None,
        help="default|style_transfer|wardrobe|background",
    )
    parser.add_argument("--aspect-ratio", default="1:1", dest="aspect_ratio")
    add_prompt_var_args(parser)
    args = parser.parse_args()
    extra: dict[str, object] = {
        "reference_image": args.reference,
        "aspect_ratio": args.aspect_ratio,
    }
    if args.template:
        extra["template"] = args.template
    extra.update(prompt_vars_from_args(args))
    return run_media_generation("image_i2i", args.prompt, extra=extra)


if __name__ == "__main__":
    raise SystemExit(main())
