"""``InputRichMessage`` shape validation and JSON serialization (R2.4, finding-2 split).

Module: sevn.channels.telegram_rich_validate
Depends: json, typing, collections.abc

Exports:
    validate_rich_message_shape — validate Bot API field shapes.
    serialize_input_rich_message — JSON serializer with size guards (R2.4).

Examples:
    >>> from sevn.channels.telegram_rich_validate import serialize_input_rich_message
    >>> serialize_input_rich_message({"blocks": [{"type": "divider"}]})
    '{"blocks":[{"type":"divider"}]}'
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

MAX_RICH_MESSAGE_JSON_BYTES = 64 * 1024


def validate_rich_message_shape(message: Mapping[str, Any]) -> dict[str, Any]:
    """Validate ``InputRichMessage`` top-level shape and block discriminators.

    Args:
        message (Mapping[str, Any]): Candidate rich message dict.

    Returns:
        dict[str, Any]: Normalised message dict (shallow copy).

    Raises:
        ValueError: When required keys or block types are invalid.

    Examples:
        >>> validate_rich_message_shape({"blocks": [{"type": "divider"}]})
        {'blocks': [{'type': 'divider'}]}
    """
    blocks = message.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError("parse error: InputRichMessage missing blocks list")
    if not blocks:
        raise ValueError("parse error: rich message must be non-empty (no blocks)")
    allowed = {
        "paragraph",
        "heading",
        "divider",
        "list",
        "pre",
        "blockquote",
        "table",
        "details",
        "math",
        "pull_quote",
        "photo",
        "video",
        "audio",
        "voice",
        "animation",
        "collage",
        "slideshow",
        "footer",
        "anchor",
        "thinking",
    }
    media_keys = {
        "photo": "photo",
        "video": "video",
        "audio": "audio",
        "voice": "voice",
        "animation": "animation",
    }
    normalised: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("parse error: block must be a dict")
        block_type = block.get("type")
        if block_type not in allowed:
            raise ValueError(f"parse error: unknown block type {block_type!r}")
        if block_type == "heading":
            level = block.get("level")
            if not isinstance(level, int) or not 1 <= level <= 6:
                raise ValueError("parse error: heading level must be 1-6")
        if block_type == "list":
            style = block.get("style")
            if style not in {"ordered", "unordered", "task"}:
                raise ValueError("parse error: invalid list style")
        if block_type == "table":
            rows = block.get("rows")
            if not isinstance(rows, list) or not rows:
                raise ValueError("parse error: table requires rows")
        if block_type == "details" and ("summary" not in block or "body" not in block):
            raise ValueError("parse error: details requires summary and body")
        if block_type == "anchor" and (not isinstance(block.get("id"), str) or not block["id"]):
            raise ValueError("parse error: anchor requires id")
        if block_type in media_keys:
            media_field = media_keys[block_type]
            if media_field not in block:
                raise ValueError(f"parse error: {block_type} requires {media_field}")
        if block_type == "slideshow" and not isinstance(block.get("slides"), list):
            raise ValueError("parse error: slideshow requires slides list")
        if block_type == "collage" and not isinstance(block.get("media"), list):
            raise ValueError("parse error: collage requires media list")
        normalised.append(dict(block))
    return {"blocks": normalised}


def serialize_input_rich_message(message: Mapping[str, Any]) -> str:
    """Serialize ``InputRichMessage`` to compact JSON with size guards (R2.4).

    Args:
        message (Mapping[str, Any]): Validated rich message dict.

    Returns:
        str: UTF-8 JSON string.

    Raises:
        ValueError: When the payload exceeds :data:`MAX_RICH_MESSAGE_JSON_BYTES`.

    Examples:
        >>> serialize_input_rich_message({"blocks": [{"type": "divider"}]})
        '{"blocks":[{"type":"divider"}]}'
    """
    validated = validate_rich_message_shape(message)
    payload = json.dumps(validated, ensure_ascii=False, separators=(",", ":"))
    if len(payload.encode("utf-8")) > MAX_RICH_MESSAGE_JSON_BYTES:
        raise ValueError("parse error: rich message JSON exceeds size limit")
    return payload
