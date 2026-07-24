"""Persistent-tunnel autostart seam (gateway-boot start gated on the flag)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sevn.infrastructure.tunnel_autostart import (
    autostart_tunnel_if_enabled,
    start_configured_tunnel,
    tunnel_autostart_enabled,
)
from sevn.infrastructure.tunnel_manager import TunnelStatus


class _FakeManager:
    """Records ``start`` calls and returns a canned status (no real subprocess)."""

    def __init__(self, status: TunnelStatus | None = None, exc: Exception | None = None) -> None:
        self.status = status
        self.exc = exc
        self.started: list[dict[str, Any]] = []

    def start(self, tunnel_config: dict[str, Any], *, confirm: bool) -> TunnelStatus:
        self.started.append({"cfg": tunnel_config, "confirm": confirm})
        if self.exc is not None:
            raise self.exc
        assert self.status is not None
        return self.status


def _healthy(mode: str = "cloudflare_quick") -> TunnelStatus:
    return TunnelStatus(
        mode=mode,
        pid=4321,
        healthy=True,
        public_url="https://x.trycloudflare.com",
        error=None,
        mission_control_url="https://x.trycloudflare.com",
    )


def test_autostart_enabled_requires_flag_and_runnable_mode() -> None:
    assert tunnel_autostart_enabled({"mode": "cloudflare", "autostart": True}) is True
    assert tunnel_autostart_enabled({"mode": "cloudflare", "autostart": False}) is False
    assert tunnel_autostart_enabled({"mode": "none", "autostart": True}) is False
    assert tunnel_autostart_enabled({"autostart": True}) is False


@pytest.mark.asyncio
async def test_start_configured_tunnel_expands_and_starts(tmp_path: Path) -> None:
    mgr = _FakeManager(status=_healthy())
    status = await start_configured_tunnel(
        tunnel_config={"mode": "cloudflare_quick"},
        gateway_port=3001,
        content_root=tmp_path,
        secrets_backend=None,
        manager=mgr,  # type: ignore[arg-type]
    )
    assert status.healthy is True
    assert len(mgr.started) == 1
    # prepare_tunnel_runtime_cfg defaults the local port from the gateway port.
    assert mgr.started[0]["cfg"]["local_port"] == 3001
    assert mgr.started[0]["confirm"] is True


@pytest.mark.asyncio
async def test_autostart_disabled_does_not_start(tmp_path: Path) -> None:
    mgr = _FakeManager(status=_healthy())
    result = await autostart_tunnel_if_enabled(
        tunnel_config={"mode": "cloudflare_quick", "autostart": False},
        gateway_port=3001,
        content_root=tmp_path,
        secrets_backend=None,
        manager=mgr,  # type: ignore[arg-type]
    )
    assert result is None
    assert mgr.started == []


@pytest.mark.asyncio
async def test_autostart_enabled_starts(tmp_path: Path) -> None:
    mgr = _FakeManager(status=_healthy())
    result = await autostart_tunnel_if_enabled(
        tunnel_config={"mode": "cloudflare_quick", "autostart": True},
        gateway_port=3001,
        content_root=tmp_path,
        secrets_backend=None,
        manager=mgr,  # type: ignore[arg-type]
    )
    assert result is not None
    assert result.healthy is True
    assert len(mgr.started) == 1


@pytest.mark.asyncio
async def test_autostart_swallows_provider_error(tmp_path: Path) -> None:
    """A missing cloudflared binary must never crash boot."""
    mgr = _FakeManager(exc=RuntimeError("cloudflared binary not found on PATH"))
    result = await autostart_tunnel_if_enabled(
        tunnel_config={"mode": "cloudflare_quick", "autostart": True},
        gateway_port=3001,
        content_root=tmp_path,
        secrets_backend=None,
        manager=mgr,  # type: ignore[arg-type]
    )
    assert result is None
    assert len(mgr.started) == 1


@pytest.mark.asyncio
async def test_autostart_swallows_os_error(tmp_path: Path) -> None:
    """A failed subprocess spawn (OSError) must never crash boot."""
    mgr = _FakeManager(exc=OSError("exec format error"))
    result = await autostart_tunnel_if_enabled(
        tunnel_config={"mode": "cloudflare_quick", "autostart": True},
        gateway_port=3001,
        content_root=tmp_path,
        secrets_backend=None,
        manager=mgr,  # type: ignore[arg-type]
    )
    assert result is None
    assert len(mgr.started) == 1


class _HangingManager:
    """``start`` blocks past the timeout (models a stuck tailscale CLI spawn)."""

    def start(self, tunnel_config: dict[str, Any], *, confirm: bool) -> TunnelStatus:
        import time

        # Outlive the (patched) timeout without stalling teardown for long.
        time.sleep(1.0)
        return _healthy()


@pytest.mark.asyncio
async def test_start_configured_tunnel_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hung provider spawn raises RuntimeError instead of blocking forever."""
    monkeypatch.setattr("sevn.infrastructure.tunnel_autostart.TUNNEL_START_TIMEOUT_S", 0.05)
    with pytest.raises(RuntimeError, match="did not start within"):
        await start_configured_tunnel(
            tunnel_config={"mode": "cloudflare_quick"},
            gateway_port=3001,
            content_root=tmp_path,
            secrets_backend=None,
            manager=_HangingManager(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_autostart_swallows_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A boot-time spawn timeout is logged and skipped, never fatal."""
    monkeypatch.setattr("sevn.infrastructure.tunnel_autostart.TUNNEL_START_TIMEOUT_S", 0.05)
    result = await autostart_tunnel_if_enabled(
        tunnel_config={"mode": "cloudflare_quick", "autostart": True},
        gateway_port=3001,
        content_root=tmp_path,
        secrets_backend=None,
        manager=_HangingManager(),  # type: ignore[arg-type]
    )
    assert result is None
