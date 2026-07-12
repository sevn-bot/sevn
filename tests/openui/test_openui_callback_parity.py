"""OpenUI HTTP vs webchat WS callback parity (`specs/29-openui.md` §10.4)."""

from __future__ import annotations

import json

from sevn.gateway.channel_router import IncomingMessage
from sevn.ui.openui.callback import build_openui_dispatch_payload, normalize_webchat_openui_callback


def test_webchat_openui_json_callback_matches_http_dispatch_metadata() -> None:
    session_id = "sess-ws-1"
    body = {
        "form_id": "openui:agent:pick:submit",
        "parent_message_id": "msg-parent",
        "session_id": session_id,
        "fields": {"choice": "opus"},
    }
    raw = "openui:json:" + json.dumps(body, separators=(",", ":"))
    ws_msg = IncomingMessage(
        channel="webchat",
        user_id="owner",
        text=raw,
        raw={"type": "callback"},
        metadata={
            "is_callback": True,
            "callback_data": raw,
            "session_scope_override": "webchat:owner",
            "webchat_session_id": session_id,
        },
    )
    out = normalize_webchat_openui_callback(ws_msg)
    http = build_openui_dispatch_payload(
        channel="webchat",
        user_id="owner",
        session_id=session_id,
        parent_message_id="msg-parent",
        form_id="openui:agent:pick:submit",
        fields={"choice": "opus"},
    )
    assert out.text == http["text"]
    assert out.metadata["openui_form_fields"] == http["metadata"]["openui_form_fields"]
    assert out.metadata["openui_parent_message_id"] == http["metadata"]["openui_parent_message_id"]
    assert out.metadata["openui_route"] == http["metadata"]["openui_route"]
    assert out.metadata["session_scope_override"] == "webchat:owner"


def test_telegram_adapter_rasterise_caps_defaults() -> None:
    from sevn.channels.telegram import TelegramAdapter

    caps = TelegramAdapter(resolved_bot_token="t").rasterise_caps()
    assert caps.png_max_bytes == 10 * 1024 * 1024
    assert caps.pdf_max_bytes == 50 * 1024 * 1024
    assert caps.image_max_dimension_px == 10_000
