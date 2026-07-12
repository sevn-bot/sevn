"""Spill-recursion guard tests for ``maybe_spill_large_payload`` (Wave W1).

Covers the root-cause fix for the ``read`` spill infinite loop: a ``read`` of a
spill artifact under ``.sevn/tool_results/`` is terminal and never re-spills, and
spill descriptors carry ``spill_depth`` so a spill-of-a-spill is impossible.
"""

from __future__ import annotations

import json
from pathlib import Path

from sevn.tools.base import (
    _is_spill_artifact_read,
    enveloped_success,
    maybe_spill_large_payload,
)


def _spill_dir(workspace: Path, session_id: str) -> Path:
    return workspace / ".sevn" / "tool_results" / session_id


def test_is_spill_artifact_read_posix() -> None:
    assert _is_spill_artifact_read({"kind": "file", "path": ".sevn/tool_results/sess/abc.json"})


def test_is_spill_artifact_read_windows_separator() -> None:
    assert _is_spill_artifact_read({"kind": "file", "path": ".sevn\\tool_results\\sess\\abc.json"})


def test_is_spill_artifact_read_false_for_regular_file() -> None:
    assert not _is_spill_artifact_read({"kind": "file", "path": "memory/USER.md"})


def test_is_spill_artifact_read_false_for_directory() -> None:
    assert not _is_spill_artifact_read({"kind": "directory", "path": ".sevn/tool_results/sess"})


def test_spill_artifact_read_returns_unchanged_and_writes_nothing(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    session_id = "sess"
    # A big ``read`` envelope whose path is under the spill root.
    read_env = enveloped_success(
        {
            "path": ".sevn/tool_results/sess/already.json",
            "kind": "file",
            "content": "1|" + ("x" * 50_000),
            "line_count": 1,
            "total_lines": 1,
        }
    )
    out = maybe_spill_large_payload(workspace, session_id, envelope_str=read_env)
    assert out == read_env
    # No new artifact directory created by the guard.
    assert not _spill_dir(workspace, session_id).exists()


def test_non_read_payload_still_spills_with_depth(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    session_id = "sess"
    big = enveloped_success({"blob": "y" * 50_000})
    out = maybe_spill_large_payload(workspace, session_id, envelope_str=big)
    data = json.loads(out)["data"]
    assert "spill_path" in data
    assert data["spill_depth"] == 1
    assert _spill_dir(workspace, session_id).is_dir()


def test_end_to_end_spill_then_read_does_not_loop(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    session_id = "sess"

    # Pass 1: a big payload spills and yields a descriptor with a spill_path.
    big = enveloped_success({"blob": "z" * 60_000})
    spilled = maybe_spill_large_payload(workspace, session_id, envelope_str=big)
    descriptor = json.loads(spilled)["data"]
    spill_path = descriptor["spill_path"]
    assert ".sevn/tool_results/" in spill_path.replace("\\", "/")

    # Pass 2: the agent "reads" that artifact — the read envelope is big and its
    # path is under the spill root, so the second pass must return it unchanged.
    artifact_text = (workspace / spill_path).read_text(encoding="utf-8")
    read_env = enveloped_success(
        {
            "path": spill_path,
            "kind": "file",
            "content": "1|" + artifact_text,
            "line_count": 1,
            "total_lines": 1,
        }
    )
    out = maybe_spill_large_payload(workspace, session_id, envelope_str=read_env)
    assert out == read_env
