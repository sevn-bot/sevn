"""Tests for the CGR argv allowlist + capped export reader."""

from __future__ import annotations

import pytest

from sevn.code_understanding.cgr_adapter import (
    CGR_ALLOWED_SUBCOMMANDS,
    build_cgr_argv,
    read_export_capped,
)


@pytest.mark.parametrize("subcommand", sorted(CGR_ALLOWED_SUBCOMMANDS))
def test_build_cgr_argv_accepts_allowlist(subcommand: str) -> None:
    argv = build_cgr_argv(subcommand)
    assert argv == ["cgr", subcommand]


@pytest.mark.parametrize("subcommand", ["shell", "bash", "import", "", "sh", "export ;rm -rf"])
def test_build_cgr_argv_rejects_disallowed(subcommand: str) -> None:
    with pytest.raises(ValueError, match="code_graph_rag"):
        build_cgr_argv(subcommand)


def test_build_cgr_argv_appends_extra() -> None:
    argv = build_cgr_argv("stats", ["--repo", "/r"])
    assert argv == ["cgr", "stats", "--repo", "/r"]


def test_read_export_capped_truncates() -> None:
    assert read_export_capped(b"abcdef", 3) == b"abc"


def test_read_export_capped_keeps_short_payload() -> None:
    assert read_export_capped(b"abc", 99) == b"abc"


def test_read_export_capped_zero_returns_empty() -> None:
    assert read_export_capped(b"abc", 0) == b""


def test_read_export_capped_rejects_negative() -> None:
    with pytest.raises(ValueError, match="max_bytes must be non-negative"):
        read_export_capped(b"abc", -1)
