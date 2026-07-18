#!/usr/bin/env python3
"""Bundled ``media_generation`` skill — generate music via ``media_generator``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import add_prompt_var_args, prompt_vars_from_args, run_media_generation  # noqa: E402


def main() -> int:
    """Run music generation CLI.

    Returns:
        int: ``0`` on success; ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description="Generate music via media_generator")
    parser.add_argument("prompt", help="Short music intent (augmented with templates)")
    parser.add_argument("--lyrics", default=None, help="Optional vocal lyrics")
    parser.add_argument("--instrumental", action="store_true")
    parser.add_argument(
        "--template",
        default=None,
        help="Template slug: default, lofi, cinematic, jingle, ambient, …",
    )
    add_prompt_var_args(parser)
    args = parser.parse_args()
    extra: dict[str, object] = {"is_instrumental": bool(args.instrumental)}
    if args.lyrics:
        extra["lyrics"] = args.lyrics
    if args.template:
        extra["template"] = args.template
    extra.update(prompt_vars_from_args(args))
    return run_media_generation("music", args.prompt, extra=extra)


if __name__ == "__main__":
    raise SystemExit(main())
