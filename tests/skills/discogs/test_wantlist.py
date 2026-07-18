"""discogs-wantlist skill script contracts (W1.8 / D16/D9)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.skills.discogs.conftest import run_skill_script

_SKILL_ID = "discogs-wantlist"
_WRITE_SCRIPTS = (
    ("add_want.py", ["--release-id", "1", "--notes", "must have"]),
    ("remove_want.py", ["--release-id", "1"]),
    ("edit_want.py", ["--release-id", "1", "--rating", "5"]),
)
_READ_SCRIPTS = ("get_wantlist.py", "search_wantlist.py")


def _mock_client_module(client: MagicMock) -> object:
    mod = MagicMock()
    mod.Client.return_value = client
    return mod


@pytest.mark.parametrize("script_name", _READ_SCRIPTS)
def test_read_script_returns_ok_envelope(script_name: str, tmp_path: Path) -> None:
    client = MagicMock()
    user = MagicMock()
    user.wantlist = MagicMock(pages=1, page=1, per_page=50, count=0)
    client.identity.return_value = user
    with patch.dict("sys.modules", {"discogs_client": _mock_client_module(client)}):
        code, payload = run_skill_script(
            _SKILL_ID,
            script_name,
            ["--artist", "kraftwerk"] if script_name == "search_wantlist.py" else [],
            workspace=tmp_path,
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
        _code, payload = run_skill_script(
            _SKILL_ID,
            script_name,
            argv,
            workspace=tmp_path,
            env={"DISCOGS_CONFIRM_WRITES": "true"},
        )
    assert payload["error"]["code"] == "CONFIRM_REQUIRED"
    client.assert_not_called()


@pytest.mark.parametrize(("script_name", "argv"), _WRITE_SCRIPTS)
def test_write_script_acts_with_confirm(
    script_name: str,
    argv: list[str],
    tmp_path: Path,
) -> None:
    client = MagicMock()
    client.identity.return_value = MagicMock(username="buyer")
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
