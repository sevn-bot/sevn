"""W35.4 — gateway boots without a microphone (#102 → W36/W37, D25)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests.open_issues_sweep.batch_g.conftest import (
    activation_enabled_workspace_doc,
    gateway_test_client,
    import_voice_activation_module,
)


def test_gateway_lifespan_completes_with_activation_enabled_no_device(tmp_path: Path) -> None:
    import_voice_activation_module()
    doc = activation_enabled_workspace_doc(enabled=True)
    with (
        patch(
            "sevn.voice.activation.probe_voice_activation",
            return_value={
                "available": False,
                "status": "unavailable",
                "reason": "no input device",
            },
        ),
        gateway_test_client(tmp_path, sevn_doc=doc) as client,
    ):
        response = client.get("/health")
        assert response.status_code == 200
        activation = client.app.state.voice_activation
        assert activation.get("listening") is False
        assert activation.get("task") is None


def test_gateway_shutdown_drains_wake_word_listener_cleanly(tmp_path: Path) -> None:
    import_voice_activation_module()
    doc = activation_enabled_workspace_doc(enabled=True)
    stop_hook = AsyncMock()
    with (
        patch(
            "sevn.voice.activation.probe_voice_activation",
            return_value={"available": False, "status": "unavailable", "reason": "no device"},
        ),
        patch(
            "sevn.voice.activation.maybe_stop_wake_word_listener",
            stop_hook,
        ),
    ):
        with gateway_test_client(tmp_path, sevn_doc=doc) as client:
            assert client.get("/health").status_code == 200
        stop_hook.assert_called_once()
