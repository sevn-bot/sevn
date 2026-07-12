"""Onboarding proxy handoff spawn (`specs/22-onboarding.md` §4.9)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from sevn.onboarding.live_validate import probe_llm_reachability
from sevn.onboarding.profiles import load_profile_fragment
from sevn.onboarding.proxy_spawn import spawn_proxy_background


def test_good_value_osx_profile_has_minimax_base_url() -> None:
    fragment = load_profile_fragment("good_value_osx")
    minimax = fragment.get("providers", {}).get("minimax", {})
    assert minimax.get("base_url") == "https://api.minimax.io/anthropic/v1"


def test_spawn_proxy_background_already_running(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    with patch(
        "sevn.onboarding.proxy_spawn.probe_proxy_listen_state",
        return_value="running",
    ):
        body = spawn_proxy_background(sevn_json_path=sevn_json)
    assert body["ok"] is True
    assert "already running" in body["message"]


def test_spawn_proxy_background_starts_process(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )

    class _Proc:
        pid = 4242

        def poll(self) -> None:
            return None

    captured: dict[str, object] = {}

    def _popen(*args: object, **kwargs: object) -> _Proc:
        captured["env"] = kwargs.get("env")
        return _Proc()

    with (
        patch("sevn.onboarding.proxy_spawn.probe_proxy_listen_state", return_value="absent"),
        patch("sevn.onboarding.proxy_spawn.subprocess.Popen", side_effect=_popen),
        patch("sevn.onboarding.proxy_spawn.proxy_healthz_get") as healthz,
        patch("sevn.onboarding.proxy_spawn.time.sleep"),
    ):
        healthz.return_value = httpx.Response(200)
        body = spawn_proxy_background(sevn_json_path=sevn_json)
    env = captured.get("env")
    assert isinstance(env, dict)
    assert env.get("SEVN_SERVICE_LOG") == "proxy"
    assert env.get("SEVN_HOME") == str(tmp_path.resolve())
    assert body["ok"] is True
    assert body["pid"] == 4242
    assert (tmp_path / "logs" / "proxy.log").name in body["log_path"]


@pytest.mark.anyio
async def test_probe_llm_proxy_503_errors_when_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "http://proxy.test/llm/openai/chat/completions")
    response = httpx.Response(503, request=request, json={"detail": "openai not configured"})

    async def _fail(self: object, req: dict[str, object]) -> dict[str, object]:
        _ = self, req
        raise httpx.HTTPStatusError("503", request=request, response=response)

    monkeypatch.setattr(
        "sevn.agent.providers.transport.ChatCompletionsTransport.complete",
        _fail,
    )
    check = await probe_llm_reachability(
        merged_preview={
            "llm": {"main_model": "openai/gpt-test"},
            "proxy": {"url": "http://proxy.test"},
        },
        cfg_proxy=None,
        fail_on_proxy_503=True,
    )
    assert check.ok is False
    assert check.severity == "error"
    assert "503" in check.detail
