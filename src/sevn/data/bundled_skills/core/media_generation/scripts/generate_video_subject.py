#!/usr/bin/env python3
"""Subject-reference video (face-consistent) via media_generator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import add_prompt_var_args, prompt_vars_from_args, run_media_generation  # noqa: E402


def main() -> int:
    """Run subject-reference video CLI.

    Returns:
        int: ``0`` on success; ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(
        description="Generate face-consistent video via media_generator (S2V)",
    )
    parser.add_argument("prompt", help="Short action intent")
    parser.add_argument("subject_reference", help="Face reference image path or URL")
    parser.add_argument("--template", default=None, help="default|talking_head|reaction")
    add_prompt_var_args(parser)
    args = parser.parse_args()
    extra: dict[str, object] = {"subject_reference": args.subject_reference}
    if args.template:
        extra["template"] = args.template
    extra.update(prompt_vars_from_args(args))
    return run_media_generation("video_s2v", args.prompt, extra=extra)


if __name__ == "__main__":
    raise SystemExit(main())
