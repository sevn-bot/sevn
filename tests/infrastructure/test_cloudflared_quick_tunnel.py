"""Tests for Cloudflare quick tunnel URL discovery."""

from __future__ import annotations

import io
import subprocess
from unittest.mock import MagicMock

import pytest

from sevn.infrastructure.cloudflared_quick_tunnel import (
    extract_quick_tunnel_url,
    read_quick_tunnel_url,
)


def test_extract_quick_tunnel_url_from_log_line() -> None:
    assert (
        extract_quick_tunnel_url("Visit it at https://abc-def.trycloudflare.com")
        == "https://abc-def.trycloudflare.com/"
    )


def test_read_quick_tunnel_url_from_stderr() -> None:
    stderr = io.StringIO()
    stderr.write("INF |  https://live-demo.trycloudflare.com\n")
    stderr.seek(0)

    proc = MagicMock(spec=subprocess.Popen)
    proc.poll.return_value = None
    proc.stderr = stderr

    assert read_quick_tunnel_url(proc, timeout=2.0) == "https://live-demo.trycloudflare.com/"


def test_read_quick_tunnel_url_times_out_when_missing() -> None:
    stderr = io.StringIO()
    proc = MagicMock(spec=subprocess.Popen)
    proc.poll.return_value = None
    proc.stderr = stderr

    with pytest.raises(RuntimeError, match="timed out"):
        read_quick_tunnel_url(proc, timeout=0.3)
