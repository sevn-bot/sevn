#!/usr/bin/env python3
"""Bundled ``media_generation`` skill — generate image via ``media_generator``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import add_prompt_var_args, prompt_vars_from_args, run_media_generation  # noqa: E402


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
    parser.add_argument("prompt", help="Short image intent (augmented with templates)")
    parser.add_argument("--aspect-ratio", default="1:1", dest="aspect_ratio")
    parser.add_argument(
        "--template",
        default=None,
        help="Template slug: default, portrait, product, illustration, cinematic, …",
    )
    add_prompt_var_args(parser)
    args = parser.parse_args()
    extra: dict[str, object] = {"aspect_ratio": args.aspect_ratio}
    if args.template:
        extra["template"] = args.template
    extra.update(prompt_vars_from_args(args))
    return run_media_generation("image", args.prompt, extra=extra)


if __name__ == "__main__":
    raise SystemExit(main())
