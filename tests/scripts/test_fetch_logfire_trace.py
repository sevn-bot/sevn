"""Tests for Logfire trace export script."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest
from scripts.fetch_logfire_trace import (
    QUERY_ROW_LIMIT,
    _inline_json,
    _parse_env_file,
    _query_logfire,
    _rows_from_payload,
    build_document,
    fetch_trace,
    validate_base_url,
    validate_trace_id,
)


def test_validate_trace_id_accepts_hex() -> None:
    validate_trace_id("019fe645e8b9059835f7a5b56c3cea0f")


@pytest.mark.parametrize(
    "trace_id",
    [
        "../../scripts/fetch_logfire_trace",
        "x' OR '1'='1",
        "dead-beef",
        "",
    ],
)
def test_validate_trace_id_rejects_unsafe_values(trace_id: str) -> None:
    with pytest.raises(SystemExit, match="trace_id must be hex"):
        validate_trace_id(trace_id)


def test_validate_base_url_accepts_supported_regions() -> None:
    assert validate_base_url("https://logfire-eu.pydantic.dev") == "https://logfire-eu.pydantic.dev"
    assert (
        validate_base_url("https://logfire-us.pydantic.dev/") == "https://logfire-us.pydantic.dev"
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://logfire-eu.pydantic.dev",
        "https://evil.example",
        "https://logfire-eu.pydantic.dev/exfil",
    ],
)
def test_validate_base_url_rejects_untrusted_hosts(base_url: str) -> None:
    with pytest.raises(SystemExit, match="base-url"):
        validate_base_url(base_url)


def test_parse_env_file() -> None:
    assert _parse_env_file("# c\nA=1\nexport B='two'\n") == {"A": "1", "B": "two"}


def test_rows_from_payload_column_shape() -> None:
    rows = _rows_from_payload({"columns": [{"name": "a", "values": [1, 2]}]})
    assert rows == [{"a": 1}, {"a": 2}]


def test_rows_from_payload_row_shape() -> None:
    assert _rows_from_payload({"rows": [{"a": 1}]}) == [{"a": 1}]


def test_inline_json_parses_objects() -> None:
    assert _inline_json('{"a": 1}') == {"a": 1}
    assert _inline_json("plain") == "plain"


def test_build_document_envelope() -> None:
    doc = build_document("t", [{"span_name": "root", "parent_span_id": None}], project="p")
    assert doc["root_span_name"] == "root"
    assert doc["span_count"] == 1
    assert doc["project"] == "p"


def _column_payload(values: list[object]) -> dict[str, object]:
    return {"columns": [{"name": "span_name", "values": values}]}


def test_fetch_trace_paginates_at_row_limit() -> None:
    first_page = _column_payload([f"span-{index}" for index in range(QUERY_ROW_LIMIT)])
    second_page = _column_payload(["tail-span"])

    with patch(
        "scripts.fetch_logfire_trace._query_logfire",
        side_effect=[first_page, second_page],
    ) as query:
        rows = fetch_trace("tok", "abc123", base_url="https://logfire-eu.pydantic.dev")

    assert len(rows) == QUERY_ROW_LIMIT + 1
    assert rows[-1]["span_name"] == "tail-span"
    assert query.call_count == 2
    assert "OFFSET 0" in query.call_args_list[0].args[2]
    assert f"OFFSET {QUERY_ROW_LIMIT}" in query.call_args_list[1].args[2]


def test_fetch_trace_single_page() -> None:
    payload = _column_payload(["only-span"])
    with patch("scripts.fetch_logfire_trace._query_logfire", return_value=payload) as query:
        rows = fetch_trace("tok", "abc123", base_url="https://logfire-eu.pydantic.dev")

    assert rows == [{"span_name": "only-span"}]
    assert query.call_count == 1


def test_fetch_trace_rejects_bad_trace_id_before_network() -> None:
    with (
        patch("scripts.fetch_logfire_trace._query_logfire") as query,
        pytest.raises(SystemExit, match="trace_id must be hex"),
    ):
        fetch_trace("tok", "../../x", base_url="https://logfire-eu.pydantic.dev")
    query.assert_not_called()


def test_fetch_trace_rejects_untrusted_base_url_before_network() -> None:
    with (
        patch("scripts.fetch_logfire_trace._query_logfire") as query,
        pytest.raises(SystemExit, match="base-url"),
    ):
        fetch_trace("tok", "abc123", base_url="https://evil.example")
    query.assert_not_called()


def test_query_logfire_http_error() -> None:
    body = BytesIO(b'{"detail":"nope"}')
    error = HTTPError(
        url="https://logfire-eu.pydantic.dev/v1/query",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=body,
    )
    with (
        patch("urllib.request.urlopen", side_effect=error),
        pytest.raises(SystemExit, match="401"),
    ):
        _query_logfire("tok", "https://logfire-eu.pydantic.dev", "SELECT 1")


def test_query_logfire_request_includes_response_limit() -> None:
    captured_urls: list[str] = []

    def fake_urlopen(request: object, timeout: int = 180) -> MagicMock:
        captured_urls.append(getattr(request, "full_url", ""))
        response = MagicMock()
        response.read.return_value = b'{"rows": []}'
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        _query_logfire("tok", "https://logfire-eu.pydantic.dev", "SELECT 1")

    assert captured_urls
    query = parse_qs(urlparse(captured_urls[0]).query)
    assert query["limit"] == [str(QUERY_ROW_LIMIT)]
    assert query["sql"] == ["SELECT 1"]
