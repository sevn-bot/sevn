"""Doctor / live-validate Web App HTTPS notice (`prd/06` §5.15)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.config.workspace_config import WorkspaceConfig

if TYPE_CHECKING:
    import pytest
from sevn.gateway.webapp_qa import maybe_log_qa_bar_webapp_disabled, webapp_https_disabled_notice
from sevn.onboarding.live_validate import probe_webapp_https


def test_webapp_notice_for_http_gateway_base() -> None:
    notice = webapp_https_disabled_notice("http://127.0.0.1:3001")
    assert notice is not None
    assert "not HTTPS" in notice
    assert "share/feedback" in notice


def test_probe_webapp_https_warns_on_http_base() -> None:
    chk = probe_webapp_https(
        merged_preview={
            "schema_version": 1,
            "gateway": {
                "host": "127.0.0.1",
                "port": 3001,
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
        },
    )
    assert chk.check_id == "webapp_https"
    assert chk.severity == "warn"
    assert chk.detail is not None
    assert "not HTTPS" in chk.detail


def test_maybe_log_qa_bar_webapp_disabled_emits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loguru import logger as loguru_logger

    monkeypatch.setattr(
        "sevn.gateway.webapp_qa._QA_BAR_WEBAPP_DISABLED_BASES_SEEN",
        set(),
    )
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    messages: list[str] = []
    handler_id = loguru_logger.add(messages.append, format="{message}", level="INFO")
    try:
        first = maybe_log_qa_bar_webapp_disabled(ws, once_per_base=True)
        second = maybe_log_qa_bar_webapp_disabled(ws, once_per_base=True)
    finally:
        loguru_logger.remove(handler_id)
    assert first is not None
    assert second == first
    matches = [m for m in messages if "qa_bar_webapp_disabled" in m]
    assert len(matches) == 1
