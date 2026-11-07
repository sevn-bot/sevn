"""``deploy/compose.yaml`` and the Tailscale sidecar files (plan 0025 D10, W5).

The files are parsed, never run; ``docker compose`` is a live gate (WV).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from support.repo import repo_root

_COMPOSE = repo_root() / "deploy" / "compose.yaml"
_SERVE = repo_root() / "deploy" / "tailscale" / "serve.json"
_UPSTREAM = "http://127.0.0.1:8787"


def _compose() -> dict[str, Any]:
    yaml = pytest.importorskip("yaml")
    loaded = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _env(service: dict[str, Any]) -> dict[str, str]:
    raw = service.get("environment", {})
    if isinstance(raw, list):
        pairs = [str(item).split("=", 1) for item in raw]
        return {pair[0]: pair[1] if len(pair) > 1 else "" for pair in pairs}
    return {str(key): "" if value is None else str(value) for key, value in raw.items()}


def _volume_specs(service: dict[str, Any]) -> list[str]:
    specs: list[str] = []
    for item in service.get("volumes", []):
        if isinstance(item, dict):
            specs.append(f"{item.get('source')}:{item.get('target')}")
        else:
            specs.append(":".join(str(item).split(":")[:2]))
    return specs


def _sevn() -> dict[str, Any]:
    return _compose()["services"]["sevn"]


def test_sevn_service_builds_the_debian_image() -> None:
    build = _sevn()["build"]
    if isinstance(build, str):
        pytest.fail("build must name deploy/Dockerfile explicitly")
    context = (_COMPOSE.parent / str(build.get("context", "."))).resolve()
    dockerfile = (context / str(build["dockerfile"])).resolve()
    assert dockerfile == (repo_root() / "deploy" / "Dockerfile").resolve()


def test_sevn_service_restarts_unless_stopped() -> None:
    assert _sevn()["restart"] == "unless-stopped"


def test_sevn_service_mounts_data_and_home_volumes() -> None:
    compose = _compose()
    specs = _volume_specs(compose["services"]["sevn"])
    assert "sevn-data:/data" in specs
    assert "sevn-home:/home/sevn" in specs
    assert {"sevn-data", "sevn-home"} <= set(compose.get("volumes", {}))


def test_sevn_service_publishes_loopback_only() -> None:
    ports = [str(item) for item in _sevn().get("ports", [])]
    assert ports == ["127.0.0.1:8787:8787"]


def test_allowed_hosts_come_from_the_env_file() -> None:
    value = _env(_sevn()).get("SEVN_ALLOWED_HOSTS")
    assert value is not None
    assert re.fullmatch(r"\$\{SEVN_ALLOWED_HOSTS[^}]*\}", value), value
    # The image binds all interfaces; the merged host guard requires explicit names.
    assert value == "${SEVN_ALLOWED_HOSTS:-127.0.0.1:8787,localhost:8787}"


def _tailscale() -> dict[str, Any]:
    return _compose()["services"]["tailscale"]


def test_tailscale_sidecar_is_behind_a_profile() -> None:
    sidecar = _tailscale()
    assert str(sidecar["image"]).startswith("tailscale/tailscale")
    assert sidecar.get("profiles") == ["tailscale"]
    assert "tailscale" not in _sevn().get("profiles", [])


def test_tailscale_auth_key_is_a_compose_secret() -> None:
    compose = _compose()
    sidecar = compose["services"]["tailscale"]
    secrets = sidecar.get("secrets", [])
    names = [item if isinstance(item, str) else item.get("source") for item in secrets]
    assert names, "the sidecar declares no secrets"
    assert set(names) <= set(compose.get("secrets", {}))
    auth = _env(sidecar).get("TS_AUTHKEY", "")
    assert "/run/secrets/" in auth, auth
    assert "tskey-" not in _COMPOSE.read_text(encoding="utf-8")


def test_tailscale_serves_the_mounted_config_and_keeps_state() -> None:
    sidecar = _tailscale()
    env = _env(sidecar)
    assert env.get("TS_SERVE_CONFIG") == "/config/serve.json"
    specs = _volume_specs(sidecar)
    mounted = [spec for spec in specs if spec.endswith(":/config")]
    assert len(mounted) == 1, specs
    source = (_COMPOSE.parent / mounted[0].split(":")[0]).resolve()
    assert source == _SERVE.parent.resolve()
    state_dir = env.get("TS_STATE_DIR")
    assert state_dir, "TS_STATE_DIR keeps the node identity across restarts"
    named = set(_compose().get("volumes", {}))
    assert any(spec.endswith(f":{state_dir}") and spec.split(":")[0] in named for spec in specs)


def test_sevn_joins_the_tailscale_network_in_the_profile() -> None:
    services = _compose()["services"]
    joined = [
        (name, service)
        for name, service in services.items()
        if service.get("network_mode") == "service:tailscale"
    ]
    assert len(joined) == 1, list(services)
    name, service = joined[0]
    assert name != "tailscale"
    assert "tailscale" in service.get("profiles", [])
    assert "ports" not in service
    specs = _volume_specs(service)
    assert "sevn-data:/data" in specs
    assert "sevn-home:/home/sevn" in specs


def _proxies(node: object) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "Proxy" and isinstance(value, str):
                found.append(value)
            found.extend(_proxies(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_proxies(item))
    return found


def test_serve_json_proxies_https_to_the_loopback_host() -> None:
    config = json.loads(_SERVE.read_text(encoding="utf-8"))
    assert config["TCP"]["443"]["HTTPS"] is True
    proxies = _proxies(config.get("Web", {}))
    assert proxies == [_UPSTREAM]


def test_compose_files_hold_no_secrets() -> None:
    for path in (_COMPOSE, _SERVE):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"tskey-[A-Za-z0-9]", text), path
        assert Path(path).is_file()
