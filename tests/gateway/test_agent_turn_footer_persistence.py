"""§7 (`PROBLEMS.md` / Step §7) — footer never persists into ``gateway_messages.content``.

The historical bug: ``_intent=NEW · tier=B · conf=0.95_`` appended to assistant
messages survived into LLM context on the next turn (the executor re-reads
recent assistant rows). Step §7 strips the footer at the persistence boundary
so the message body remains clean regardless of the ``show_intent_footer`` /
``channels.telegram.show_routing`` toggles.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import (
    ChannelsWorkspaceSectionConfig,
    TelegramChannelConfig,
    WorkspaceConfig,
)
from sevn.gateway.channel_router import (
    ChannelAdapter,
    ChannelRouter,
    IncomingMessage,
    OutgoingMessage,
)
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.turn.turn_metadata import load_turn_metadata, record_turn_start
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations


class _CaptureAdapter(ChannelAdapter):
    """Records outbound text without doing transport work."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    @property
    def name(self) -> str:
        return "telegram"

    def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
        return None

    async def send(self, message: OutgoingMessage) -> list[str]:
        self.sent.append(message.text)
        return ["1"]


@pytest.mark.asyncio
async def test_footer_in_outbound_is_stripped_from_persisted_content(
    tmp_path: Any,
) -> None:
    """Outbound text may carry the footer; ``gateway_messages.content`` must not."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)

    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(show_routing=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    sessions = SessionManager(conn)
    media = MediaStore(conn, tmp_path)
    router = ChannelRouter(
        workspace=ws,
        content_root=tmp_path,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(tmp_path, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=10.0, refill_per_second=5.0),
        media=media,
    )
    adapter = _CaptureAdapter()
    router.register_adapter(adapter)
    session_id = await sessions.ensure_session(
        scope_key="telegram:42",
        channel="telegram",
        user_id="42",
    )
    # Outbound carrying the historical footer line — simulates what the
    # executor used to emit before §7's strip landed.
    outbound_text = "Here is the answer.\n\n_intent=NEW_REQUEST · tier=B · conf=0.95_"
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="42",
            text=outbound_text,
            session_id=session_id,
            metadata={"chat_id": 42},
        ),
    )
    rows = conn.execute(
        """
        SELECT content FROM gateway_messages
        WHERE session_id = ? AND role = 'assistant'
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()
    assert rows, "expected one persisted assistant row"
    persisted = rows[-1][0]
    # Persistence MUST NOT contain the footer (the §7 invariant).
    assert "intent=NEW_REQUEST" not in persisted
    assert "conf=0.95" not in persisted
    # The body is preserved.
    assert "Here is the answer." in persisted
    # The outbound DID still carry the footer (renderer's responsibility,
    # gated by show_routing / show_intent_footer).
    assert any("intent=NEW_REQUEST" in t for t in adapter.sent)
    conn.close()


@pytest.mark.asyncio
async def test_full_gateway_footer_with_triager_s_is_stripped_from_persistence(
    tmp_path: Any,
) -> None:
    """Wave W3 regression: the canonical footer ``append_routing_footer`` emits
    carries ``· tools=[…] · skills=[…] · triager_s=N`` *after* ``conf=``.

    The 2026-05-30 leak: that suffix slipped past the persistence-time strip, so
    the footer landed in ``gateway_messages.content`` with ``visible_to_llm = 1``
    and the executor read it back and echoed it on the next turn. The persisted
    body MUST contain none of the footer tokens even though the display toggle is
    ON and the outbound copy still shows the footer.
    """
    from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
    from sevn.gateway.routing.routing_footer import append_routing_footer

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)

    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(show_routing=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    sessions = SessionManager(conn)
    media = MediaStore(conn, tmp_path)
    router = ChannelRouter(
        workspace=ws,
        content_root=tmp_path,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(tmp_path, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=10.0, refill_per_second=5.0),
        media=media,
    )
    adapter = _CaptureAdapter()
    router.register_adapter(adapter)
    session_id = await sessions.ensure_session(
        scope_key="telegram:99",
        channel="telegram",
        user_id="99",
    )

    # Build the outbound exactly as the gateway does for a tier-B turn with the
    # routing-footer toggle on: a real footer with the trailing ``triager_s``.
    triage = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["read", "log_query"],
        skills=["lcm"],
        mcp_servers_required=[],
        confidence=0.82,
        requires_vision=False,
        requires_document=False,
    )
    outbound_text = append_routing_footer(
        "Here is the substantive answer.",
        triage,
        triager_ms=8635,
    )
    # Sanity: the outbound copy carries the full footer (the leak source).
    assert "triager_s=9" in outbound_text

    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="99",
            text=outbound_text,
            session_id=session_id,
            metadata={"chat_id": 99},
        ),
    )

    rows = conn.execute(
        """
        SELECT content, visible_to_llm FROM gateway_messages
        WHERE session_id = ? AND role = 'assistant'
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()
    assert rows, "expected one persisted assistant row"
    persisted, visible = rows[-1]
    # The row IS visible to the LLM (it is the real assistant reply) ...
    assert visible == 1
    # ... but it MUST carry none of the footer tokens.
    for token in ("_intent=", "intent=", "tier=", "conf=", "triager_s=", "tools=", "skills="):
        assert token not in persisted, f"footer token {token!r} leaked into visible_to_llm body"
    assert persisted == "Here is the substantive answer."
    # The outbound still renders the footer (display toggle on).
    assert any("triager_s=9" in t for t in adapter.sent)
    conn.close()


@pytest.mark.asyncio
async def test_clean_outbound_persists_unchanged(tmp_path: Any) -> None:
    """When no footer is present, the body persists unchanged."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    sessions = SessionManager(conn)
    router = ChannelRouter(
        workspace=ws,
        content_root=tmp_path,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(tmp_path, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=10.0, refill_per_second=5.0),
        media=MediaStore(conn, tmp_path),
    )
    adapter = _CaptureAdapter()
    router.register_adapter(adapter)
    session_id = await sessions.ensure_session(
        scope_key="telegram:7",
        channel="telegram",
        user_id="7",
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="7",
            text="A clean reply with no footer.",
            session_id=session_id,
            metadata={"chat_id": 7},
        ),
    )
    rows = conn.execute(
        "SELECT content FROM gateway_messages WHERE session_id = ? AND role = 'assistant'",
        (session_id,),
    ).fetchall()
    assert rows
    assert rows[-1][0] == "A clean reply with no footer."
    conn.close()


def test_turn_metadata_holds_intent_after_record_start() -> None:
    """``record_turn_start`` writes the classifier output to the sibling table —
    the renderer reads from there to attach the footer when the toggle is on,
    rather than parsing it back out of ``gateway_messages.content``."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("s", "telegram:1", "telegram", "1", "now", "now"),
    )
    conn.commit()
    record_turn_start(
        conn,
        turn_id="t",
        session_id="s",
        intent="NEW_REQUEST",
        tier="B",
        confidence=0.82,
    )
    meta = load_turn_metadata(conn, "t")
    assert meta is not None
    assert meta.intent == "NEW_REQUEST"
    assert meta.tier == "B"
    assert meta.confidence == 0.82
    conn.close()
