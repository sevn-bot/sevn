"""discogs-identity skill script contracts (W1.9 / D17)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.skills.discogs.conftest import load_skill_script, run_skill_script

_SKILL_ID = "discogs-identity"
_READ_SCRIPTS = (
    "get_user.py",
    "list_user_lists.py",
    "get_list.py",
    "search_lists.py",
    "contributions.py",
)


def _mock_client_module(client: MagicMock) -> object:
    mod = MagicMock()
    mod.Client.return_value = client
    return mod


def test_whoami_returns_authed_username(tmp_path: Path) -> None:
    client = MagicMock()
    client.identity.return_value = MagicMock(username="discogs-operator")
    with patch.dict("sys.modules", {"discogs_client": _mock_client_module(client)}):
        code, payload = run_skill_script(_SKILL_ID, "whoami.py", [], workspace=tmp_path)
    assert code == 0
    assert payload["ok"] is True
    assert payload["data"]["username"] == "discogs-operator"


def test_whoami_maps_auth_error() -> None:
    client = MagicMock()
    client.identity.side_effect = Exception("401 Unauthorized")
    mod = load_skill_script(_SKILL_ID, "whoami.py")
    with patch.dict("sys.modules", {"discogs_client": _mock_client_module(client)}):
        code, payload = mod.main([])
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] in {"AUTH_REQUIRED", "DISCOGS_HTTP"}


@pytest.mark.parametrize("script_name", _READ_SCRIPTS)
def test_read_script_returns_ok_envelope(script_name: str, tmp_path: Path) -> None:
    client = MagicMock()
    user = MagicMock(username="someone")
    user.lists = MagicMock(pages=1, page=1, per_page=50, count=0)
    user.releases_contributed = MagicMock(pages=1, page=1, per_page=50, count=0)
    client.user.return_value = user
    client.list.return_value = MagicMock(
        id=1, items=MagicMock(pages=1, page=1, per_page=50, count=0)
    )
    with patch.dict("sys.modules", {"discogs_client": _mock_client_module(client)}):
        code, payload = run_skill_script(
            _SKILL_ID,
            script_name,
            ["--username", "someone"] if script_name != "get_list.py" else ["--list-id", "1"],
            workspace=tmp_path,
        )
    assert code == 0
    assert payload["ok"] is True
