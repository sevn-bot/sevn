"""discogs-database skill script contracts (W1.5 / D13)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.skills.discogs.conftest import load_skill_script, run_skill_script

_SKILL_ID = "discogs-database"
_READ_SCRIPTS = (
    "search.py",
    "get_artist.py",
    "get_release.py",
    "get_master.py",
    "get_label.py",
    "price_suggestions.py",
    "marketplace_stats.py",
)


def _mock_client_module(client: MagicMock) -> object:
    mod = MagicMock()
    mod.Client.return_value = client
    return mod


@pytest.mark.parametrize("script_name", _READ_SCRIPTS)
def test_read_script_returns_ok_envelope(script_name: str, tmp_path: Path) -> None:
    client = MagicMock()
    client.search.return_value = MagicMock(pages=1, page=1, per_page=50, count=0)
    client.artist.return_value = MagicMock(id=1, name="Artist")
    client.release.return_value = MagicMock(id=2, title="Release")
    client.master.return_value = MagicMock(id=3, title="Master")
    client.label.return_value = MagicMock(id=4, name="Label")
    with patch.dict("sys.modules", {"discogs_client": _mock_client_module(client)}):
        code, payload = run_skill_script(
            _SKILL_ID,
            script_name,
            ["--id", "1"] if script_name != "search.py" else ["--query", "test"],
            workspace=tmp_path,
            env={
                "DISCOGS_USER_AGENT": "sevn-discogs/1.0",
                "DISCOGS_AUTH_METHOD": "user_token",
            },
        )
    assert code == 0
    assert payload["ok"] is True
    assert "data" in payload


def test_search_honors_filters_and_paging(tmp_path: Path) -> None:
    client = MagicMock()
    results = MagicMock(pages=3, page=2, per_page=25, count=60)
    client.search.return_value = results
    mod = load_skill_script(_SKILL_ID, "search.py")
    with patch.dict("sys.modules", {"discogs_client": _mock_client_module(client)}):
        code, payload = mod.main(
            [
                "--query",
                "kraftwerk",
                "--type",
                "release",
                "--genre",
                "Electronic",
                "--page",
                "2",
                "--per-page",
                "25",
            ],
        )
    assert code == 0
    assert payload["ok"] is True
    client.search.assert_called_once()
    assert payload["paging"]["page"] == 2
    assert payload["paging"]["per_page"] == 25
