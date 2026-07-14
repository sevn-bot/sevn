"""Persistent deployment id tests (`specs/17-gateway.md` §10.14 TE-1)."""

from __future__ import annotations

import json
import re
import socket
from pathlib import Path

from sevn.gateway.runtime.deployment_id import load_or_create_deployment_id

_DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+-\d{14}-[0-9a-f]{6}$")


def _deployment_file(content_root: Path) -> Path:
    return content_root / ".sevn" / "deployment_id.json"


def test_first_call_creates_persisted_id(tmp_path: Path) -> None:
    """The first call mints an id and writes it to ``.sevn/deployment_id.json``."""
    target = _deployment_file(tmp_path)
    assert not target.exists()

    did = load_or_create_deployment_id(tmp_path)

    assert isinstance(did, str)
    assert did.strip()
    assert target.is_file()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["deployment_id"] == did
    assert "created_at" in payload


def test_second_call_returns_stable_id(tmp_path: Path) -> None:
    """Subsequent calls return the same id without rewriting the file."""
    first = load_or_create_deployment_id(tmp_path)
    target = _deployment_file(tmp_path)
    mtime = target.stat().st_mtime_ns

    second = load_or_create_deployment_id(tmp_path)

    assert second == first
    # File contents are not rewritten when an id is already persisted.
    assert target.stat().st_mtime_ns == mtime


def test_deleting_json_regenerates_fresh_id(tmp_path: Path) -> None:
    """Removing the JSON forces the next call to mint a brand new id."""
    first = load_or_create_deployment_id(tmp_path)
    target = _deployment_file(tmp_path)
    target.unlink()

    second = load_or_create_deployment_id(tmp_path)

    assert second != first
    assert target.is_file()


def test_format_matches_hostname_timestamp_hex(tmp_path: Path) -> None:
    """Id format is ``{hostname}-{YYYYMMDDHHMMSS}-{6-char-hex}``."""
    did = load_or_create_deployment_id(tmp_path)

    assert _DEPLOYMENT_ID_RE.match(did), did
    # The leading segment should reflect the (sanitised) hostname.
    raw_host = (socket.gethostname() or "").strip()
    if raw_host:
        # We can't reproduce the sanitiser regex here without coupling tests to
        # implementation details, but at minimum the suffix is six hex chars
        # and the middle segment is a 14-digit timestamp.
        head, stamp, suffix = did.rsplit("-", 2)
        assert head  # non-empty hostname segment
        assert len(stamp) == 14
        assert stamp.isdigit()
        assert len(suffix) == 6
        assert all(c in "0123456789abcdef" for c in suffix)


def test_creates_dot_sevn_dir_when_missing(tmp_path: Path) -> None:
    """Calling without an existing ``.sevn`` directory creates one."""
    nested_root = tmp_path / "workspace"
    nested_root.mkdir()
    assert not (nested_root / ".sevn").exists()

    did = load_or_create_deployment_id(nested_root)

    assert (nested_root / ".sevn").is_dir()
    assert (nested_root / ".sevn" / "deployment_id.json").is_file()
    assert did.strip()


def test_corrupt_json_is_replaced(tmp_path: Path) -> None:
    """Unreadable/corrupt JSON is replaced with a fresh id rather than crashing."""
    target = _deployment_file(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not-json", encoding="utf-8")

    did = load_or_create_deployment_id(tmp_path)

    assert _DEPLOYMENT_ID_RE.match(did), did
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["deployment_id"] == did
