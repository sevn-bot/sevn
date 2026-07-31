"""W35.4 — gateway boots without a microphone (#102 → W36/W37, D25)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from tests.open_issues_sweep.batch_g.conftest import (
    activation_enabled_workspace_doc,
    gateway_test_client,
    import_voice_activation_module,
)


@pytest.mark.xfail(
    reason="green after W36: lifespan completes with activation enabled, no mic", strict=False
)
def test_gateway_lifespan_completes_with_activation_enabled_no_device(tmp_path: Path) -> None:
    import_voice_activation_module()
    doc = activation_enabled_workspace_doc(enabled=True)
    with (
        gateway_test_client(tmp_path, sevn_doc=doc) as client,
        patch(
            "sevn.voice.activation.probe_voice_activation",
            return_value={
                "available": False,
                "status": "unavailable",
                "reason": "no input device",
            },
            create=True,
        ),
        patch(
            "sevn.voice.activation.maybe_start_wake_word_listener",
            new_callable=AsyncMock,
            create=True,
        ) as start_hook,
    ):
        response = client.get("/health")
        assert response.status_code == 200
        start_hook.assert_not_called()


@pytest.mark.xfail(
    reason="green after W37: shutdown drains listener without error when unavailable", strict=False
)
def test_gateway_shutdown_drains_wake_word_listener_cleanly(tmp_path: Path) -> None:
    import_voice_activation_module()
    doc = activation_enabled_workspace_doc(enabled=True)
    stop_hook = AsyncMock()
    with (
        gateway_test_client(tmp_path, sevn_doc=doc) as client,
        patch(
            "sevn.voice.activation.probe_voice_activation",
            return_value={"available": False, "status": "unavailable", "reason": "no device"},
            create=True,
        ),
        patch(
            "sevn.voice.activation.maybe_stop_wake_word_listener",
            stop_hook,
            create=True,
        ),
    ):
        assert client.get("/health").status_code == 200
    stop_hook.assert_called_once()
