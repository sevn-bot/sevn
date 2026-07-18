"""discogs-collection skill script contracts (W1.7 / D15/D9)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.skills.discogs.conftest import run_skill_script

_SKILL_ID = "discogs-collection"
_WRITE_SCRIPTS = (
    ("add_release.py", ["--folder-id", "0", "--release-id", "1"]),
    ("remove_release.py", ["--folder-id", "0", "--instance-id", "10"]),
    ("move_release.py", ["--folder-id", "0", "--instance-id", "10", "--target-folder-id", "1"]),
    ("uncategorize_release.py", ["--folder-id", "0", "--instance-id", "10"]),
    ("rate_release.py", ["--folder-id", "0", "--instance-id", "10", "--rating", "5"]),
)
_READ_SCRIPTS = (
    "list_folders.py",
    "get_folder.py",
    "search_collection.py",
    "collection_value.py",
)


def _mock_client_module(client: MagicMock) -> object:
    mod = MagicMock()
    mod.Client.return_value = client
    return mod


@pytest.mark.parametrize("script_name", _READ_SCRIPTS)
def test_read_script_returns_ok_envelope(script_name: str, tmp_path: Path) -> None:
    client = MagicMock()
    user = MagicMock()
    user.collection_folders = [MagicMock(id=0, name="All")]
    folder = MagicMock()
    folder.releases = MagicMock(pages=1, page=1, per_page=50, count=0)
    user.collection_folder.return_value = folder
    user.collection_value.return_value = MagicMock(minimum=1, median=2, maximum=3)
    user.collection_items.return_value = MagicMock(pages=1, page=1, per_page=50, count=0)
    client.identity.return_value = user
    with patch.dict("sys.modules", {"discogs_client": _mock_client_module(client)}):
        code, payload = run_skill_script(
            _SKILL_ID,
            script_name,
            ["--folder-id", "0"] if script_name != "list_folders.py" else [],
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
    client.identity.return_value = MagicMock(username="collector")
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
