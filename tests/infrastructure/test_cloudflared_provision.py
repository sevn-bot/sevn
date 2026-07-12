"""Tests for cloudflared provisioning helpers."""

from __future__ import annotations

import subprocess

import pytest

from sevn.infrastructure.cloudflared_provision import (
    ensure_cloudflared_binary,
    parse_cloudflared_tunnel_input,
)


def test_parse_cloudflared_tunnel_input_from_service_install() -> None:
    token = parse_cloudflared_tunnel_input(
        "sudo cloudflared service install eyJhIjoiYzExZGY0YjJjIn0="
    )
    assert token == "eyJhIjoiYzExZGY0YjJjIn0="


def test_parse_cloudflared_tunnel_input_from_bare_token() -> None:
    assert parse_cloudflared_tunnel_input("eyJhIjoiYSJ9") == "eyJhIjoiYSJ9"


def test_parse_cloudflared_tunnel_input_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="Install as service"):
        parse_cloudflared_tunnel_input("not a cloudflare command at all")


def test_ensure_cloudflared_binary_uses_existing_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sevn.infrastructure.cloudflared_provision.shutil.which",
        lambda name: "/opt/homebrew/bin/cloudflared" if name == "cloudflared" else None,
    )
    path, detail = ensure_cloudflared_binary()
    assert path == "/opt/homebrew/bin/cloudflared"
    assert detail == "cloudflared already on PATH"


def test_ensure_cloudflared_binary_installs_with_brew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    installed = False

    def _which(name: str) -> str | None:
        nonlocal installed
        if name == "brew":
            return "/opt/homebrew/bin/brew"
        if name == "cloudflared":
            return "/opt/homebrew/bin/cloudflared" if installed else None
        return None

    def _runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal installed
        calls.append(argv)
        installed = True
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "sevn.infrastructure.cloudflared_provision.platform.system", lambda: "darwin"
    )
    monkeypatch.setattr("sevn.infrastructure.cloudflared_provision.shutil.which", _which)
    path, detail = ensure_cloudflared_binary(runner=_runner)
    assert calls == [["brew", "install", "cloudflared"]]
    assert path == "/opt/homebrew/bin/cloudflared"
    assert "installed cloudflared via brew" in detail
