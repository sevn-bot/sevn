"""Wave W1 tests: delivery-integrity fixes (`build-plan-from-review/waves/
voice-duplex-tts-menu-log-fixes-wave-plan.md` W1.10).

Covers the ``sendRichMessage`` -> ``Bad Request: chat not found`` degrade and the
``tier_b.fabricated_file_delivery`` guard gap for "attached/delivered" phrasing that
slips past today's patterns. The guard-tightening assertion is expected to be RED
until Wave W6 lands.
"""

from __future__ import annotations

import pytest

from sevn.agent.grounding import apply_file_delivery_grounding_guard, claims_file_delivery_success
from sevn.channels.telegram_capabilities import RichCapability
from sevn.channels.telegram_rich_fallback import RichFallbackReason, send_with_rich_fallback
from sevn.config.sections.channels import TelegramRichConfig


class _ChatNotFound(ValueError):
    pass


@pytest.mark.asyncio
async def test_send_rich_message_chat_not_found_degrades_to_plain_send() -> None:
    """A ``sendRichMessage`` ``chat not found`` failure must still deliver via legacy send."""
    legacy_calls: list[str] = []
    trace_calls: list[dict[str, object]] = []

    async def _rich_send() -> str:
        raise _ChatNotFound("Bad Request: chat not found")

    async def _legacy_send(body: str) -> str:
        legacy_calls.append(body)
        return "42"

    async def _emit_trace(*, kind: str, status: str, attrs: dict[str, object]) -> None:
        trace_calls.append({"kind": kind, "status": status, **attrs})

    result = await send_with_rich_fallback(
        reply="hello there",
        capability=RichCapability.CAPABLE,
        rich_cfg=TelegramRichConfig(mode="all"),
        parse_mode="HTML",
        legacy_send=_legacy_send,
        rich_send=_rich_send,
        emit_trace=_emit_trace,
    )
    assert result == "42", "chat-not-found on the rich path must not drop the reply"
    assert legacy_calls, "legacy sendMessage must run as the downgrade"
    assert trace_calls, "the downgrade must be logged via emit_trace"
    assert trace_calls[0]["reason"] == RichFallbackReason.SEND_FAILED.value


# --- fabricated_file_delivery guard: saved/delivered/attached claims --------


@pytest.mark.parametrize(
    "claim",
    [
        "I have attached your file below.",
        "The report has been delivered to you.",
        "I attached the report for you.",
    ],
)
def test_claims_file_delivery_success_catches_attached_delivered_phrasing(claim: str) -> None:
    """These phrasings claim delivery but slip past today's narrower regex set."""
    assert claims_file_delivery_success(claim), (
        f"expected a saved/delivered/attached claim to be detected: {claim!r}"
    )


@pytest.mark.parametrize(
    "claim",
    [
        "I have attached your file below.",
        "The report has been delivered to you.",
    ],
)
def test_fabricated_delivery_guard_blocks_claim_without_real_artifact(claim: str) -> None:
    _text, blocked = apply_file_delivery_grounding_guard(claim, successful_tools_called=frozenset())
    assert blocked, f"guard should block an unbacked delivery claim: {claim!r}"
