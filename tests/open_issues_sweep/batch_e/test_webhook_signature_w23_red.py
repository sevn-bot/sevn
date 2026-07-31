"""W23.2 — signed webhook timestamp skew + replay (#81 → W24).

``verify_github_payload`` checks HMAC only — no skew check. Delivery-id dedupe is the
second replay layer (``try_insert_webhook_dedupe``).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from sevn.triggers.sources.github import verify_github_payload
from tests.open_issues_sweep.batch_e.conftest import (
    gateway_test_client,
    github_signature,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import TriggersWorkspaceConfig

_SECRET = b"batch-e-gh-secret"


def test_invalid_github_hmac_rejected_today() -> None:
    """Invalid HMAC is rejected (baseline — not an xfail regression guard)."""
    body = json.dumps({"zen": "pong"}).encode("utf-8")
    ok = verify_github_payload(
        {"x-hub-signature-256": "sha256=deadbeef"},
        body,
        secret=_SECRET,
    )
    assert ok is False


def test_stale_github_webhook_timestamp_rejected() -> None:
    """Signed webhooks older than allowed skew are rejected before enqueue."""
    from sevn.triggers.sources.github import verify_github_webhook_freshness

    body = json.dumps({"action": "ping"}).encode("utf-8")
    headers = {
        "x-hub-signature-256": github_signature(body, secret=_SECRET),
        "x-github-delivery": "stale-delivery-1",
        "x-hub-signature-timestamp": str(int(time.time()) - 3600),
    }
    assert verify_github_webhook_freshness(headers, max_skew_seconds=300) is False


def test_stale_github_webhook_http_401(
    tmp_path: Path,
    github_triggers_config: TriggersWorkspaceConfig,
) -> None:
    """HTTP ingress rejects stale signed GitHub deliveries with 401."""
    body = json.dumps({"action": "ping"}).encode("utf-8")
    headers = {
        "X-Hub-Signature-256": github_signature(body, secret=_SECRET),
        "X-GitHub-Delivery": "stale-http-1",
        "X-Hub-Signature-Timestamp": str(int(time.time()) - 7200),
        "Content-Type": "application/json",
    }
    with gateway_test_client(tmp_path, triggers=github_triggers_config) as client:
        response = client.post("/webhook/github", content=body, headers=headers)
    assert response.status_code == 401


def test_duplicate_github_delivery_deduped_without_double_spawn(
    tmp_path: Path,
    github_triggers_config: TriggersWorkspaceConfig,
) -> None:
    """Delivery-id dedupe remains the second replay layer (passes today)."""
    body = json.dumps({"action": "opened"}).encode("utf-8")
    headers = {
        "X-Hub-Signature-256": github_signature(body, secret=_SECRET),
        "X-GitHub-Delivery": "dup-batch-e-1",
        "Content-Type": "application/json",
    }
    with (
        gateway_test_client(tmp_path, triggers=github_triggers_config) as client,
        patch("sevn.triggers.webhook_router.spawn_logged") as mock_spawn,
    ):
        mock_spawn.return_value = MagicMock()
        first = client.post("/webhook/github", content=body, headers=headers)
        second = client.post("/webhook/github", content=body, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json().get("dedupe") == "duplicate"
    assert mock_spawn.call_count == 1
