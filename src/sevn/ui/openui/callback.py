"""Parse OpenUI HTTP callbacks (`specs/29-openui.md` §4.2).

Module: sevn.ui.openui.callback
Depends: urllib.parse, json, sevn.gateway.channel_router (IncomingMessage)

Exports:
    parse_query_dict — flatten ``application/x-www-form-urlencoded`` fields.
    build_openui_dispatch_payload — dict compatible with :class:`IncomingMessage` kwargs.
    normalize_webchat_openui_callback — expand ``openui:json:…`` WS payloads to HTTP parity.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from sevn.gateway.channel_types import IncomingMessage


def parse_query_dict(raw: bytes, *, encoding: str = "utf-8") -> dict[str, str]:
    """Parse URL-encoded form body into a flat string map.

    Args:
        raw (bytes): Raw POST body.
        encoding (str): Body text encoding.

    Returns:
        dict[str, str]: Field name → value (first value wins for duplicates).

    Examples:
        >>> parse_query_dict(b"a=1&b=two")
        {'a': '1', 'b': 'two'}
    """

    text = raw.decode(encoding, errors="replace")
    pairs = urllib.parse.parse_qsl(text, keep_blank_values=True)
    out: dict[str, str] = {}
    for k, v in pairs:
        if k not in out:
            out[k] = v
    return out


def _route_from_form_id(form_id: str) -> str:
    """Return dispatcher route bucket for a namespaced form id.

    Args:
        form_id (str): Form identifier, typically ``openui:agent:…`` or ``openui:cfg:…``.

    Returns:
        str: ``cfg`` when ``form_id`` starts with ``openui:cfg:`` else ``agent``.

    Examples:
        >>> _route_from_form_id("openui:cfg:x")
        'cfg'
        >>> _route_from_form_id("openui:agent:y")
        'agent'
    """

    if form_id.startswith("openui:cfg:"):
        return "cfg"
    return "agent"


def build_openui_dispatch_payload(
    *,
    channel: str,
    user_id: str,
    session_id: str,
    parent_message_id: str,
    form_id: str,
    fields: dict[str, str],
    callback_query_id: str | None = None,
) -> dict[str, Any]:
    """Return kwargs for :class:`sevn.gateway.channel_router.IncomingMessage` (`specs/29-openui.md` §4.2).

    Args:
        channel (str): ``webchat`` / ``telegram`` / …
        user_id (str): Stable user id string.
        session_id (str): Gateway session id.
        parent_message_id (str): Emitting assistant message id.
        form_id (str): Namespace key such as ``openui:agent:pick:submit``.
        fields (dict[str, str]): Parsed form fields.
        callback_query_id (str | None): Telegram spinner id when applicable.

    Returns:
        dict[str, Any]: Keys ``channel``, ``user_id``, ``text``, ``raw``, ``metadata``.

    Examples:
        >>> p = build_openui_dispatch_payload(
        ...     channel="webchat",
        ...     user_id="u1",
        ...     session_id="s1",
        ...     parent_message_id="m1",
        ...     form_id="openui:agent:x:submit",
        ...     fields={"a": "b"},
        ... )
        >>> p["metadata"]["is_callback"]
        True
    """

    structured = {
        "kind": "openui_callback",
        "form_id": form_id,
        "parent_message_id": parent_message_id,
        "fields": dict(fields),
    }
    route = _route_from_form_id(form_id)
    summary_bits = ", ".join(f"{k}={v}" for k, v in sorted(fields.items()) if k != "form_id")
    bracket = f"[user submitted form — {summary_bits}]" if summary_bits else "[user submitted form]"
    text = f"{bracket}\n{json.dumps(structured, separators=(',', ':'), ensure_ascii=False)}"
    meta: dict[str, Any] = {
        "is_callback": True,
        "openui_form_fields": dict(fields),
        "openui_parent_message_id": parent_message_id,
        "openui_form_id": form_id,
        "openui_route": route,
        "session_id": session_id,
    }
    if callback_query_id:
        meta["callback_query_id"] = callback_query_id
    return {
        "channel": channel,
        "user_id": user_id,
        "text": text,
        "raw": {"openui_callback": structured},
        "metadata": meta,
    }


_WEBCHAT_OPENUI_JSON_PREFIX = "openui:json:"


def normalize_webchat_openui_callback(msg: IncomingMessage) -> IncomingMessage:
    """Expand webchat ``callback`` JSON payloads to HTTP callback metadata parity.

    WebSocket clients send ``{"type":"callback","data":"openui:json:"+json}`` where
    ``json`` encodes ``form_id``, ``parent_message_id``, ``fields``, and ``session_id``
    (``prd/10-generated-ui.md`` §5.9). The result matches
    :func:`build_openui_dispatch_payload` fields used by ``POST /openui/callback``.

    Args:
        msg (IncomingMessage): Adapter output for a webchat ``callback`` frame.

    Returns:
        IncomingMessage: Normalised copy when the prefix matches; otherwise ``msg``.

    Examples:
        >>> from sevn.gateway.channel_types import IncomingMessage
        >>> import json
        >>> raw = "openui:json:" + json.dumps(
        ...     {"form_id": "openui:agent:a:submit", "parent_message_id": "m",
        ...      "session_id": "s", "fields": {"x": "1"}},
        ...     separators=(",", ":"),
        ... )
        >>> m = IncomingMessage(
        ...     channel="webchat", user_id="u", text=raw,
        ...     metadata={"callback_data": raw, "session_scope_override": "webchat:u"},
        ... )
        >>> out = normalize_webchat_openui_callback(m)
        >>> out.metadata["openui_form_fields"]["x"]
        '1'
    """

    if msg.channel != "webchat":
        return msg
    md = msg.metadata if isinstance(msg.metadata, dict) else {}
    raw_data = md.get("callback_data")
    if not isinstance(raw_data, str) or not raw_data.startswith(_WEBCHAT_OPENUI_JSON_PREFIX):
        return msg
    suffix = raw_data[len(_WEBCHAT_OPENUI_JSON_PREFIX) :].strip()
    try:
        body = json.loads(suffix)
    except (json.JSONDecodeError, TypeError, ValueError):
        return msg
    if not isinstance(body, dict):
        return msg
    form_id = body.get("form_id")
    parent_message_id = body.get("parent_message_id")
    fields = body.get("fields")
    session_id = body.get("session_id")
    if not isinstance(form_id, str) or not form_id.strip():
        return msg
    if not isinstance(parent_message_id, str) or not parent_message_id.strip():
        return msg
    if not isinstance(session_id, str) or not session_id.strip():
        return msg
    if not isinstance(fields, dict):
        return msg
    fields_s: dict[str, str] = {str(k): str(v) for k, v in fields.items()}
    cq_raw = body.get("callback_query_id")
    cq_id = cq_raw.strip() if isinstance(cq_raw, str) and cq_raw.strip() else None
    dispatch = build_openui_dispatch_payload(
        channel="webchat",
        user_id=msg.user_id,
        session_id=session_id.strip(),
        parent_message_id=parent_message_id.strip(),
        form_id=form_id.strip(),
        fields=fields_s,
        callback_query_id=cq_id,
    )
    merged: dict[str, Any] = {**md, **dispatch["metadata"]}
    raw_frame = msg.raw if isinstance(msg.raw, dict) else {}
    raw_out = {**raw_frame, "openui_ws_json_expanded": True}
    return IncomingMessage(
        channel=msg.channel,
        user_id=msg.user_id,
        text=dispatch["text"],
        raw=raw_out,
        attachments=list(msg.attachments),
        metadata=merged,
    )


__all__ = [
    "build_openui_dispatch_payload",
    "normalize_webchat_openui_callback",
    "parse_query_dict",
]
