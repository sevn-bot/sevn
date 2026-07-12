"""macOS pf ruleset helper (`specs/08-sandbox.md` §11)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from sevn.security.egress_firewall import write_macos_pf_ruleset


@pytest.mark.skipif(sys.platform != "darwin", reason="pf ruleset writer is macOS-only")
def test_write_macos_pf_ruleset_includes_proxy_port() -> None:
    dest = Path(tempfile.mkdtemp()) / "sevn-pf.rules"
    write_macos_pf_ruleset(dest, proxy_port=8787)
    text = dest.read_text(encoding="utf-8")
    assert "port 8787" in text
    assert "block out" in text
