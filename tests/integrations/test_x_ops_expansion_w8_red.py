"""W8.3 - structured JSON envelopes for W12-W14 ``x_ops`` expansion (#129, stubbed)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from sevn.integrations.social_media.x_ops_dispatch import envelope

_ENVELOPE_KEYS = frozenset({"ok", "medium", "op", "data"})

# Planned facade ops - not on trunk until W12-W14 (D11 incremental ship).
W12_ENGAGEMENT_OPS: tuple[str, ...] = (
    "comment_on_tweet",
    "react_tweet",
)

W13_TIMELINE_OPS: tuple[str, ...] = (
    "get_new_comments_on_tweet",
    "get_tweet_stats",
    "collect_tweet_replies",
)

W14_DISCOVERY_OPS: tuple[str, ...] = (
    "discover_followers",
    "discover_topic_accounts",
    "discover_mutual_graph",
)

EXPANSION_OPS: tuple[tuple[str, ...], ...] = (
    W12_ENGAGEMENT_OPS,
    W13_TIMELINE_OPS,
    W14_DISCOVERY_OPS,
)
ALL_EXPANSION_OPS: tuple[str, ...] = tuple(op for group in EXPANSION_OPS for op in group)
W13_W14_EXPANSION_OPS: tuple[str, ...] = W13_TIMELINE_OPS + W14_DISCOVERY_OPS
W14_ONLY_EXPANSION_OPS: tuple[str, ...] = W14_DISCOVERY_OPS


def _import_x_ops() -> Any:
    from sevn.integrations.social_media import x_ops

    return x_ops


@pytest.mark.parametrize("op_name", W12_ENGAGEMENT_OPS)
def test_w12_expansion_ops_exported_on_x_ops_facade(op_name: str) -> None:
    """W12 #129 engagement ops are callables on ``sevn.integrations.social_media.x_ops``."""
    x_ops = _import_x_ops()
    fn = getattr(x_ops, op_name, None)
    assert callable(fn), f"missing W12 expansion facade op: {op_name}"


@pytest.mark.parametrize("op_name", W13_TIMELINE_OPS)
def test_w13_expansion_ops_exported_on_x_ops_facade(op_name: str) -> None:
    """W13 #129 timeline/comment ops are callables on ``sevn.integrations.social_media.x_ops``."""
    x_ops = _import_x_ops()
    fn = getattr(x_ops, op_name, None)
    assert callable(fn), f"missing W13 expansion facade op: {op_name}"


@pytest.mark.parametrize("op_name", W14_ONLY_EXPANSION_OPS)
@pytest.mark.xfail(reason="green after W14: expansion op exported on facade (#129)", strict=False)
def test_w14_expansion_ops_exported_on_x_ops_facade(op_name: str) -> None:
    """Each planned #129 discovery op is a callable on the facade."""
    x_ops = _import_x_ops()
    fn = getattr(x_ops, op_name, None)
    assert callable(fn), f"missing expansion facade op: {op_name}"


@pytest.mark.asyncio
@pytest.mark.parametrize("op_name", W12_ENGAGEMENT_OPS)
async def test_w12_expansion_op_returns_structured_envelope(op_name: str) -> None:
    """W12 engagement dispatch returns ``{ok, medium, op, data}`` (+ optional ``error``/``code``)."""
    x_ops = _import_x_ops()
    fn = getattr(x_ops, op_name)
    with patch(
        "sevn.integrations.social_media.x_ops_dispatch.resolve_social_medium",
        return_value="twexapi",
    ):
        result = await fn(
            task={"medium": "twexapi", "tweet_id": "123", "text": "hi", "dry_run": True},
            cfg={"integrations": {"twexapi": {"enabled": True}}},
            site="x",
        )
    assert isinstance(result, dict)
    assert _ENVELOPE_KEYS.issubset(result.keys())
    assert result["op"] == op_name
    assert result["medium"] in ("browser", "twexapi")
    assert result["ok"] in (True, False)
    if result["ok"] is False:
        assert result.get("error") or result.get("code")


@pytest.mark.asyncio
@pytest.mark.parametrize("op_name", W13_TIMELINE_OPS)
async def test_w13_expansion_op_returns_structured_envelope(op_name: str) -> None:
    """W13 timeline/comment dispatch returns ``{ok, medium, op, data}`` (+ optional ``error``/``code``)."""
    x_ops = _import_x_ops()
    fn = getattr(x_ops, op_name)
    with patch(
        "sevn.integrations.social_media.x_ops_dispatch.resolve_social_medium",
        return_value="twexapi",
    ):
        result = await fn(
            task={"medium": "twexapi", "tweet_id": "123", "dry_run": True},
            cfg={"integrations": {"twexapi": {"enabled": True}}},
            site="x",
        )
    assert isinstance(result, dict)
    assert _ENVELOPE_KEYS.issubset(result.keys())
    assert result["op"] == op_name
    assert result["medium"] in ("browser", "twexapi")
    assert result["ok"] in (True, False)
    if result["ok"] is False:
        assert result.get("error") or result.get("code")


@pytest.mark.asyncio
@pytest.mark.parametrize("op_name", W14_ONLY_EXPANSION_OPS)
@pytest.mark.xfail(reason="green after W14: stubbed envelope contract (#129)", strict=False)
async def test_w14_expansion_op_stub_returns_structured_envelope(op_name: str) -> None:
    """Stubbed discovery dispatch returns ``{ok, medium, op, data}`` (+ optional ``error``/``code``)."""
    x_ops = _import_x_ops()
    fn = getattr(x_ops, op_name)
    with patch(
        "sevn.integrations.social_media.x_ops_dispatch.resolve_social_medium",
        return_value="twexapi",
    ):
        result = await fn(
            task={"medium": "twexapi", "tweet_id": "123", "dry_run": True},
            cfg={"integrations": {"twexapi": {"enabled": True}}},
            site="x",
        )
    assert isinstance(result, dict)
    assert _ENVELOPE_KEYS.issubset(result.keys())
    assert result["op"] == op_name
    assert result["medium"] in ("browser", "twexapi")
    assert result["ok"] in (True, False)
    if result["ok"] is False:
        assert result.get("error") or result.get("code")


@pytest.mark.asyncio
@pytest.mark.parametrize("op_name", W12_ENGAGEMENT_OPS)
async def test_w12_write_ops_dry_run_returns_planned_envelope(op_name: str) -> None:
    """Posting/engagement ops must dry-run without live writes (D11 guardrail)."""
    x_ops = _import_x_ops()
    fn = getattr(x_ops, op_name)
    with patch(
        "sevn.integrations.social_media.x_ops_dispatch.resolve_social_medium",
        return_value="browser",
    ):
        result = await fn(
            task={"medium": "browser", "tweet_id": "1", "text": "hi", "dry_run": True},
            cfg={"tools": {"browser": {"social": {"x": {"allow_write": True}}}}},
            site="x",
        )
    assert result["ok"] is True
    assert result.get("code") == "DRY_RUN"
    data = result.get("data") or {}
    assert data.get("dry_run") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("op_name", W13_TIMELINE_OPS)
async def test_w13_read_ops_dry_run_returns_planned_envelope(op_name: str) -> None:
    """Timeline/comment read ops honor dry_run without live fetches (D11 guardrail)."""
    x_ops = _import_x_ops()
    fn = getattr(x_ops, op_name)
    with patch(
        "sevn.integrations.social_media.x_ops_dispatch.resolve_social_medium",
        return_value="browser",
    ):
        result = await fn(
            task={"medium": "browser", "tweet_id": "1", "dry_run": True},
            cfg={},
            site="x",
        )
    assert result["ok"] is True
    assert result.get("code") == "DRY_RUN"
    data = result.get("data") or {}
    assert data.get("dry_run") is True
    assert data.get("read") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("op_name", W14_DISCOVERY_OPS)
@pytest.mark.xfail(
    reason="green after W14: discovery ops expose rate-limit codes (#129)", strict=False
)
async def test_w14_discovery_ops_rate_limit_envelope(op_name: str) -> None:
    """Discovery strategies return machine-readable backoff when caps exceeded."""
    x_ops = _import_x_ops()
    fn = getattr(x_ops, op_name)
    with patch(
        "sevn.integrations.social_media.x_ops_dispatch.resolve_social_medium",
        return_value="twexapi",
    ):
        result = await fn(
            task={"medium": "twexapi", "query": "ai", "force_rate_limit": True},
            cfg={"integrations": {"twexapi": {"enabled": True}}},
            site="x",
        )
    assert result["ok"] is False
    assert result.get("code") in ("RATE_LIMITED", "BACKOFF_REQUIRED")
    assert "retry" in str(result.get("error") or "").lower() or result.get("data")


def test_envelope_helper_documents_expansion_contract() -> None:
    """Baseline green: normalized envelope shape is stable for expansion ops."""
    sample = envelope(
        ok=False,
        medium="twexapi",
        op="discover_followers",
        data={"retry_after_s": 30},
        error="rate limited",
        code="RATE_LIMITED",
    )
    assert _ENVELOPE_KEYS.issubset(sample.keys())
    assert sample["code"] == "RATE_LIMITED"
