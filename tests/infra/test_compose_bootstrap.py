"""Post-audit Batch A — compose bootstrap regression (#177).

Contracts (W3.7, ``about-sevn.bot/specs/25-cicd-full.md``): gateway entrypoint
materializes ``<SEVN_HOME>/workspace/sevn.json`` from mounted onboard JSON before
exec'ing uvicorn when workspace config is absent. Parses bootstrap Python + shell
artefacts directly — no Docker daemon.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKER_DIR = _REPO_ROOT / "docker"
_INFRA_DOCKER = _REPO_ROOT / "infra" / "docker"
_BOOTSTRAP_SCRIPT = _INFRA_DOCKER / "compose-bootstrap.py"
_GATEWAY_ENTRYPOINT = _INFRA_DOCKER / "gateway-entrypoint.sh"
_GUI_ENTRYPOINT = _INFRA_DOCKER / "gui" / "entrypoint.sh"
_ONBOARD_JSON = _REPO_ROOT / "infra" / "docker-onboard.json"
_BASE_COMPOSE = _DOCKER_DIR / "docker-compose.yml"
_SEVN_JSON_REL = "workspace/sevn.json"


def _load_compose_bootstrap_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "compose_bootstrap_under_test",
        _BOOTSTRAP_SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _bootstrap_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    telegram_token: str | None = None,
) -> dict[str, Path]:
    sevn_home = tmp_path / "operator"
    workspace = sevn_home / "workspace"
    workspace.mkdir(parents=True)
    bootstrap_config = tmp_path / "bootstrap" / "onboard-compose.json"
    bootstrap_config.parent.mkdir(parents=True)
    bootstrap_config.write_text(_ONBOARD_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(sevn_home))
    monkeypatch.setenv("SEVN_COMPOSE_BOOTSTRAP_CONFIG", str(bootstrap_config))
    monkeypatch.setenv("SEVN_COMPOSE_BOOTSTRAP_PROFILE", "good_value_docker")
    monkeypatch.setenv("SEVN_BOOTSTRAP_BOT_NAME", "TestSevn")
    if telegram_token is None:
        monkeypatch.delenv("SEVN_TELEGRAM_BOT_TOKEN", raising=False)
    else:
        monkeypatch.setenv("SEVN_TELEGRAM_BOT_TOKEN", telegram_token)
    return {
        "sevn_home": sevn_home,
        "workspace": workspace,
        "sevn_json": workspace / "sevn.json",
        "bootstrap_config": bootstrap_config,
    }


def test_bootstrap_compose_workspace_materializes_sevn_json_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#177: clean volume → promoted workspace config at bound path."""
    env = _bootstrap_env(tmp_path, monkeypatch)
    mod = _load_compose_bootstrap_module()

    assert not env["sevn_json"].is_file()
    result = mod.bootstrap_compose_workspace()

    assert result == env["sevn_json"]
    assert env["sevn_json"].is_file()
    doc = json.loads(env["sevn_json"].read_text(encoding="utf-8"))
    assert doc["gateway"]["token"] == "${ENV:SEVN_GATEWAY_TOKEN}"
    assert doc["channels"]["telegram"]["enabled"] is False
    assert doc["agent"]["display_name"] == "TestSevn"


def test_bootstrap_compose_workspace_skips_when_sevn_json_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#177: idempotent entrypoint guard — never overwrite an existing workspace."""
    env = _bootstrap_env(tmp_path, monkeypatch)
    mod = _load_compose_bootstrap_module()
    sentinel = {"marker": "keep-me"}
    env["sevn_json"].write_text(json.dumps(sentinel), encoding="utf-8")

    result = mod.bootstrap_compose_workspace()

    assert result == env["sevn_json"]
    assert json.loads(env["sevn_json"].read_text(encoding="utf-8")) == sentinel


def test_bootstrap_compose_workspace_rejects_non_object_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error handling: bootstrap config must be a JSON object."""
    env = _bootstrap_env(tmp_path, monkeypatch)
    env["bootstrap_config"].write_text("[]", encoding="utf-8")
    mod = _load_compose_bootstrap_module()

    with pytest.raises(ValueError, match="bootstrap config must be a JSON object"):
        mod.bootstrap_compose_workspace()


@pytest.mark.parametrize(
    ("token_ref", "expected"),
    [
        pytest.param(
            "${SECRET:keychain:sevn.gateway.token}", "${ENV:SEVN_GATEWAY_TOKEN}", id="keychain"
        ),
        pytest.param("${ENV:SEVN_GATEWAY_TOKEN}", "${ENV:SEVN_GATEWAY_TOKEN}", id="already-env"),
    ],
)
def test_dockerize_config_doc_rewrites_gateway_token(
    token_ref: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_compose_bootstrap_module()
    doc: dict[str, Any] = {"gateway": {"token": token_ref}}
    monkeypatch.delenv("SEVN_TELEGRAM_BOT_TOKEN", raising=False)

    mod._dockerize_config_doc(doc)

    assert doc["gateway"]["token"] == expected


def test_dockerize_config_doc_disables_telegram_without_bot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_compose_bootstrap_module()
    doc: dict[str, Any] = {
        "channels": {
            "telegram": {"enabled": True, "bot_token_ref": "${ENV:SEVN_TELEGRAM_BOT_TOKEN}"}
        },
    }
    monkeypatch.delenv("SEVN_TELEGRAM_BOT_TOKEN", raising=False)

    mod._dockerize_config_doc(doc)

    assert doc["channels"]["telegram"]["enabled"] is False


def test_dockerize_config_doc_keeps_telegram_when_bot_token_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_compose_bootstrap_module()
    doc: dict[str, Any] = {
        "channels": {
            "telegram": {"enabled": True, "bot_token_ref": "${ENV:SEVN_TELEGRAM_BOT_TOKEN}"}
        },
    }
    monkeypatch.setenv("SEVN_TELEGRAM_BOT_TOKEN", "123456:ABC")

    mod._dockerize_config_doc(doc)

    assert doc["channels"]["telegram"]["enabled"] is True


def test_compose_bootstrap_cli_writes_ready_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI entrypoint used by gateway-entrypoint.sh."""
    env = _bootstrap_env(tmp_path, monkeypatch)
    proc = subprocess.run(
        [sys.executable, str(_BOOTSTRAP_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )  # nosec B603
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "compose bootstrap: workspace ready at" in proc.stdout
    assert env["sevn_json"].is_file()


def test_compose_bootstrap_cli_fails_on_invalid_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _bootstrap_env(tmp_path, monkeypatch)
    env["bootstrap_config"].write_text("[]", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_BOOTSTRAP_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )  # nosec B603
    assert proc.returncode == 1
    assert "compose bootstrap failed:" in proc.stderr


def test_gateway_entrypoint_runs_bootstrap_before_exec() -> None:
    """Static guard: bootstrap must run only when workspace sevn.json is absent."""
    text = _GATEWAY_ENTRYPOINT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert 'if [[ ! -f "${SEVN_JSON}" ]]' in text
    assert "compose-bootstrap.py" in text
    assert 'exec "$@"' in text
    bootstrap_pos = text.index("compose-bootstrap.py")
    exec_pos = text.index('exec "$@"')
    assert bootstrap_pos < exec_pos, "bootstrap must precede exec of CMD (uvicorn)"


def test_gateway_entrypoint_targets_workspace_sevn_json() -> None:
    text = _GATEWAY_ENTRYPOINT.read_text(encoding="utf-8")
    assert "SEVN_JSON=" in text
    assert _SEVN_JSON_REL in text


def test_gui_entrypoint_runs_bootstrap_before_supervisord() -> None:
    text = _GUI_ENTRYPOINT.read_text(encoding="utf-8")
    assert 'if [[ ! -f "${WORKSPACE}/sevn.json" ]]' in text
    assert "compose-bootstrap.py" in text
    assert "exec supervisord" in text


@pytest.mark.parametrize(
    "dockerfile",
    [
        pytest.param("Dockerfile.gateway", id="gateway"),
        pytest.param("Dockerfile.gateway.browser", id="gateway-browser"),
    ],
)
def test_gateway_dockerfiles_wire_entrypoint_before_uvicorn(dockerfile: str) -> None:
    text = (_DOCKER_DIR / dockerfile).read_text(encoding="utf-8")
    assert "gateway-entrypoint.sh" in text
    assert "compose-bootstrap.py" in text
    assert 'CMD ["uvicorn"' in text
    entry_pos = text.index("gateway-entrypoint.sh")
    cmd_pos = text.index('CMD ["uvicorn"')
    assert entry_pos < cmd_pos


def test_gateway_compose_mounts_onboard_bootstrap_json() -> None:
    data = yaml.safe_load(_BASE_COMPOSE.read_text(encoding="utf-8")) or {}
    gateway = (data.get("services") or {}).get("sevn-gateway") or {}
    volumes = gateway.get("volumes") or []
    joined = "\n".join(str(v) for v in volumes)
    assert "docker-onboard.json:/bootstrap/onboard-compose.json" in joined


def test_entrypoint_guard_materializes_config_before_command_exec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavioral mirror of gateway-entrypoint.sh: bootstrap then hand off to CMD."""
    env = _bootstrap_env(tmp_path, monkeypatch)
    mod = _load_compose_bootstrap_module()
    sevn_json = env["sevn_json"]
    cmd_ran = False

    if not sevn_json.is_file():
        mod.bootstrap_compose_workspace()

    assert sevn_json.is_file(), "uvicorn CMD must not run without workspace config"
    cmd_ran = True
    assert cmd_ran


@pytest.mark.xfail(
    reason="green after F2: GUI sevnoperator UID must not collide with gateway 10001",
    strict=False,
)
def test_gui_dockerfile_sevnoperator_uid_distinct_from_gateway() -> None:
    """F2 regression: GUI operator UID must not collide with gateway UID 10001."""
    text = (_DOCKER_DIR / "Dockerfile.gateway.gui").read_text(encoding="utf-8")
    assert "useradd --create-home --uid 10002" in text
    assert "sevnoperator" in text
    gateway_text = (_DOCKER_DIR / "Dockerfile.gateway").read_text(encoding="utf-8")
    assert "useradd --create-home --uid 10001" in gateway_text
