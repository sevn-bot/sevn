#!/usr/bin/env python3
"""Bundled ``media_generation`` skill — list Video Agent templates.

Module: sevn.data.bundled_skills.core.media_generation.scripts.list_video_templates
Depends: sevn.agent.subagents.media_prompts, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import sys

from sevn.agent.subagents.media_prompts import list_video_agent_templates
from sevn.lcm.script_cli import write_ok


def main() -> int:
    """Emit the Video Agent template catalog as JSON.

    Returns:
        int: Always ``0``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    write_ok({"templates": list_video_agent_templates()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
