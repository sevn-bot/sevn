#!/usr/bin/env python3
"""List augmentation prompt templates for media_generation."""

from __future__ import annotations

import argparse
import json
import sys

from sevn.agent.subagents.media_prompts import PROMPT_VARIABLES, list_prompt_templates
from sevn.lcm.script_cli import write_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="List media_generation prompt templates")
    parser.add_argument("--kind", default=None, help="Filter: image, video, music, voice, …")
    args = parser.parse_args()
    payload = {
        "variables": list(PROMPT_VARIABLES),
        "templates": list_prompt_templates(args.kind),  # type: ignore[arg-type]
    }
    write_ok(payload)
    if "--json" in sys.argv:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
