"""Validate CLI help panels and bundled guides (`plan/cli-comprehensive-parity-doctor` W7).

Module: scripts.check_cli_help_docs
Depends: pathlib, sevn.cli.app, sevn.cli.help.guide, sevn.cli.help.panels

Exports:
    main — exit 1 on panel or guide drift.

Examples:
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import sys
from pathlib import Path

from sevn.cli.app import app
from sevn.cli.help.guide import GUIDE_TOPICS, list_guide_topics
from sevn.cli.help.panels import PANEL_ORDER, ROOT_COMMAND_PANELS, iter_root_click_commands

REPO = Path(__file__).resolve().parents[1]
GUIDES_DIR = REPO / "src" / "sevn" / "data" / "cli_guides"


def main() -> int:
    """Verify root command panels and bundled guide topics.

    Returns:
        int: ``0`` when clean; ``1`` on drift.

    Examples:
        >>> main() in (0, 1)
        True
    """
    errors: list[str] = []

    observed = dict(iter_root_click_commands(app))
    if not observed:
        errors.append("no root commands registered on sevn.cli.app.app")

    for name, expected in sorted(ROOT_COMMAND_PANELS.items()):
        if name not in observed:
            errors.append(f"ROOT_COMMAND_PANELS lists missing root command: {name!r}")
            continue
        actual = observed[name]
        if actual != expected:
            errors.append(f"panel drift for {name!r}: expected {expected!r}, got {actual!r}")

    for name, panel in sorted(observed.items()):
        if name not in ROOT_COMMAND_PANELS:
            errors.append(f"root command {name!r} missing from ROOT_COMMAND_PANELS")
        elif panel not in PANEL_ORDER:
            errors.append(f"command {name!r} has unknown panel {panel!r}")

    for topic in GUIDE_TOPICS:
        path = GUIDES_DIR / f"{topic}.md"
        if not path.is_file():
            errors.append(f"missing guide file: {path}")

    live_topics = list_guide_topics()
    for topic in GUIDE_TOPICS:
        if topic not in live_topics:
            errors.append(f"guide topic {topic!r} not discoverable via list_guide_topics()")

    extra = sorted(set(live_topics) - set(GUIDE_TOPICS))
    if extra:
        errors.append(f"guide files on disk not listed in GUIDE_TOPICS: {extra}")

    if errors:
        for line in errors:
            print(line, file=sys.stderr)
        return 1
    print(f"cli-help-docs-check ok: {len(observed)} root commands, {len(GUIDE_TOPICS)} guides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
