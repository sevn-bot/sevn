"""W23.1 — ingress body caps (#81 → W24).

Every gateway/proxy ingress path must reject oversized bodies before JSON parsing.
Today ``await request.json()`` / ``request.body()`` are unbounded.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from sevn.config.workspace_config import TriggersWorkspaceConfig

from sevn.proxy.app import create_app as create_proxy_app
from sevn.proxy.settings import ProxySettings
from tests.open_issues_sweep.batch_e.conftest import (
    EXPECTED_MAX_INGRESS_BODY_BYTES,
    OVERSIZED_BODY_BYTES,
    IngressPostTarget,
    gateway_test_client,
    ingress_post_targets,
    oversized_json_body,
)

_INGRESS_CAP_STATUS = 413


@pytest.mark.parametrize("target", ingress_post_targets(), ids=lambda t: t.route_id)
@pytest.mark.xfail(reason="green after W24: centralized ingress body cap", strict=False)
def test_oversized_post_body_rejected_before_handler(
    tmp_path: Path,
    target: IngressPostTarget,
    github_triggers_config: TriggersWorkspaceConfig,
) -> None:
    """Oversized POST bodies return 413 without reaching route handlers."""
    body = (
        oversized_json_body() if target.content_type == "application/json" else OVERSIZED_BODY_BYTES
    )
    with gateway_test_client(
        tmp_path, triggers=github_triggers_config, dashboard_enabled=True
    ) as client:
        response = client.post(target.path, content=body, headers=dict(target.headers))
    assert response.status_code == _INGRESS_CAP_STATUS, (
        f"{target.path} accepted {len(body)} bytes — cap should be {EXPECTED_MAX_INGRESS_BODY_BYTES}"
    )


@pytest.mark.xfail(reason="green after W24: webchat WS frame body cap", strict=False)
def test_oversized_webchat_ws_first_frame_rejected(tmp_path: Path) -> None:
    """Webchat auth frame larger than cap closes before session registration."""
    with gateway_test_client(tmp_path) as client, client.websocket_connect("/ws/webchat") as ws:
        ws.send_bytes(OVERSIZED_BODY_BYTES)
        frame = ws.receive()
    assert frame.get("type") == "websocket.close"
    assert frame.get("code") == 1009


@pytest.mark.anyio
@pytest.mark.xfail(reason="green after W24: egress proxy ingress body cap", strict=False)
async def test_oversized_proxy_llm_post_rejected() -> None:
    """Egress proxy ``POST /llm/*`` rejects oversized bodies before upstream forward."""
    app = create_proxy_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=None,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    body = oversized_json_body()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/llm/openai/chat/completions", content=body)
    assert response.status_code == _INGRESS_CAP_STATUS
