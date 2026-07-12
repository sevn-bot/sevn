"""Result fan-out for trigger dispatches (`specs/30-non-interactive-triggers.md` §4.6).

Module: sevn.triggers.delivery
Depends: json, pathlib

Exports:
    trigger_runs_dir — resolve ``.sevn/trigger_runs`` under content root.
    write_log_result — ``LOG`` channel writes JSON summaries under ``.sevn/trigger_runs``.

Examples:
    >>> from sevn.triggers.delivery import trigger_runs_dir
    >>> from pathlib import Path
    >>> trigger_runs_dir(Path("/tmp/r")).name
    'trigger_runs'
"""

from __future__ import annotations

import json
from pathlib import Path

from sevn.triggers.request import DispatchRequest


def trigger_runs_dir(content_root: Path) -> Path:
    """Return ``<content_root>/.sevn/trigger_runs``.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        Path: Directory for JSON summaries.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.triggers.delivery import trigger_runs_dir
        >>> trigger_runs_dir(Path("/w")).parts[-3:]
        ('w', '.sevn', 'trigger_runs')
    """
    return content_root / ".sevn" / "trigger_runs"


def write_log_result(*, content_root: Path, req: DispatchRequest, body: dict[str, object]) -> Path:
    """Persist ``LOG`` channel artefact; return written path.

    Args:
        content_root (Path): Workspace content root.
        req (DispatchRequest): Trigger request envelope.
        body (dict[str, object]): Extra JSON fields merged into the file payload.

    Returns:
        Path: Path to the written ``.json`` file.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.triggers.request import DispatchRequest, ResultChannel
        >>> from sevn.triggers.delivery import write_log_result
        >>> req = DispatchRequest(
        ...     prompt="x",
        ...     result_channel=ResultChannel(kind="LOG"),
        ...     correlation_id="c1",
        ... )
        >>> p = write_log_result(content_root=Path("/tmp"), req=req, body={})
        >>> p.name
        'c1.json'
    """
    d = trigger_runs_dir(content_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{req.correlation_id}.json"
    payload = {
        "correlation_id": req.correlation_id,
        "delivery_mode": req.delivery_mode,
        "routing_mode": req.routing_mode,
        "transport": req.trigger_meta.get("transport"),
        **body,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
