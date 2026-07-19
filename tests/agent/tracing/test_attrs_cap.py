"""RED suite for trace attrs cap honesty + secrets reconcile log noise (D12, D13; green after W8)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sevn.agent.tracing.sqlite_sink import cap_attrs_json
from sevn.config.defaults import TRACE_ATTRS_JSON_MAX_BYTES

if TYPE_CHECKING:
    from loguru import Record


def _capture_loguru(*, level: str) -> tuple[list[str], int]:
    from loguru import logger as loguru_logger

    captured: list[str] = []

    def _sink(message: Record) -> None:
        captured.append(str(message))

    sink_id = loguru_logger.add(_sink, level=level)
    return captured, sink_id


def test_cap_attrs_json_records_truncated_field_names() -> None:
    """D12: over-cap payloads record original size and which fields were truncated."""
    payload = json.dumps({"tool_result": "x" * (TRACE_ATTRS_JSON_MAX_BYTES + 64)})
    out = cap_attrs_json(payload, max_bytes=128)
    obj = json.loads(out)
    assert obj["_truncated"] is True
    assert obj["_original_bytes"] >= TRACE_ATTRS_JSON_MAX_BYTES
    assert obj.get("_truncated_keys") == ["tool_result"]


async def test_stale_shell_reconcile_logs_info_not_warning(
    monkeypatch,
) -> None:
    """D13: routine stale-shell reconciliation logs at INFO/DEBUG — not WARNING."""
    from loguru import logger as loguru_logger

    import sevn.security.secrets.passphrase_prime as pp
    from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain

    warnings, warn_sink = _capture_loguru(level="WARNING")
    info, info_sink = _capture_loguru(level="INFO")
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "stale-shell")

    async def _fake_fetch(*, key_source: str, service: str | None = None) -> str | None:
        assert key_source == "passphrase"
        return "onboard-pass"

    monkeypatch.setattr(pp, "fetch_unlock_secret_from_keychain", _fake_fetch)
    try:
        replaced = await reconcile_unlock_env_with_keychain(key_source="passphrase")
    finally:
        loguru_logger.remove(warn_sink)
        loguru_logger.remove(info_sink)
    assert replaced is True
    assert warnings == []
    assert any("secrets_unlock_env_stale_replaced" in line for line in info)


async def test_unexpected_unlock_conflict_still_warns() -> None:
    """D13: only genuine unexpected conflicts remain at WARNING."""
    from loguru import logger as loguru_logger

    from sevn.security.secrets.passphrase_prime import log_unlock_env_conflict

    warnings, warn_sink = _capture_loguru(level="WARNING")
    try:
        log_unlock_env_conflict(
            var="SEVN_SECRETS_PASSPHRASE",
            env_value="shell-a",
            keychain_value="shell-b",
            reason="unexpected_conflict",
        )
    finally:
        loguru_logger.remove(warn_sink)
    assert any("conflict" in line.lower() for line in warnings)
