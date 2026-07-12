"""Webhook dispatch schedules background work via :func:`spawn_logged`."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.triggers.test_webhook_github import _SECRET, _github_signature, _make_client

from sevn.config.workspace_config import TriggersWorkspaceConfig


def test_signed_webhook_dispatch_uses_spawn_logged(tmp_path: Path) -> None:
    triggers = TriggersWorkspaceConfig(
        webhooks={
            "github": {"secret_b64": base64.b64encode(_SECRET).decode("ascii")},
        },
        sources={
            "github": {
                "delivery_mode": "notify_only",
                "payload_template": "{{ prompt }}",
            }
        },
    )
    body = json.dumps({"action": "opened", "issue": {"title": "t"}}).encode()
    with _make_client(tmp_path, triggers=triggers) as client:
        client.get("/health")
        with patch("sevn.triggers.webhook_router.spawn_logged") as mock_spawn:
            mock_spawn.return_value = MagicMock()
            resp = client.post(
                "/webhook/github",
                content=body,
                headers={
                    "X-Hub-Signature-256": _github_signature(body),
                    "X-GitHub-Delivery": "delivery-1",
                    "X-GitHub-Event": "issues",
                    "Content-Type": "application/json",
                },
            )
    assert resp.status_code == 202
    mock_spawn.assert_called_once()
    assert mock_spawn.call_args.kwargs["label"] == "webhook_dispatch"
