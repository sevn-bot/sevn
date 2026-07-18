"""Shared ``_discogs_common.py`` helper contracts (W1.4 / D7/D11/D12)."""

from __future__ import annotations

import doctest
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from tests.skills.discogs.conftest import DISCOGS_SKILL_IDS, common_script_path, load_discogs_common

_COMMON: ModuleType | None = None


def _common() -> ModuleType:
    global _COMMON
    if _COMMON is None:
        _COMMON = load_discogs_common()
    return _COMMON


def test_write_ok_envelope_shape() -> None:
    common = _common()
    payload = common.write_ok(
        {"items": []}, paging={"page": 1, "pages": 2, "per_page": 50, "count": 1}
    )
    assert payload["ok"] is True
    assert payload["data"] == {"items": []}
    assert payload["paging"]["page"] == 1


def test_write_err_envelope_shape() -> None:
    common = _common()
    payload = common.write_err(code="BAD_ARGS", message="missing release id")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "BAD_ARGS"
    assert payload["error"]["message"] == "missing release id"


def test_paginate_math() -> None:
    common = _common()
    page = MagicMock(page=2, pages=5, per_page=25, count=120)
    paging = common.paginate(page)
    assert paging == {"page": 2, "pages": 5, "per_page": 25, "count": 120}


def test_require_confirm_without_flag_returns_preview() -> None:
    common = _common()
    args = MagicMock(confirm=False)
    preview = common.require_confirm(args, would_do={"action": "delete_listing", "id": 42})
    assert preview["ok"] is False
    assert preview["error"]["code"] == "CONFIRM_REQUIRED"
    assert preview["error"]["would_do"]["id"] == 42


def test_require_confirm_skipped_when_config_allows() -> None:
    common = _common()
    args = MagicMock(confirm=False)
    assert common.require_confirm(args, would_do={"action": "noop"}, confirm_writes=False) is None


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "AUTH_REQUIRED"),
        (403, "AUTH_REQUIRED"),
        (404, "NOT_FOUND"),
        (429, "RATE_LIMITED"),
        (500, "DISCOGS_HTTP"),
    ],
)
def test_map_discogs_error_stable_codes(status_code: int, expected_code: str) -> None:
    common = _common()
    exc = MagicMock()
    exc.status_code = status_code
    exc.__class__.__name__ = "HTTPError"
    mapped = common.map_discogs_error(exc)
    assert mapped["code"] == expected_code
    assert "token" not in mapped["message"].lower()


def test_map_discogs_error_never_leaks_token_in_message() -> None:
    common = _common()
    exc = MagicMock()
    exc.status_code = 401
    exc.__str__.return_value = "401 Unauthorized token=leaked-secret"
    mapped = common.map_discogs_error(exc)
    assert "leaked-secret" not in mapped["message"]


def test_discogs_common_stubs_are_byte_identical() -> None:
    canonical = common_script_path("discogs-database").read_bytes()
    for skill_id in DISCOGS_SKILL_IDS:
        stub = common_script_path(skill_id).read_bytes()
        assert stub == canonical, (
            f"{skill_id}/scripts/_discogs_common.py diverges from canonical stub"
        )


def test_discogs_common_doctests_are_network_free() -> None:
    common = _common()
    finder = doctest.DocTestFinder()
    tests = finder.find(common)
    assert tests, "_discogs_common.py must ship Examples: doctests"
    runner = doctest.DocTestRunner(verbose=False)
    for test in tests:
        result = runner.run(test)
        assert result.failed == 0, result
