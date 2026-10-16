"""Image, fly skeleton, and CI workflow (D19, D20). Green after W7."""

from __future__ import annotations

import re
import tomllib

import pytest
from support.repo import repo_root

pytestmark = pytest.mark.xfail(strict=False, reason="green after W7")


def test_dockerfile_user_and_healthcheck() -> None:
    text = (repo_root() / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    users = re.findall(r"(?m)^USER\s+(\S+)", text)
    assert users
    assert users[-1] not in {"root", "0", "0:0"}
    health = re.search(r"(?ms)^HEALTHCHECK\b.*?(?=^(?:[A-Z]+)\b|\Z)", text)
    assert health is not None
    block = health.group(0).replace("\\\n", " ")
    assert "curl" in block
    assert "/health" in block
    assert re.search(r"(?m)^ENV\s+SEVN_HOME=/data\b", text)
    assert re.search(r"(?m)^VOLUME\s+/data\b", text)
    assert "--allow-remote-bind" in text


def test_fly_toml_has_volume_and_health() -> None:
    data = tomllib.loads((repo_root() / "deploy" / "fly.toml").read_text(encoding="utf-8"))
    mounts = data["mounts"]
    if isinstance(mounts, dict):
        assert mounts["destination"] == "/data"
    else:
        assert any(item["destination"] == "/data" for item in mounts)
    checks = data["http_service"]["checks"]
    assert any(item.get("path") == "/health" for item in checks)


def test_ci_workflow_runs_make_ci_without_secrets() -> None:
    text = (repo_root() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ubuntu-latest" in text
    assert "make ci" in text
    assert "pull_request" in text
    assert re.search(r"branches:[^\n]*main|-\s+[\"']?main[\"']?", text)
    assert "permissions:" in text
    assert re.search(r"contents:\s*read", text)
    assert "${{ secrets" not in text
