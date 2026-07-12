"""Gateway process settings merge at boot."""

from __future__ import annotations

from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.http_server import _effective_process_settings


def test_effective_process_settings_fills_proxy_from_workspace() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    process = ProcessSettings()
    effective = _effective_process_settings(ws, process)
    assert effective.proxy_url == "http://127.0.0.1:8787"
