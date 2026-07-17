#!/usr/bin/env python3
"""Image-to-image via media_generator (reference portrait + style/scene vars)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import run_media_generation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Image-to-image via media_generator")
    parser.add_argument("prompt", help="Short transformation intent")
    parser.add_argument("reference", help="Reference portrait path or URL")
    parser.add_argument(
        "--template", default=None, help="default|style_transfer|wardrobe|background"
    )
    parser.add_argument("--scene", default=None)
    parser.add_argument("--style", default=None)
    parser.add_argument("--mood", default=None)
    parser.add_argument("--aspect-ratio", default="1:1", dest="aspect_ratio")
    args = parser.parse_args()
    extra: dict[str, object] = {
        "reference_image": args.reference,
        "aspect_ratio": args.aspect_ratio,
    }
    if args.template:
        extra["template"] = args.template
    if args.scene:
        extra["scene"] = args.scene
    if args.style:
        extra["style"] = args.style
    if args.mood:
        extra["mood"] = args.mood
    rc: int = run_media_generation("image_i2i", args.prompt, extra=extra)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
