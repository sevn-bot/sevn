"""Tests for rich send decision helpers and fallback contract (R1.3-R1.4, D3-D4)."""

from __future__ import annotations

from typing import Any

import pytest

from sevn.channels.telegram_capabilities import RichCapability
from sevn.channels.telegram_rich import (
    RichFallbackReason,
    is_reply_rich_worthy,
    resolve_rich_config,
    send_with_rich_fallback,
    should_use_rich,
)
from sevn.config.sections.channels import TelegramRichConfig

_TABLE = "| A | B |\n|---|---|\n| 1 | 2 |\n"
_PLAIN = "hello world"


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (_PLAIN, False),
        (_TABLE, True),
        ("<details><summary>x</summary></details>", True),
        ("Inline $x$ math", True),
        ("![img](https://example.com/a.png)", True),
    ],
)
def test_is_reply_rich_worthy(reply: str, expected: bool) -> None:
    assert is_reply_rich_worthy(reply) is expected


@pytest.mark.parametrize(
    ("mode", "capability", "reply", "streaming", "expected"),
    [
        ("off", RichCapability.CAPABLE, _TABLE, False, False),
        ("off", RichCapability.CAPABLE, _PLAIN, True, False),
        ("auto", RichCapability.NOT_CAPABLE, _TABLE, False, False),
        ("auto", RichCapability.CAPABLE, _PLAIN, False, False),
        ("auto", RichCapability.CAPABLE, _TABLE, False, True),
        ("auto", RichCapability.CAPABLE, _PLAIN, True, True),
        ("all", RichCapability.CAPABLE, _PLAIN, False, True),
        ("all", RichCapability.NOT_CAPABLE, _TABLE, False, False),
    ],
)
def test_should_use_rich_matrix(
    mode: str,
    capability: RichCapability,
    reply: str,
    streaming: bool,
    expected: bool,
) -> None:
    cfg = TelegramRichConfig(mode=mode)  # type: ignore[arg-type]
    assert (
        should_use_rich(
            reply,
            capability,
            cfg,
            streaming_active=streaming,
        )
        is expected
    )


def test_resolve_rich_config_defaults_to_auto() -> None:
    assert resolve_rich_config(None).mode == "auto"


@pytest.mark.asyncio
async def test_send_with_rich_fallback_legacy_when_not_gated() -> None:
    from sevn.channels.telegram_format import to_telegram

    seen: list[str] = []

    async def legacy(body: str) -> str:
        seen.append(body)
        return body

    out = await send_with_rich_fallback(
        reply=_PLAIN,
        capability=RichCapability.NOT_CAPABLE,
        rich_cfg=None,
        parse_mode="HTML",
        legacy_send=legacy,
    )
    assert out == to_telegram(_PLAIN, "HTML")
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_send_with_rich_fallback_degrades_and_traces() -> None:
    traces: list[dict[str, Any]] = []

    async def emit_trace(**kwargs: Any) -> None:
        traces.append(kwargs)

    async def legacy(body: str) -> str:
        return f"legacy:{body}"

    async def rich_fail() -> str:
        raise ValueError("rich parse error")

    out = await send_with_rich_fallback(
        reply=_TABLE,
        capability=RichCapability.CAPABLE,
        rich_cfg=TelegramRichConfig(mode="auto"),
        parse_mode="HTML",
        legacy_send=legacy,
        rich_send=rich_fail,
        emit_trace=emit_trace,
    )
    assert out.startswith("legacy:")
    assert traces
    assert traces[0]["kind"] == "channel.telegram.rich_fallback"
    assert traces[0]["attrs"]["reason"] == RichFallbackReason.PARSE_ERROR.value


@pytest.mark.asyncio
async def test_send_with_rich_fallback_rich_unavailable_when_no_renderer() -> None:
    traces: list[dict[str, Any]] = []

    async def emit_trace(**kwargs: Any) -> None:
        traces.append(kwargs)

    async def legacy(body: str) -> str:
        return body

    await send_with_rich_fallback(
        reply=_TABLE,
        capability=RichCapability.CAPABLE,
        rich_cfg=TelegramRichConfig(mode="all"),
        parse_mode="HTML",
        legacy_send=legacy,
        rich_send=None,
        emit_trace=emit_trace,
    )
    assert traces[0]["attrs"]["reason"] == RichFallbackReason.RICH_UNAVAILABLE.value
