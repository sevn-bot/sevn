"""Unit tests for ``WebChatAdapter`` + auth helpers (`specs/19-channel-webui.md`)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import pytest

from sevn.channels.webchat import (
    VALID_CLIENT_FRAME_TYPES,
    WebChatAdapter,
    WebChatConfig,
    webchat_config_from_workspace,
)
from sevn.config.workspace_config import (
    ChannelsWorkspaceSectionConfig,
    WebChatChannelConfig,
    WorkspaceConfig,
)
from sevn.gateway.auth import (
    JWTClaims,
    mint_webchat_jwt,
    verify_telegram_init_data,
    verify_webchat_jwt,
)
from sevn.gateway.channel_router import IncomingMessage, OutgoingMessage
from sevn.gateway.web_transport import WebChannelTransport


class _CaptureWS:
    """Minimal :class:`WebSocketLike` recording every text frame sent."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail = False

    async def send_text(self, data: str) -> None:
        if self.fail:
            raise RuntimeError("simulated")
        self.sent.append(data)


def test_parse_webhook_always_returns_none() -> None:
    adapter = WebChatAdapter()
    assert adapter.parse_webhook({}) is None
    assert adapter.parse_webhook({"message": {"text": "hi"}}) is None


def test_name_is_webchat_and_send_is_coroutine() -> None:
    assert WebChatAdapter().name == "webchat"
    assert asyncio.iscoroutinefunction(WebChatAdapter.send)


def test_valid_client_frame_types_match_spec() -> None:
    assert (
        frozenset(
            {"auth", "message", "callback", "file", "ping"},
        )
        == VALID_CLIENT_FRAME_TYPES
    )


def _claims(sub: str = "u1") -> JWTClaims:
    return JWTClaims(sub=sub, aud="webchat", exp=10**10, scope=("session:read",))


def test_ingest_message_frame_maps_to_incoming_message() -> None:
    adapter = WebChatAdapter()
    msg = adapter.ingest_ws_frame(
        {"type": "message", "text": "hi there", "session_id": "s-1"},
        claims=_claims(),
        client_id="c-1",
        expected_session_id="s-1",
    )
    assert isinstance(msg, IncomingMessage)
    assert msg.channel == "webchat"
    assert msg.user_id == "u1"
    assert msg.text == "hi there"
    assert msg.metadata["session_scope_override"] == "webchat:u1"
    assert msg.metadata["webchat_session_id"] == "s-1"
    assert msg.metadata["client_id"] == "c-1"


def test_ingest_callback_frame_marks_dispatcher_metadata() -> None:
    msg = WebChatAdapter().ingest_ws_frame(
        {"type": "callback", "data": "qa:approve", "session_id": "s-1"},
        claims=_claims(),
        expected_session_id="s-1",
    )
    assert msg is not None
    assert msg.metadata["is_callback"] is True
    assert msg.metadata["callback_data"] == "qa:approve"
    assert msg.text == "qa:approve"


def test_ingest_file_frame_yields_attachment_descriptor() -> None:
    msg = WebChatAdapter().ingest_ws_frame(
        {
            "type": "file",
            "upload_id": "u-42",
            "filename": "doc.txt",
            "session_id": "s-1",
        },
        claims=_claims(),
        expected_session_id="s-1",
    )
    assert msg is not None
    assert msg.text == ""
    assert msg.attachments == [
        {"upload_id": "u-42", "filename": "doc.txt", "source": "webchat"},
    ]


def test_ingest_auth_and_ping_frames_return_none() -> None:
    adapter = WebChatAdapter()
    assert adapter.ingest_ws_frame({"type": "auth"}, claims=_claims()) is None
    assert adapter.ingest_ws_frame({"type": "ping", "session_id": "s-1"}, claims=_claims()) is None


def test_ingest_unknown_frame_returns_none() -> None:
    adapter = WebChatAdapter()
    assert (
        adapter.ingest_ws_frame(
            {"type": "garbage", "session_id": "s-1"},
            claims=_claims(),
            expected_session_id="s-1",
        )
        is None
    )


def test_ingest_missing_session_id_returns_none() -> None:
    adapter = WebChatAdapter()
    assert adapter.ingest_ws_frame({"type": "message", "text": "hi"}, claims=_claims()) is None


def test_ingest_blank_session_id_rejected() -> None:
    adapter = WebChatAdapter()
    assert (
        adapter.ingest_ws_frame(
            {"type": "message", "text": "hi", "session_id": "   "}, claims=_claims()
        )
        is None
    )


def test_ingest_session_mismatch_returns_none() -> None:
    adapter = WebChatAdapter()
    assert (
        adapter.ingest_ws_frame(
            {"type": "message", "text": "hi", "session_id": "wrong"},
            claims=_claims(),
            expected_session_id="expected",
        )
        is None
    )


@pytest.mark.asyncio
async def test_send_fan_out_text_to_subscribed_connections() -> None:
    transport = WebChannelTransport()
    ws_a = _CaptureWS()
    ws_b = _CaptureWS()
    await transport.register(session_id="s-1", client_id="c-a", ws=ws_a)
    await transport.register(session_id="s-1", client_id="c-b", ws=ws_b)
    adapter = WebChatAdapter(transport=transport)
    ids = await adapter.send(
        OutgoingMessage(
            channel="webchat",
            user_id="u1",
            text="hello",
            session_id="s-1",
        ),
    )
    assert len(ids) == 1
    for client in (ws_a, ws_b):
        assert len(client.sent) == 1
        payload = json.loads(client.sent[0])
        assert payload["type"] == "message"
        assert payload["text"] == "hello"
        assert payload["session_id"] == "s-1"
        assert payload["message_id"] == ids[0]


@pytest.mark.asyncio
async def test_send_emits_openui_iframe_src_when_present() -> None:
    transport = WebChannelTransport()
    ws_a = _CaptureWS()
    await transport.register(session_id="s-1", client_id="c-a", ws=ws_a)
    adapter = WebChatAdapter(transport=transport)
    ids = await adapter.send(
        OutgoingMessage(
            channel="webchat",
            user_id="u1",
            text="",
            session_id="s-1",
            metadata={
                "openui_iframe_src": "/openui/abc",
                "openui_title": "report",
            },
        ),
    )
    assert len(ids) == 1
    payload = json.loads(ws_a.sent[0])
    assert payload["type"] == "openui"
    assert payload["iframe_src"] == "/openui/abc"
    assert payload["title"] == "report"


@pytest.mark.asyncio
async def test_send_falls_back_to_openui_html_when_no_iframe_src() -> None:
    transport = WebChannelTransport()
    ws_a = _CaptureWS()
    await transport.register(session_id="s-1", client_id="c-a", ws=ws_a)
    adapter = WebChatAdapter(transport=transport)
    await adapter.send(
        OutgoingMessage(
            channel="webchat",
            user_id="u1",
            text="",
            session_id="s-1",
            metadata={"openui_html": "<p>hi</p>"},
        ),
    )
    payload = json.loads(ws_a.sent[0])
    assert payload["type"] == "openui"
    assert payload["html"] == "<p>hi</p>"


@pytest.mark.asyncio
async def test_send_audio_frame_when_tts_audio_path_and_inline_enabled() -> None:
    transport = WebChannelTransport()
    ws_a = _CaptureWS()
    await transport.register(session_id="s-1", client_id="c-a", ws=ws_a)
    cfg = WebChatConfig(tts_inline=True)
    adapter = WebChatAdapter(transport=transport, config=cfg)
    await adapter.send(
        OutgoingMessage(
            channel="webchat",
            user_id="u1",
            text="reply",
            session_id="s-1",
            metadata={"tts_audio_path": "/media/audio-abc"},
        ),
    )
    types = [json.loads(s)["type"] for s in ws_a.sent]
    assert types == ["message", "audio"]


@pytest.mark.asyncio
async def test_send_audio_frame_suppressed_when_tts_inline_disabled() -> None:
    transport = WebChannelTransport()
    ws_a = _CaptureWS()
    await transport.register(session_id="s-1", client_id="c-a", ws=ws_a)
    cfg = WebChatConfig(tts_inline=False)
    adapter = WebChatAdapter(transport=transport, config=cfg)
    await adapter.send(
        OutgoingMessage(
            channel="webchat",
            user_id="u1",
            text="reply",
            session_id="s-1",
            metadata={"tts_audio_path": "/media/audio-abc"},
        ),
    )
    types = [json.loads(s)["type"] for s in ws_a.sent]
    assert types == ["message"]


@pytest.mark.asyncio
async def test_send_returns_empty_when_no_session_subscribed() -> None:
    transport = WebChannelTransport()
    adapter = WebChatAdapter(transport=transport)
    ids = await adapter.send(
        OutgoingMessage(channel="webchat", user_id="u1", text="x", session_id="s-1"),
    )
    assert ids == []


@pytest.mark.asyncio
async def test_send_returns_empty_when_session_id_missing() -> None:
    adapter = WebChatAdapter(transport=WebChannelTransport())
    ids = await adapter.send(
        OutgoingMessage(channel="webchat", user_id="u1", text="x"),
    )
    assert ids == []


@pytest.mark.asyncio
async def test_transport_unregisters_dead_connections() -> None:
    transport = WebChannelTransport()
    boom = _CaptureWS()
    boom.fail = True
    await transport.register(session_id="s-1", client_id="dead", ws=boom)
    ok = _CaptureWS()
    await transport.register(session_id="s-1", client_id="live", ws=ok)
    n = await transport.send_to_session("s-1", "{}")
    assert n == 1
    assert transport.session_count("s-1") == 1
    assert transport.session_for("dead") is None


def test_jwt_round_trip_and_aud_check() -> None:
    token, expires_in = mint_webchat_jwt(secret="s", sub="u1", ttl_seconds=60, now=1000)
    assert expires_in == 60
    claims = verify_webchat_jwt(secret="s", token=token, now=1010)
    assert claims is not None
    assert claims.sub == "u1"
    assert claims.aud == "webchat"
    assert "session:read" in claims.scope


def test_jwt_rejects_wrong_secret() -> None:
    token, _ = mint_webchat_jwt(secret="s", sub="u1", ttl_seconds=60, now=1000)
    assert verify_webchat_jwt(secret="other", token=token, now=1010) is None


def test_jwt_rejects_expired_token() -> None:
    token, _ = mint_webchat_jwt(secret="s", sub="u1", ttl_seconds=10, now=1000)
    assert verify_webchat_jwt(secret="s", token=token, now=2000) is None


def test_jwt_rejects_tampered_payload() -> None:
    token, _ = mint_webchat_jwt(secret="s", sub="u1", ttl_seconds=60, now=1000)
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload}AAAA.{sig}"
    assert verify_webchat_jwt(secret="s", token=tampered, now=1010) is None


def _build_init_data(*, bot_token: str, fields: dict[str, str]) -> str:
    from urllib.parse import urlencode

    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    h = hmac.new(secret_key, dcs.encode("utf-8"), hashlib.sha256).hexdigest()
    body = dict(fields)
    body["hash"] = h
    return urlencode(body)


def test_init_data_signature_golden_vector_round_trip() -> None:
    fields = {
        "auth_date": "1700000000",
        "user": '{"id":42,"first_name":"Alex","username":"alex"}',
        "query_id": "abc",
    }
    init_data = _build_init_data(bot_token="123:abc", fields=fields)
    got = verify_telegram_init_data(bot_token="123:abc", init_data=init_data)
    assert got is not None
    assert got["auth_date"] == "1700000000"
    assert got["user"] == fields["user"]


def test_init_data_signature_rejects_tampered_field() -> None:
    fields = {
        "auth_date": "1700000000",
        "user": '{"id":42,"first_name":"Alex"}',
    }
    init_data = _build_init_data(bot_token="123:abc", fields=fields)
    tampered = init_data.replace("Alex", "Eve")
    assert verify_telegram_init_data(bot_token="123:abc", init_data=tampered) is None


def test_init_data_missing_hash_rejected() -> None:
    assert (
        verify_telegram_init_data(bot_token="123:abc", init_data="auth_date=1&user=%7B%7D") is None
    )


def test_init_data_rejects_other_bot_token() -> None:
    fields = {"auth_date": "1700000000", "user": '{"id":1}'}
    init_data = _build_init_data(bot_token="real", fields=fields)
    assert verify_telegram_init_data(bot_token="fake", init_data=init_data) is None


def test_init_data_max_age_enforced() -> None:
    fields = {"auth_date": "1000", "user": '{"id":1}'}
    init_data = _build_init_data(bot_token="t", fields=fields)
    assert (
        verify_telegram_init_data(bot_token="t", init_data=init_data, max_age_seconds=60, now=2000)
        is None
    )
    assert (
        verify_telegram_init_data(bot_token="t", init_data=init_data, max_age_seconds=60, now=1030)
        is not None
    )


def test_webchat_config_from_workspace_defaults() -> None:
    cfg = webchat_config_from_workspace(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        )
    )
    assert cfg.allowed_origins == []
    assert cfg.public is False
    assert cfg.tts_inline is True
    assert cfg.jwt_ttl_seconds == 3600


def test_webchat_config_from_workspace_reads_overrides() -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        channels=ChannelsWorkspaceSectionConfig(
            webchat=WebChatChannelConfig(
                allowed_origins=["https://chat.example"],
                public=True,
                tts_inline=False,
                jwt_ttl_seconds=120,
            ),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    cfg = webchat_config_from_workspace(ws)
    assert cfg.allowed_origins == ["https://chat.example"]
    assert cfg.public is True
    assert cfg.tts_inline is False
    assert cfg.jwt_ttl_seconds == 120
