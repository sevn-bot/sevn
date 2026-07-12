"""Linux iptables ruleset helper (`specs/08-sandbox.md` §11)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from sevn.security.egress_firewall import (
    apply_namespace_egress_firewall,
    write_linux_iptables_ruleset,
)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="iptables writer is Linux-only")
def test_write_linux_iptables_ruleset_includes_proxy() -> None:
    dest = Path(tempfile.mkdtemp()) / "sevn-iptables.rules"
    write_linux_iptables_ruleset(dest, proxy_host_ports=("127.0.0.1:8787",))
    text = dest.read_text(encoding="utf-8")
    assert "8787" in text
    assert "OUTPUT" in text


def test_apply_namespace_writes_rules(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    rules = tmp_path / "rules.txt"
    monkeypatch.setenv("SEVN_SANDBOX_IPTABLES_RULES", str(rules))
    apply_namespace_egress_firewall(proxy_host_ports=("127.0.0.1:8787",))
    assert rules.exists() or rules.with_suffix(".pf.rules").exists()
