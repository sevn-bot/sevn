"""Tests for ``sevn agent``, ``sevn models``, and ``sevn voice`` (W9)."""

from __future__ import annotations

import json
import sqlite3

import httpx
import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

import sevn.cli.dashboard_api_client as dashboard_api_client_mod
from sevn.cli.app import app
from sevn.cli.commands.voice_cmd import _voice_settings_snapshot
from sevn.cli.help.panels import panel_for
from sevn.config.llm_params import LLM_PARAMS_FILENAME
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_help_panels_agent_models_voice() -> None:
    assert panel_for("agent") == "Core"
    assert panel_for("models") == "Agent"
    assert panel_for("voice") == "Agent"


def test_voice_settings_snapshot_defaults() -> None:
    snap = _voice_settings_snapshot(WorkspaceConfig.minimal())
    assert snap["stt_providers"]
    assert snap["tts_providers"]


def test_sevn_agent_help_lists_subcommands(runner: CliRunner) -> None:
    result = runner.invoke(app, ["agent"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "status" in result.stdout
    assert "config" in result.stdout


def test_sevn_models_and_voice_help(runner: CliRunner) -> None:
    models = runner.invoke(app, ["models", "--help"], env={"NO_COLOR": "1"})
    assert models.exit_code == 0
    assert "params" in models.stdout
    assert "set-max-output-tokens" in models.stdout
    voice = runner.invoke(app, ["voice", "--help"], env={"NO_COLOR": "1"})
    assert voice.exit_code == 0
    assert "status" in voice.stdout


def _patch_dashboard_via_gateway(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> TestClient:
    home = tmp_path_factory.mktemp("home")
    ws = home / "workspace"
    ws.mkdir()
    sevn_doc = {
        "schema_version": 2,
        "providers": {
            "use_main_model_for_all": True,
            "tier_default": {"triager": "minimax/MiniMax-M2.7"},
        },
        "voice": {
            "tts_mode": "when_asked",
            "stt_providers": ["whisper_cpp"],
            "voice_trigger_keywords": ["voice"],
        },
        "gateway": {"token": "gw-token"},
    }
    (ws / "sevn.json").write_text(json.dumps(sevn_doc), encoding="utf-8")
    cfg = parse_workspace_config(sevn_doc)
    layout = WorkspaceLayout.from_config(ws / "sevn.json", cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_migrations(conn)
        return conn

    gw_app = create_app(
        workspace=cfg,
        layout=layout,
        sqlite_connection_factory=factory,
        process_settings=ProcessSettings(gateway_token="gw-token"),
    )
    client_cm = TestClient(gw_app, raise_server_exceptions=True)
    tc = client_cm.__enter__()
    tc.get("/health")
    request.addfinalizer(lambda: client_cm.__exit__(None, None, None))

    def _via_test_client(
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        _ = kwargs, json_body
        if method.upper() != "GET":
            msg = f"unsupported method {method}"
            raise ValueError(msg)
        starlette_resp = tc.get(path)
        return httpx.Response(
            status_code=starlette_resp.status_code,
            json=starlette_resp.json() if starlette_resp.content else None,
            request=httpx.Request("GET", path),
        )

    monkeypatch.setattr(dashboard_api_client_mod, "gateway_json_request", _via_test_client)
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", "gw-token")
    return tc


def test_sevn_agent_config_json(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> None:
    _patch_dashboard_via_gateway(monkeypatch, tmp_path_factory, request)
    result = runner.invoke(app, ["agent", "config", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert "main_model" in payload["data"]
    assert payload["command"] == "sevn agent config"


def test_sevn_models_show_plain(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> None:
    _patch_dashboard_via_gateway(monkeypatch, tmp_path_factory, request)
    result = runner.invoke(app, ["models", "show"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "main_model:" in result.stdout


def test_sevn_models_params_json(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> None:
    _patch_dashboard_via_gateway(monkeypatch, tmp_path_factory, request)
    result = runner.invoke(app, ["models", "params", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert "doc" in payload["data"]


def test_sevn_voice_show_local_config(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> None:
    _patch_dashboard_via_gateway(monkeypatch, tmp_path_factory, request)
    result = runner.invoke(app, ["voice", "show", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["tts_mode"] == "when_asked"
    assert payload["data"]["stt_providers"] == ["whisper_cpp"]


def test_sevn_voice_status_filters_voice_providers(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> None:
    _patch_dashboard_via_gateway(monkeypatch, tmp_path_factory, request)
    result = runner.invoke(app, ["voice", "status", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    providers = payload["data"]["providers"]
    assert isinstance(providers, list)
    assert all(str(row.get("id", "")).startswith("voice_") for row in providers)


def test_sevn_models_set_max_output_tokens(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    home = tmp_path_factory.mktemp("home")
    ws = home / "workspace"
    ws.mkdir()
    sevn_doc = {
        "schema_version": 2,
        "gateway": {"token": "gw-token"},
    }
    (ws / "sevn.json").write_text(json.dumps(sevn_doc), encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(
        app,
        ["models", "set-max-output-tokens", "tier_b", "6000", "--model", "minimax/*", "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["max_output_tokens"] == 6000
    params_path = ws / LLM_PARAMS_FILENAME
    assert params_path.is_file()
    doc = json.loads(params_path.read_text(encoding="utf-8"))
    assert doc["tier_b"]["model_overrides"]["minimax/*"]["max_output_tokens"] == 6000


def test_dashboard_api_get_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hello": "world"}, request=request)

    body = dashboard_api_client_mod.dashboard_api_get(
        "/api/v1/agent/config",
        command="t",
        workspace=WorkspaceConfig.minimal(),
        transport=httpx.MockTransport(handler),
    )
    assert body["hello"] == "world"
