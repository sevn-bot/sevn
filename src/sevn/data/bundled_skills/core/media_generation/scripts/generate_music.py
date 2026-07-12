#!/usr/bin/env python3
"""Bundled ``media_generation`` skill — generate music via ``media_generator``.

Module: sevn.data.bundled_skills.core.media_generation.scripts.generate_music
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
    """Run music generation CLI.

    Returns:
        int: ``0`` on success; ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description="Generate music via media_generator")
    parser.add_argument("prompt", help="Style / mood prompt")
    parser.add_argument("--lyrics", default=None, help="Optional vocal lyrics")
    parser.add_argument("--instrumental", action="store_true")
    args = parser.parse_args()
    extra: dict[str, object] = {"is_instrumental": bool(args.instrumental)}
    if args.lyrics:
        extra["lyrics"] = args.lyrics
    return run_media_generation("music", args.prompt, extra=extra)


if __name__ == "__main__":
    raise SystemExit(main())
