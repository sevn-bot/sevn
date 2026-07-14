"""First-session BOOTSTRAP intro state (`specs/17-gateway.md` §2.6)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.onboarding.first_session import (
    bootstrap_capture_active,
    count_user_messages,
    first_session_intro_max_output_tokens,
    intro_state_for_session,
    is_first_session_turn,
    mark_intro_state,
    maybe_reseed_bootstrap_at_boot,
)
from sevn.gateway.session_manager import SessionManager
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_USER_INCOMPLETE_MARKER = "<!-- sevn-bootstrap:user-incomplete -->"


async def _seed_session(conn: sqlite3.Connection) -> str:
    sm = SessionManager(conn)
    return await sm.ensure_session(
        scope_key="webchat:test-user",
        channel="webchat",
        user_id="test-user",
    )


def _workspace_layout(tmp_path: Path) -> tuple[WorkspaceConfig, WorkspaceLayout]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, ws)
    return ws, layout


def test_first_session_detected_before_intro_done() -> None:
    import asyncio

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    sid = asyncio.run(_seed_session(conn))
    assert is_first_session_turn(conn, sid, workspace=ws) is True


def test_intro_state_marked_done() -> None:
    import asyncio

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    sid = asyncio.run(_seed_session(conn))
    mark_intro_state(conn, sid, "done")
    assert intro_state_for_session(conn, sid) == "done"
    assert is_first_session_turn(conn, sid, workspace=ws) is False


def test_intro_metadata_persisted() -> None:
    import asyncio

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    sid = asyncio.run(_seed_session(conn))
    mark_intro_state(conn, sid, "skipped")
    row = conn.execute(
        "SELECT metadata_json FROM gateway_sessions WHERE session_id = ?",
        (sid,),
    ).fetchone()
    assert row is not None
    meta = json.loads(str(row[0]))
    assert meta.get("intro_state") == "skipped"


def test_missing_user_md_intro_runs_and_boot_reseeds(tmp_path: Path) -> None:
    import asyncio

    ws, layout = _workspace_layout(tmp_path)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    sid = asyncio.run(_seed_session(conn))
    assert not (layout.content_root / "USER.md").is_file()
    assert is_first_session_turn(
        conn,
        sid,
        workspace=ws,
        content_root=layout.content_root,
        agent_name="Sevn",
    )
    written = maybe_reseed_bootstrap_at_boot(conn, workspace=ws, layout=layout)
    assert any(p.name == "USER.md" for p in written)
    assert (layout.content_root / "USER.md").is_file()


def test_placeholder_name_intro_runs_despite_intro_state_done(tmp_path: Path) -> None:
    import asyncio

    ws, layout = _workspace_layout(tmp_path)
    user_path = layout.content_root / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text(
        "# User\n\n- **Name:** _(your preferred name)_\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    sid = asyncio.run(_seed_session(conn))
    mark_intro_state(conn, sid, "done")
    assert intro_state_for_session(conn, sid) == "done"
    assert (
        is_first_session_turn(
            conn,
            sid,
            workspace=ws,
            content_root=layout.content_root,
            agent_name="Sevn",
        )
        is True
    )


def test_filled_user_md_suppresses_intro_despite_pending_state(tmp_path: Path) -> None:
    import asyncio

    ws, layout = _workspace_layout(tmp_path)
    user_path = layout.content_root / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text(
        "# User\n\n- **Name:** Alex\n- **Role:** builder\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    sid = asyncio.run(_seed_session(conn))
    assert intro_state_for_session(conn, sid) == "pending"
    assert (
        is_first_session_turn(
            conn,
            sid,
            workspace=ws,
            content_root=layout.content_root,
            agent_name="Sevn",
        )
        is False
    )


def test_boot_reseed_writes_marker_on_fresh_user_md(tmp_path: Path) -> None:
    ws, layout = _workspace_layout(tmp_path)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    maybe_reseed_bootstrap_at_boot(conn, workspace=ws, layout=layout)
    user_md = (layout.content_root / "USER.md").read_text(encoding="utf-8")
    assert _USER_INCOMPLETE_MARKER in user_md


def test_bootstrap_capture_active_after_intro_until_user_md_complete(
    tmp_path: Path,
) -> None:
    import asyncio

    ws, layout = _workspace_layout(tmp_path)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    sid = asyncio.run(_seed_session(conn))
    maybe_reseed_bootstrap_at_boot(conn, workspace=ws, layout=layout)
    mark_intro_state(conn, sid, "done")
    assert (
        bootstrap_capture_active(
            conn,
            sid,
            workspace=ws,
            content_root=layout.content_root,
            agent_name="Sevn",
        )
        is True
    )
    (layout.content_root / "USER.md").write_text(
        "# User\n\n## Profile\n\n"
        "- **Name:** Alex\n"
        "- **Role:** _(what you do day to day)_\n"
        "- **Timezone:** _(e.g. America/New_York)_\n\n"
        "## Communication\n\n"
        "- **Style:** _(brief / detailed / bullet lists)_\n"
        "- **Language:** _(primary language for replies)_\n\n"
        "## Preferences\n\n"
        "- _(tools you prefer, topics to avoid, standing priorities)_\n",
        encoding="utf-8",
    )
    assert (
        bootstrap_capture_active(
            conn,
            sid,
            workspace=ws,
            content_root=layout.content_root,
            agent_name="Sevn",
        )
        is True
    )
    (layout.content_root / "USER.md").write_text(
        "# User\n\n## Profile\n\n"
        "- **Name:** Alex\n"
        "- **Role:** engineer\n"
        "- **Timezone:** America/New_York\n\n"
        "## Communication\n\n"
        "- **Style:** brief\n"
        "- **Language:** English\n\n"
        "## Preferences\n\n"
        "- async updates only\n",
        encoding="utf-8",
    )
    assert (
        bootstrap_capture_active(
            conn,
            sid,
            workspace=ws,
            content_root=layout.content_root,
            agent_name="Sevn",
        )
        is False
    )


def test_first_session_intro_max_output_tokens_defaults() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    assert first_session_intro_max_output_tokens(ws, model_id="openai:gpt-4o") == 4096


def test_incomplete_user_md_intro_uses_live_session_message_count(tmp_path: Path) -> None:
    """After ``/new``, intro runs on first ``Hi`` even when scope has older messages."""
    import asyncio

    ws, layout = _workspace_layout(tmp_path)
    user_path = layout.content_root / "USER.md"
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text(
        f"# User\n\n- **Name:** _(your preferred name)_\n\n{_USER_INCOMPLETE_MARKER}\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    sm = SessionManager(conn, content_root=layout.content_root)

    async def _run() -> tuple[str, str]:
        old_sid = await sm.ensure_session(
            scope_key="telegram:scope-hist",
            channel="telegram",
            user_id="u-hist",
        )
        for i in range(3):
            await sm.add_message(
                old_sid,
                role="user",
                kind="message",
                content=f"old-{i}",
                visible_to_llm=1,
                status="sent",
                metadata_blob=None,
                turn_id=f"t-old-{i}",
            )
        assert count_user_messages(conn, old_sid, channel="telegram", user_id="u-hist") == 3
        new_sid = await sm.rotate_session(old_sid, content_root=layout.content_root)
        await sm.add_message(
            new_sid,
            role="user",
            kind="message",
            content="Hi",
            visible_to_llm=1,
            status="sent",
            metadata_blob=None,
            turn_id="t-new-1",
        )
        return old_sid, new_sid

    _old, new_sid = asyncio.run(_run())
    assert count_user_messages(conn, new_sid, channel="telegram", user_id="u-hist") == 4
    assert (
        is_first_session_turn(
            conn,
            new_sid,
            workspace=ws,
            content_root=layout.content_root,
            channel="telegram",
            user_id="u-hist",
            agent_name="Sevn",
        )
        is True
    )


def test_incomplete_user_md_no_intro_on_second_message_in_same_session(
    tmp_path: Path,
) -> None:
    import asyncio

    ws, layout = _workspace_layout(tmp_path)
    (layout.content_root / "USER.md").write_text(
        f"- **Name:** _(your preferred name)_\n{_USER_INCOMPLETE_MARKER}\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    sm = SessionManager(conn)

    async def _run() -> str:
        sid = await sm.ensure_session(
            scope_key="telegram:two-msg",
            channel="telegram",
            user_id="u-two",
        )
        for text in ("Hi", "Alex"):
            await sm.add_message(
                sid,
                role="user",
                kind="message",
                content=text,
                visible_to_llm=1,
                status="sent",
                metadata_blob=None,
                turn_id=f"t-{text}",
            )
        return sid

    sid = asyncio.run(_run())
    assert (
        is_first_session_turn(
            conn,
            sid,
            workspace=ws,
            content_root=layout.content_root,
            agent_name="Sevn",
        )
        is False
    )


def test_first_session_intro_max_output_tokens_clamped_to_tier_cap() -> None:
    from sevn.config.workspace_config import GatewayBudgetConfig, GatewayConfig

    ws = WorkspaceConfig(
        schema_version=1,
        gateway=GatewayConfig(
            first_session_intro={"max_output_tokens": 3000},
            budget=GatewayBudgetConfig(tier_b_max_output_tokens=5000),
            token="${SECRET:keychain:sevn.gateway.token}",
        ),
    )
    assert first_session_intro_max_output_tokens(ws, model_id="openai:gpt-4o") == 3000

    ws_tier_lower = WorkspaceConfig(
        schema_version=1,
        gateway=GatewayConfig(
            first_session_intro={"max_output_tokens": 5000},
            budget=GatewayBudgetConfig(tier_b_max_output_tokens=5000),
            token="${SECRET:keychain:sevn.gateway.token}",
        ),
    )
    assert first_session_intro_max_output_tokens(ws_tier_lower, model_id="openai:gpt-4o") == 5000
