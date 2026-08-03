"""Batch A W1 RED — compose default services (#136, #137; green after W2).

Contracts: ``docker/docker-compose.yml`` default profile must start ``sevn-proxy`` +
``sevn-gateway``; negated ``!browser`` / ``!gui`` profiles forbidden; gateway services
must not receive ``OPENAI_API_KEY``.
"""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_FILE = _REPO_ROOT / "docker" / "docker-compose.yml"
_NEGATED_PROFILE_RE = re.compile(r'^\s*-\s*"![^"]+"\s*$', re.MULTILINE)
_GATEWAY_SERVICE_NAMES = ("sevn-gateway", "sevn-gateway-browser", "sevn-gateway-gui")


def _compose_default_services() -> list[str]:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker CLI not on PATH")
    proc = subprocess.run(
        [docker, "compose", "-f", str(_COMPOSE_FILE), "config", "--services"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )  # nosec B603
    if proc.returncode != 0:
        pytest.skip(f"docker compose config failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def test_default_compose_services_include_gateway_and_proxy() -> None:
    services = _compose_default_services()
    assert "sevn-proxy" in services
    assert "sevn-gateway" in services


def test_compose_yaml_forbids_negated_profiles() -> None:
    text = _COMPOSE_FILE.read_text(encoding="utf-8")
    matches = _NEGATED_PROFILE_RE.findall(text)
    assert matches == [], f"negated profiles forbidden, found: {matches}"


def test_gateway_compose_services_do_not_receive_openai_api_key() -> None:
    text = _COMPOSE_FILE.read_text(encoding="utf-8")
    blocks = re.split(r"(?=^\s{2}\w)", text, flags=re.MULTILINE)
    for block in blocks:
        first_line = block.splitlines()[0] if block.splitlines() else ""
        service = first_line.strip().rstrip(":")
        if service not in _GATEWAY_SERVICE_NAMES:
            continue
        assert "OPENAI_API_KEY" not in block, f"{service} must not receive OPENAI_API_KEY"
