"""Tests for evolution slash-command parsing (FL-5.4).

Covers ``_parse_executor_flag``, ``_parse_live_flag``, ``_command_arg``, and the
``EvolutionCommandHandler._handle_fix``/``_handle_feature`` integration paths
for the new ``--executor=`` flag.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution.issues import create_issue
from sevn.gateway.channel_router import IncomingMessage
from sevn.gateway.commands.evolution_commands import (
    EvolutionCommandHandler,
    _command_arg,
    _parse_executor_flag,
    _parse_live_flag,
)
from sevn.workspace.layout import WorkspaceLayout

# ---------------------------------------------------------------------------
# Pure parser unit tests — no I/O
# ---------------------------------------------------------------------------


def test_parse_executor_flag_local() -> None:
    assert _parse_executor_flag("/fix abc --executor=local") == "local"


def test_parse_executor_flag_cloud_maps_to_cursor_cloud() -> None:
    assert _parse_executor_flag("/fix abc --executor=cloud") == "cursor_cloud"


def test_parse_executor_flag_cursor_cloud_passthrough() -> None:
    assert _parse_executor_flag("/fix abc --executor=cursor_cloud") == "cursor_cloud"


def test_parse_executor_flag_chat() -> None:
    assert _parse_executor_flag("/feature abc --executor=chat") == "chat"


def test_parse_executor_flag_absent_returns_none() -> None:
    assert _parse_executor_flag("/fix abc --live") is None


def test_parse_executor_flag_combined_with_live() -> None:
    assert _parse_executor_flag("/fix abc --live --executor=local") == "local"


def test_parse_live_flag_present() -> None:
    assert _parse_live_flag("/fix abc --live") is True


def test_parse_live_flag_absent() -> None:
    assert _parse_live_flag("/fix abc --executor=local") is False


def test_command_arg_strips_flags() -> None:
    assert _command_arg("/fix abc123 --live --executor=local", "/fix") == "abc123"


def test_command_arg_empty_returns_empty() -> None:
    assert _command_arg("/fix", "/fix") == ""


# ---------------------------------------------------------------------------
# Handler integration — mock run_pipeline, assert executor forwarded
# ---------------------------------------------------------------------------


def _make_handler(tmp_path: Path) -> EvolutionCommandHandler:
    """Build an EvolutionCommandHandler pointing at a temp workspace."""
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    router = MagicMock()
    router._resolve_owner_flag.return_value = True
    return EvolutionCommandHandler(
        workspace=cfg,
        layout=layout,
        router=router,
        conn=conn,
    )


async def test_handle_fix_passes_executor_to_run_pipeline(tmp_path: Path) -> None:
    """``/fix <id> --executor=local`` must forward ``executor='local'`` to run_pipeline."""
    import dataclasses

    handler = _make_handler(tmp_path)
    issue = create_issue(handler._layout, kind="bug", title="Bug", state="open")
    mock_result = dataclasses.replace(issue, state="done", pipeline_stage="done")

    with patch(
        "sevn.gateway.commands.evolution_commands.run_pipeline",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_run:
        msg = IncomingMessage(
            channel="telegram",
            user_id="1",
            text=f"/fix {issue.id} --executor=local",
        )
        reply = await handler.handle(msg, session_id="sess")
        assert reply is not None
        assert "done" in reply
        _, kwargs = mock_run.call_args
        assert kwargs.get("executor") == "local"


async def test_handle_fix_executor_cloud_maps_to_cursor_cloud(tmp_path: Path) -> None:
    """``--executor=cloud`` on ``/fix`` must resolve to ``cursor_cloud`` in the call."""
    import dataclasses

    handler = _make_handler(tmp_path)
    issue = create_issue(handler._layout, kind="bug", title="Bug2", state="open")
    mock_result = dataclasses.replace(issue, state="done", pipeline_stage="done")

    with patch(
        "sevn.gateway.commands.evolution_commands.run_pipeline",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_run:
        msg = IncomingMessage(
            channel="telegram",
            user_id="1",
            text=f"/fix {issue.id} --executor=cloud",
        )
        await handler.handle(msg, session_id="sess")
        _, kwargs = mock_run.call_args
        assert kwargs.get("executor") == "cursor_cloud"


async def test_handle_feature_passes_executor_chat(tmp_path: Path) -> None:
    """``/feature <id> --executor=chat`` must forward ``executor='chat'``."""
    import dataclasses

    handler = _make_handler(tmp_path)
    issue = create_issue(handler._layout, kind="feature", title="Feat", state="open")
    mock_result = dataclasses.replace(
        issue, state="awaiting_approval", pipeline_stage="awaiting_approval"
    )

    with patch(
        "sevn.gateway.commands.evolution_commands.run_pipeline",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_run:
        msg = IncomingMessage(
            channel="telegram",
            user_id="1",
            text=f"/feature {issue.id} --executor=chat",
        )
        await handler.handle(msg, session_id="sess")
        _, kwargs = mock_run.call_args
        assert kwargs.get("executor") == "chat"


async def test_handle_fix_no_executor_passes_none(tmp_path: Path) -> None:
    """Without ``--executor``, executor must be ``None`` (config-resolved)."""
    import dataclasses

    handler = _make_handler(tmp_path)
    issue = create_issue(handler._layout, kind="bug", title="Bug3", state="open")
    mock_result = dataclasses.replace(issue, state="done", pipeline_stage="done")

    with patch(
        "sevn.gateway.commands.evolution_commands.run_pipeline",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_run:
        msg = IncomingMessage(
            channel="telegram",
            user_id="1",
            text=f"/fix {issue.id} --live",
        )
        await handler.handle(msg, session_id="sess")
        _, kwargs = mock_run.call_args
        assert kwargs.get("executor") is None
        # --live sets all dry-run flags to False
        assert kwargs.get("ci_dry_run") is False
        assert kwargs.get("promotion_dry_run") is False
        assert kwargs.get("spec_kit_dry_run") is False
