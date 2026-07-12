"""Trigger inbox spill + retention (`specs/30-non-interactive-triggers.md` §3.3).
Module: sevn.triggers.inbox
Depends: pathlib, json
Exports:
    inbox_dir — ``.sevn/inbox/triggers`` path helper.
    maybe_spill_prompt_to_inbox — write oversized prompts beside ``.sevn``.
    prune_inbox_spill — best-effort cap on file count for laptop safety.
Examples:
    >>> from sevn.triggers.inbox import inbox_dir
    >>> from pathlib import Path
    >>> inbox_dir(Path("/w")).name
    'triggers'
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from sevn.config.defaults import DEFAULT_TRIGGERS_INBOX_SPILL_MAX_FILES


def inbox_dir(content_root: Path) -> Path:
    """Return ``<content_root>/.sevn/inbox/triggers``.
    Args:
        content_root (Path): Workspace content root.
    Returns:
        Path: Spill directory for oversized prompts.
    Examples:
        >>> from pathlib import Path
        >>> from sevn.triggers.inbox import inbox_dir
        >>> inbox_dir(Path("/z")).parts[-1]
        'triggers'
    """
    return content_root / ".sevn" / "inbox" / "triggers"


def maybe_spill_prompt_to_inbox(
    *,
    content_root: Path,
    correlation_id: str,
    prompt: str,
    max_inline_bytes: int,
) -> str:
    """Return ``prompt`` unchanged when under cap; else spill JSON and return ``@`` path.
    Args:
        content_root (Path): Workspace content root.
        correlation_id (str): Stable id for the spill filename.
        prompt (str): Original prompt text.
        max_inline_bytes (int): UTF-8 byte cap before spill.
    Returns:
        str: Original prompt or ``@``-relative reference into ``.sevn/inbox``.
    Examples:
        >>> from pathlib import Path
        >>> from sevn.triggers.inbox import maybe_spill_prompt_to_inbox
        >>> maybe_spill_prompt_to_inbox(
        ...     content_root=Path("/tmp"),
        ...     correlation_id="a",
        ...     prompt="hi",
        ...     max_inline_bytes=1000,
        ... )
        'hi'
    """
    raw = prompt.encode("utf-8")
    if len(raw) <= max_inline_bytes:
        return prompt
    d = inbox_dir(content_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{correlation_id}.json"
    path.write_text(
        json.dumps({"prompt": prompt, "correlation_id": correlation_id}, ensure_ascii=False),
        encoding="utf-8",
    )
    rel = path.relative_to(content_root)
    return f"@{rel.as_posix()}"


def prune_inbox_spill(*, content_root: Path, max_files: int | None = None) -> int:
    """Delete oldest spill files when count exceeds ``max_files``.
    Args:
        content_root (Path): Workspace content root.
        max_files (int | None): Cap; default :data:`DEFAULT_TRIGGERS_INBOX_SPILL_MAX_FILES`.
    Returns:
        int: Files removed.
    Examples:
        >>> from pathlib import Path
        >>> from sevn.triggers.inbox import prune_inbox_spill
        >>> prune_inbox_spill(content_root=Path("/nonexistent-xyz")) == 0
        True
    """
    cap = int(max_files if max_files is not None else DEFAULT_TRIGGERS_INBOX_SPILL_MAX_FILES)
    d = inbox_dir(content_root)
    if not d.is_dir():
        return 0
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime)
    extra = len(files) - cap
    removed = 0
    if extra <= 0:
        return 0
    for p in files[:extra]:
        try:
            p.unlink()
            removed += 1
        except OSError:
            logger.exception("trigger_inbox_prune_failed path={}", p)
    return removed
