#!/usr/bin/env python3
"""Export one complete Logfire trace to a local JSON document.

Module: scripts.fetch_logfire_trace
Depends: argparse, json, os, pathlib, sys, urllib

Reads ``LOGFIRE_READ_TOKEN`` from the process environment, falling back to the
repo-root ``.env`` (gitignored). The token is never echoed, logged, or written
to the output file.

Why this exists: the Logfire MCP server returns query results into the agent's
context window, so exporting a real gateway turn — five LLM calls each carrying
the full re-sent message history — costs ~250k tokens and cannot complete in one
window. This script streams the same rows straight to disk instead, so an agent
pays only the row count. Reading the token from ``.env`` rather than the shell
keeps the secret out of the transcript: an agent that runs
``source .env`` puts the value in a command line, and every command line is
recorded.

Exports:
    fetch_trace — GET one trace's records from the Logfire query API.
    build_document — Wrap span rows in a trace-level metadata envelope.
    resolve_token — Find the read token in the environment or ``.env``.
    validate_trace_id — Reject non-hex trace ids before SQL/path sinks.
    validate_base_url — Allow only HTTPS Logfire region hosts.
    main — CLI entry.

Examples:
    >>> build_document("abc", [], project="p")["span_count"]
    0
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

TOKEN_VAR = "LOGFIRE_READ_TOKEN"
DEFAULT_BASE_URL = "https://logfire-eu.pydantic.dev"
DEFAULT_PROJECT = "sevn-testing"
REQUEST_TIMEOUT = 180
QUERY_ROW_LIMIT = 10_000
_TRACE_ID_RE = re.compile(r"^[0-9a-fA-F]+$")
ALLOWED_LOGFIRE_HOSTS = frozenset(
    {
        "logfire-eu.pydantic.dev",
        "logfire-us.pydantic.dev",
    }
)

#: Columns pulled for every span. Explicit rather than ``SELECT *`` so the
#: export stays stable when Logfire adds columns.
RECORD_COLUMNS = (
    "trace_id, span_id, parent_span_id, kind, span_name, message, level, "
    "start_timestamp, end_timestamp, duration, created_at, day, "
    "service_name, service_namespace, service_version, service_instance_id, "
    "deployment_environment, process_pid, project_id, tags, "
    "otel_scope_name, otel_scope_version, otel_scope_attributes, "
    "otel_status_code, otel_status_message, otel_events, otel_links, "
    "otel_resource_attributes, attributes, attributes_json_schema, "
    "is_exception, exception_type, exception_message, exception_stacktrace, "
    "log_body, http_method, http_route, http_response_status_code, "
    "url_full, url_path, url_query, "
    "telemetry_sdk_name, telemetry_sdk_language, telemetry_sdk_version"
)

#: Columns Logfire stores as JSON-encoded text. Parsed back into objects so the
#: dump is navigable instead of a wall of escaped strings.
JSON_COLUMNS = (
    "attributes",
    "attributes_json_schema",
    "otel_events",
    "otel_links",
    "otel_resource_attributes",
    "otel_scope_attributes",
)


def _repo_root() -> Path:
    """Return the repo root (this file's parent directory's parent).

    Returns:
        Path: Absolute path to the checkout containing ``scripts/``.

    Examples:
        >>> (_repo_root() / "scripts").is_dir()
        True
    """
    return Path(__file__).resolve().parents[1]


def _parse_env_file(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines from a dotenv-style file body.

    Ignores blanks, comments, and ``export`` prefixes; strips one layer of
    matching quotes. Deliberately minimal — no interpolation, no multiline
    values — because the only consumer is a single opaque token.

    Args:
        text (str): Full file contents.

    Returns:
        dict[str, str]: Parsed key/value pairs.

    Examples:
        >>> _parse_env_file("# c\\nA=1\\nexport B='two'\\n")
        {'A': '1', 'B': 'two'}
        >>> _parse_env_file("BARE\\nC=\\n")
        {'C': ''}
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def resolve_token(env_path: Path | None = None) -> str:
    """Resolve the Logfire read token from the environment or ``.env``.

    The process environment wins so CI and one-off overrides work without
    editing files.

    Args:
        env_path (Path | None): Dotenv file to consult. Defaults to the
            repo-root ``.env``.

    Returns:
        str: The read token.

    Raises:
        SystemExit: When no token is configured in either source.

    Examples:
        >>> import os
        >>> os.environ[TOKEN_VAR] = "tok"
        >>> resolve_token()
        'tok'
        >>> del os.environ[TOKEN_VAR]
    """
    from_env = os.environ.get(TOKEN_VAR, "").strip()
    if from_env:
        return from_env

    path = env_path if env_path is not None else _repo_root() / ".env"
    if path.is_file():
        token = _parse_env_file(path.read_text(encoding="utf-8")).get(TOKEN_VAR, "").strip()
        if token:
            return token

    raise SystemExit(
        f"{TOKEN_VAR} is not set.\n"
        f"  Add it to {path} (gitignored) or export it for one command.\n"
        "  Create a read token: Logfire project -> Settings -> Read tokens."
    )


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Normalise Logfire's response into row dicts.

    The query API answers column-oriented (``columns: [{name, values}]``); the
    MCP surface answers row-oriented. Both shapes are accepted so the parsing
    does not silently break if the endpoint changes.

    Args:
        payload (Any): Decoded JSON response body.

    Returns:
        list[dict[str, Any]]: One dict per span.

    Raises:
        SystemExit: When the payload matches no known shape.

    Examples:
        >>> _rows_from_payload({"columns": [{"name": "a", "values": [1, 2]}]})
        [{'a': 1}, {'a': 2}]
        >>> _rows_from_payload({"rows": [{"a": 1}]})
        [{'a': 1}]
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        columns = payload.get("columns")
        if isinstance(columns, list) and columns and "values" in columns[0]:
            names = [column["name"] for column in columns]
            height = len(columns[0]["values"])
            return [
                {names[i]: columns[i]["values"][row] for i in range(len(names))}
                for row in range(height)
            ]
        rows = payload.get("rows")
        if isinstance(rows, list):
            return rows
    raise SystemExit(f"Unexpected Logfire response shape: {type(payload).__name__}")


def validate_trace_id(trace_id: str) -> None:
    """Reject trace ids that are not hex (blocks SQL injection and path traversal).

    Args:
        trace_id (str): Raw CLI value.

    Raises:
        SystemExit: When the value is not a hex string.

    Examples:
        >>> validate_trace_id("019fe645e8b9059835f7a5b56c3cea0f")
        >>> validate_trace_id("../../x")  # doctest: +SKIP
        Traceback (most recent call last):
        ...
        SystemExit: ...
    """
    if not _TRACE_ID_RE.fullmatch(trace_id):
        raise SystemExit(f"trace_id must be hex, got {trace_id!r}")


def validate_base_url(base_url: str) -> str:
    """Allow only HTTPS Logfire region hosts before sending the read token.

    Args:
        base_url (str): Configured region host.

    Returns:
        str: Normalised base URL without a trailing slash.

    Raises:
        SystemExit: When the host is not on the allowlist.

    Examples:
        >>> validate_base_url("https://logfire-eu.pydantic.dev")
        'https://logfire-eu.pydantic.dev'
        >>> validate_base_url("https://evil.example")  # doctest: +SKIP
        Traceback (most recent call last):
        ...
        SystemExit: ...
    """
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "https":
        raise SystemExit(f"base-url must use https, got {base_url!r}")
    if parsed.netloc not in ALLOWED_LOGFIRE_HOSTS:
        hosts = ", ".join(sorted(ALLOWED_LOGFIRE_HOSTS))
        raise SystemExit(
            f"base-url must be a supported Logfire region host ({hosts}), got {base_url!r}"
        )
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise SystemExit(f"base-url must be a host only, got {base_url!r}")
    return f"https://{parsed.netloc}"


def _inline_json(value: Any) -> Any:
    """Decode a JSON-encoded string column, leaving anything else untouched.

    Args:
        value (Any): Raw column value.

    Returns:
        Any: Parsed object, or the input when it is not JSON text.

    Examples:
        >>> _inline_json('{"a": 1}')
        {'a': 1}
        >>> _inline_json("plain")
        'plain'
    """
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _trace_sql(trace_id: str, *, offset: int = 0) -> str:
    """Build the paginated SQL for one trace export page.

    Args:
        trace_id (str): Hex trace identifier (already validated).
        offset (int): Row offset for pagination.

    Returns:
        str: SQL selecting one page of span rows, oldest first.

    Examples:
        >>> "LIMIT 10000 OFFSET 0" in _trace_sql("abc123")
        True
        >>> "OFFSET 10000" in _trace_sql("abc123", offset=10000)
        True
    """
    return (
        f"SELECT {RECORD_COLUMNS} FROM records "
        f"WHERE trace_id = '{trace_id}' ORDER BY start_timestamp "
        f"LIMIT {QUERY_ROW_LIMIT} OFFSET {offset}"
    )


def _query_logfire(token: str, base_url: str, sql: str) -> Any:
    """Run one Logfire query and return the decoded JSON body.

    Args:
        token (str): Logfire read token.
        base_url (str): Normalised region host.
        sql (str): Query to execute.

    Returns:
        Any: Decoded JSON response body.

    Raises:
        SystemExit: When the API rejects the request or the host is unreachable.

    Examples:
        >>> _query_logfire("tok", "https://logfire-eu.pydantic.dev", "SELECT 1")  # doctest: +SKIP
        ...
    """
    url = f"{base_url}/v1/query?{urllib.parse.urlencode({'sql': sql, 'limit': QUERY_ROW_LIMIT})}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": token, "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        detail = exc.read().decode("utf-8", "replace")[:400]
        hint = " (is the token a *read* token for this project?)" if exc.code == 401 else ""
        raise SystemExit(f"Logfire API returned {exc.code}{hint}: {detail}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network path
        raise SystemExit(f"Could not reach {base_url}: {exc.reason}") from exc


def _inline_row_json(rows: list[dict[str, Any]]) -> None:
    """Decode JSON-encoded columns in place for one page of rows.

    Args:
        rows (list[dict[str, Any]]): Span rows to mutate in place.

    Examples:
        >>> page = [{"attributes": '{"a": 1}'}]
        >>> _inline_row_json(page)
        >>> page[0]["attributes"]
        {'a': 1}
    """
    for row in rows:
        for column in JSON_COLUMNS:
            if column in row:
                row[column] = _inline_json(row[column])


def fetch_trace(
    token: str,
    trace_id: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> list[dict[str, Any]]:
    """Fetch every record belonging to one trace, oldest span first.

    Args:
        token (str): Logfire read token.
        trace_id (str): Hex trace identifier.
        base_url (str): Region host, e.g. the EU or US Logfire endpoint.

    Returns:
        list[dict[str, Any]]: Span rows with JSON columns inlined.

    Raises:
        SystemExit: When the API rejects the request.

    Examples:
        >>> fetch_trace("tok", "019fe645")[0]["span_name"]  # doctest: +SKIP
        'gateway.turn.start'
    """
    validate_trace_id(trace_id)
    host = validate_base_url(base_url)

    all_rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        payload = _query_logfire(token, host, _trace_sql(trace_id, offset=offset))
        page = _rows_from_payload(payload)
        _inline_row_json(page)
        all_rows.extend(page)
        if len(page) < QUERY_ROW_LIMIT:
            break
        offset += QUERY_ROW_LIMIT
    return all_rows


def build_document(
    trace_id: str,
    rows: list[dict[str, Any]],
    *,
    project: str = DEFAULT_PROJECT,
) -> dict[str, Any]:
    """Wrap span rows in a trace-level metadata envelope.

    Args:
        trace_id (str): Hex trace identifier.
        rows (list[dict[str, Any]]): Span rows, oldest first.
        project (str): Logfire project the trace came from.

    Returns:
        dict[str, Any]: One dict describing the whole trace.

    Examples:
        >>> doc = build_document("t", [{"span_name": "root", "parent_span_id": None}])
        >>> doc["root_span_name"], doc["span_count"]
        ('root', 1)
    """
    root = next((row for row in rows if not row.get("parent_span_id")), None)
    end_stamps: list[str] = [row["end_timestamp"] for row in rows if row.get("end_timestamp")]
    return {
        "trace_id": trace_id,
        "project": project,
        "span_count": len(rows),
        "root_span_name": root.get("span_name") if root else None,
        "start_timestamp": rows[0].get("start_timestamp") if rows else None,
        "end_timestamp": max(end_stamps) if end_stamps else None,
        "spans": rows,
    }


def main(argv: list[str] | None = None) -> int:
    """Fetch a trace and write it to disk.

    Args:
        argv (list[str] | None): Argument vector, defaulting to ``sys.argv``.

    Returns:
        int: Process exit code.

    Examples:
        >>> main(["019fe645e8b9059835f7a5b56c3cea0f"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(
        description="Export a full Logfire trace to a local JSON file.",
        epilog=(
            f"Token: {TOKEN_VAR} from the environment, else the repo-root .env. "
            "Output lands in .ignorelocal/ (gitignored) and may contain prompts, "
            "tool output, and workspace file contents."
        ),
    )
    parser.add_argument("trace_id", help="Hex trace id, e.g. 019fe645e8b9...")
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        help="Output path (default: .ignorelocal/trace-<trace_id>.json)",
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("LOGFIRE_PROJECT", DEFAULT_PROJECT),
        help=f"Project name recorded in the envelope (default: {DEFAULT_PROJECT})",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LOGFIRE_BASE_URL", DEFAULT_BASE_URL),
        help=f"Logfire region host (default: {DEFAULT_BASE_URL})",
    )
    args = parser.parse_args(argv)

    validate_trace_id(args.trace_id)
    base_url = validate_base_url(args.base_url)

    token = resolve_token()
    rows = fetch_trace(token, args.trace_id, base_url=base_url)
    if not rows:
        print(f"No spans found for trace {args.trace_id}", file=sys.stderr)
        return 1

    out_path = args.out or _repo_root() / ".ignorelocal" / f"trace-{args.trace_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    document = build_document(args.trace_id, rows, project=args.project)
    out_path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    size_mb = out_path.stat().st_size / 1_048_576
    print(f"wrote {len(rows)} spans ({size_mb:.1f} MB) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
