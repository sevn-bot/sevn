"""Shared helpers for ``media_generation`` bundled skill scripts (W8.1).

Module: sevn.data.bundled_skills.core.media_generation.scripts._common
Depends: asyncio, os, sevn.agent.subagents.media_worker, sevn.lcm.script_cli

Exports:
    content_root_from_env — resolve real workspace content root.
    run_media_generation — execute one media job and emit JSON envelope.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Literal

from sevn.agent.subagents.media_minimax import MiniMaxMediaError
from sevn.agent.subagents.media_worker import execute_media_generator_task
from sevn.config.loader import load_workspace
from sevn.lcm.script_cli import open_workspace_db, write_error, write_ok, workspace_from_env

MediaKind = Literal["image", "video", "video_i2v", "video_template", "music", "voice"]


def content_root_from_env() -> Path:
    """Return the real workspace content root for media persistence.

    Returns:
        Path: ``SEVN_CONTENT_ROOT`` when set, else :func:`workspace_from_env`.

    Examples:
        >>> content_root_from_env().is_absolute()
        True
    """
    raw = os.environ.get("SEVN_CONTENT_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return workspace_from_env()


def _session_id_from_env() -> str:
    """Resolve gateway session id from ``SEVN_SESSION_ID``.

    Returns:
        str: Session id or ``default`` when unset.

    Examples:
        >>> isinstance(_session_id_from_env(), str)
        True
    """
    sid = os.environ.get("SEVN_SESSION_ID", "").strip()
    return sid or "default"


async def _run_async(
    kind: MediaKind,
    prompt: str,
    *,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Execute one media generation job asynchronously.

    Args:
        kind (MediaKind): ``image`` / ``video`` / ``music``.
        prompt (str): User prompt.
        extra (dict[str, object] | None, optional): Additional JSON task fields.

    Returns:
        dict[str, object]: Worker result payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_run_async)
        True
    """
    content_root = content_root_from_env()
    cfg, _layout = load_workspace(start_dir=content_root)
    session_id = _session_id_from_env()
    body: dict[str, object] = {"kind": kind, "prompt": prompt.strip()}
    if extra:
        body.update(extra)
    task = json.dumps(body, separators=(",", ":"))
    conn = open_workspace_db(content_root)
    try:
        return await execute_media_generator_task(
            task,
            session_id=session_id,
            content_root=content_root,
            conn=conn,
            subagents_cfg=cfg.subagents,
        )
    finally:
        conn.close()


def run_media_generation(
    kind: MediaKind,
    prompt: str,
    *,
    extra: dict[str, object] | None = None,
) -> int:
    """Run one media job and write the skill JSON envelope to stdout.

    Args:
        kind (MediaKind): Media kind.
        prompt (str): Text prompt.
        extra (dict[str, object] | None, optional): Extra task JSON fields.

    Returns:
        int: ``0`` on success, ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(run_media_generation)
        True
    """
    try:
        payload = asyncio.run(_run_async(kind, prompt, extra=extra))
    except MiniMaxMediaError as exc:
        write_error(code="MEDIA_GENERATOR_ERROR", error=str(exc))
        return 1
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    except Exception as exc:  # pragma: no cover — unexpected upstream failures
        write_error(code="INTERNAL_ERROR", error=str(exc))
        return 1
    write_ok(payload)
    return 0


def main_guard() -> None:
    """Ensure this helper module is not executed as a script entrypoint.

    Examples:
        >>> main_guard()  # doctest: +SKIP
    """
    if __name__ == "__main__":
        sys.exit(0)
