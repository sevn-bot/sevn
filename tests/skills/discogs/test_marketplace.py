"""discogs-marketplace skill script contracts (W1.6 / D14/D9)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.skills.discogs.conftest import load_skill_script, run_skill_script

_SKILL_ID = "discogs-marketplace"
_WRITE_SCRIPTS = (
    ("create_listing.py", ["--release-id", "1", "--condition", "Mint", "--price", "10.00"]),
    ("edit_listing.py", ["--listing-id", "1", "--price", "12.00"]),
    ("delete_listing.py", ["--listing-id", "1"]),
    ("update_order.py", ["--order-id", "1", "--status", "Shipped"]),
    ("add_order_message.py", ["--order-id", "1", "--message", "Shipped today"]),
)
_READ_SCRIPTS = (
    "search_inventory.py",
    "get_listing.py",
    "get_order.py",
    "list_orders.py",
    "list_order_messages.py",
    "fee.py",
)


def _mock_client_module(client: MagicMock) -> object:
    mod = MagicMock()
    mod.Client.return_value = client
    return mod


@pytest.mark.parametrize("script_name", _READ_SCRIPTS)
def test_read_script_returns_ok_envelope(script_name: str, tmp_path: Path) -> None:
    client = MagicMock()
    client.identity.return_value = MagicMock(username="seller")
    client.identity.return_value.inventory = MagicMock(pages=1, page=1, per_page=50, count=0)
    client.listing.return_value = MagicMock(id=1)
    client.order.return_value = MagicMock(id=1)
    client.identity.return_value.orders = MagicMock(pages=1, page=1, per_page=50, count=0)
    client.fee_for.return_value = {"fee": {"value": 1.0, "currency": "USD"}}
    with patch.dict("sys.modules", {"discogs_client": _mock_client_module(client)}):
        code, payload = run_skill_script(
            _SKILL_ID,
            script_name,
            ["--id", "1"] if script_name != "fee.py" else ["--price", "10", "--currency", "USD"],
            workspace=tmp_path,
            env={"DISCOGS_AUTH_METHOD": "oauth", "DISCOGS_CONFIRM_WRITES": "true"},
        )
    assert code == 0
    assert payload["ok"] is True


@pytest.mark.parametrize(("script_name", "argv"), _WRITE_SCRIPTS)
def test_write_script_refuses_without_confirm(
    script_name: str,
    argv: list[str],
    tmp_path: Path,
) -> None:
    client = MagicMock()
    with patch.dict("sys.modules", {"discogs_client": _mock_client_module(client)}):
        code, payload = run_skill_script(
            _SKILL_ID,
            script_name,
            argv,
            workspace=tmp_path,
            env={"DISCOGS_CONFIRM_WRITES": "true"},
        )
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "CONFIRM_REQUIRED"
    assert "would_do" in payload["error"]
    client.assert_not_called()


@pytest.mark.parametrize(("script_name", "argv"), _WRITE_SCRIPTS)
def test_write_script_acts_with_confirm(
    script_name: str,
    argv: list[str],
    tmp_path: Path,
) -> None:
    client = MagicMock()
    client.identity.return_value = MagicMock(username="seller")
    with patch.dict("sys.modules", {"discogs_client": _mock_client_module(client)}):
        code, payload = run_skill_script(
            _SKILL_ID,
            script_name,
            [*argv, "--confirm"],
            workspace=tmp_path,
            env={"DISCOGS_CONFIRM_WRITES": "true"},
        )
    assert code == 0
    assert payload["ok"] is True


def test_search_inventory_paging(tmp_path: Path) -> None:
    client = MagicMock()
    inventory = MagicMock(pages=2, page=1, per_page=50, count=75)
    user = MagicMock(inventory=inventory)
    client.identity.return_value = user
    mod = load_skill_script(_SKILL_ID, "search_inventory.py")
    with patch.dict("sys.modules", {"discogs_client": _mock_client_module(client)}):
        code, payload = mod.main(["--page", "1", "--per-page", "50"])
    assert code == 0
    assert payload["paging"]["count"] == 75
