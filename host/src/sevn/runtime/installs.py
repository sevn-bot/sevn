"""Where each CLI runtime's binary comes from (plan 0025 D6).

``resolve(name)`` answers which copy of a runtime the host would run, and from where. This
first cut (W3, for ``sevn doctor``) finds the system copy on ``PATH``; managed installs under
``SEVN_HOME/runtimes`` and the Claude CLI bundled with ``claude-agent-sdk`` come with W4.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type Source = Literal["managed", "system", "bundled"]

#: The CLI runtimes sevn knows how to run.
RUNTIMES: tuple[str, ...] = ("claude", "opencode", "codex", "cursor-agent")


@dataclass(frozen=True, slots=True)
class Resolved:
    """The binary the host would run for one runtime."""

    path: Path
    source: Source
    version: str | None = None


def resolve(name: str) -> Resolved | None:
    """The copy of ``name`` the host would run, or ``None`` when there is none."""
    found = shutil.which(name)
    if found is None or not Path(found).is_absolute():
        return None
    return Resolved(Path(found), "system")
