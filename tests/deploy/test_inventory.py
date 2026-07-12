"""Deploy inventory loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.deploy.inventory import DeployInventoryError, get_host, load_inventory

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "deploy"


def test_load_inventory_parses_host() -> None:
    inv = load_inventory(_FIXTURES / "inventory.toml")
    host = get_host(inv, "staging")
    assert host.host == "203.0.113.10"
    assert host.gateway_port == 3001


def test_load_inventory_missing_file() -> None:
    with pytest.raises(DeployInventoryError, match="not found"):
        load_inventory(Path("/nonexistent/inventory.toml"))


def test_get_host_unknown() -> None:
    inv = load_inventory(_FIXTURES / "inventory.toml")
    with pytest.raises(DeployInventoryError, match="unknown deploy host"):
        get_host(inv, "missing")
