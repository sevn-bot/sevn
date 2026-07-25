"""Telegram Config → My sevn bot persistent-tunnel on/off toggle (owner-only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.commands.menu_action_router import MenuActionRouter
from sevn.gateway.menu.menu import (
    _build_my_sevn_bot_keyboard_rows,
    _tunnel_toggle_row,
)
from sevn.gateway.menu.menu_readiness import readiness_for_callback
from sevn.gateway.menu.menu_registry import match_menu_button_spec
from sevn.infrastructure.tunnel_manager import TunnelStatus
from tests.gateway.test_my_sevn_version_id import _build_owner_router, _callback

# --- registry + readiness -------------------------------------------------


def test_tunnel_callbacks_registered_owner_only_and_ready() -> None:
    on = match_menu_button_spec("act:tunnel:on")
    off = match_menu_button_spec("act:tunnel:off")
    assert on is not None
    assert off is not None
    assert on.spec_id == "C22.1"
    assert off.spec_id == "C22.2"
    for spec in (on, off):
        assert spec.section == "my_sevn_bot"
        assert spec.owner_only is True
        assert spec.implemented is True
    # The two-step confirm/cancel sub-callbacks resolve to the same C22.1 spec.
    for sub in ("act:tunnel:on:confirm", "act:tunnel:on:cancel"):
        spec = match_menu_button_spec(sub)
        assert spec is not None, sub
        assert spec.spec_id == "C22.1", sub
    # Pressable (not locked behind cfg:disabled:*).
    assert readiness_for_callback("act:tunnel:on") == "Ready"
    assert readiness_for_callback("act:tunnel:off") == "Ready"


# --- renderer -------------------------------------------------------------


def test_tunnel_toggle_row_reflects_state() -> None:
    assert _tunnel_toggle_row({"mode": "none"}) is None
    assert _tunnel_toggle_row({"mode": "cloudflare"})[0]["callback_data"] == "act:tunnel:on"
    assert (
        _tunnel_toggle_row({"mode": "cloudflare", "autostart": True})[0]["callback_data"]
        == "act:tunnel:off"
    )


def test_my_sevn_bot_rows_include_tunnel_toggle_for_owner() -> None:
    rows = _build_my_sevn_bot_keyboard_rows(
        WorkspaceConfig.minimal(),
        is_owner=True,
        tunnel_cfg={"mode": "cloudflare_quick", "autostart": False},
    )
    cbs = [btn["callback_data"] for row in rows for btn in row]
    assert "act:tunnel:on" in cbs
    assert "cfg:logs:deployment_id" in cbs


def test_my_sevn_bot_rows_omit_tunnel_when_unconfigured() -> None:
    rows = _build_my_sevn_bot_keyboard_rows(
        WorkspaceConfig.minimal(),
        is_owner=True,
        tunnel_cfg={"mode": "none"},
    )
    cbs = [btn["callback_data"] for row in rows for btn in row]
    assert not any(c.startswith("act:tunnel:") for c in cbs)


def test_non_owner_never_sees_tunnel_toggle() -> None:
    rows = _build_my_sevn_bot_keyboard_rows(
        WorkspaceConfig.minimal(),
        is_owner=False,
        tunnel_cfg={"mode": "cloudflare_quick", "autostart": True},
    )
    cbs = [btn["callback_data"] for row in rows for btn in row]
    assert not any(c.startswith("act:tunnel:") for c in cbs)


# --- persistence hint -----------------------------------------------------


def test_tunnel_persistence_hint_empty_when_gateway_daemon_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sevn.gateway.commands.menu_action_router.unit_file_exists",
        lambda **_kwargs: True,
    )
    router = MenuActionRouter.__new__(MenuActionRouter)
    assert router._tunnel_persistence_hint() == ""


def test_tunnel_persistence_hint_warns_when_gateway_daemon_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sevn.gateway.commands.menu_action_router.unit_file_exists",
        lambda **_kwargs: False,
    )
    router = MenuActionRouter.__new__(MenuActionRouter)
    assert "Install the gateway daemon" in router._tunnel_persistence_hint()


# --- action router --------------------------------------------------------


def _set_tunnel_mode(root: Path, mode: str, *, autostart: bool | None = None) -> None:
    sevn_json = root / "sevn.json"
    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    tunnel: dict[str, Any] = {"mode": mode}
    if autostart is not None:
        tunnel["autostart"] = autostart
    doc.setdefault("infrastructure", {})["tunnel"] = tunnel
    sevn_json.write_text(json.dumps(doc), encoding="utf-8")


def _read_tunnel(root: Path) -> dict[str, Any]:
    doc = json.loads((root / "sevn.json").read_text(encoding="utf-8"))
    infra = doc.get("infrastructure")
    tunnel = infra.get("tunnel") if isinstance(infra, dict) else None
    return tunnel if isinstance(tunnel, dict) else {}


def _healthy(mode: str = "cloudflare_quick") -> TunnelStatus:
    return TunnelStatus(
        mode=mode,
        pid=555,
        healthy=True,
        public_url="https://x.trycloudflare.com",
        error=None,
        mission_control_url="https://x.trycloudflare.com",
    )


@pytest.mark.asyncio
async def test_tunnel_on_shows_confirm_prompt_without_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tunnel:on`` opens a two-step confirm — it must not start or persist yet."""
    router, cap, root = _build_owner_router(tmp_path)
    _set_tunnel_mode(root, "cloudflare_quick")

    started: list[Any] = []

    async def _fake_start(**kwargs: Any) -> TunnelStatus:
        started.append(kwargs)
        return _healthy()

    monkeypatch.setattr("sevn.infrastructure.tunnel_autostart.start_configured_tunnel", _fake_start)

    await router.route_incoming(_callback("act:tunnel:on", callback_query_id="cq-prompt"))

    assert started == []
    assert "autostart" not in _read_tunnel(root)
    # The message is edited to the confirm screen exposing the confirm callback.
    confirm_cbs = [
        btn["callback_data"]
        for edit in cap.edited
        for row in edit.get("reply_markup", {}).get("inline_keyboard", [])
        for btn in row
    ]
    assert "act:tunnel:on:confirm" in confirm_cbs
    assert any("Turn tunnel on" in (edit.get("text") or "") for edit in cap.edited)


@pytest.mark.asyncio
async def test_tunnel_on_confirm_sets_autostart_and_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, cap, root = _build_owner_router(tmp_path)
    _set_tunnel_mode(root, "cloudflare_quick")

    calls: list[dict[str, Any]] = []

    async def _fake_start(**kwargs: Any) -> TunnelStatus:
        calls.append(kwargs)
        return _healthy()

    monkeypatch.setattr("sevn.infrastructure.tunnel_autostart.start_configured_tunnel", _fake_start)

    await router.route_incoming(_callback("act:tunnel:on:confirm", callback_query_id="cq-on"))

    assert _read_tunnel(root).get("autostart") is True
    assert len(calls) == 1
    assert any("Tunnel on" in (t or "") for _cq, t in cap.answered)


@pytest.mark.asyncio
async def test_tunnel_on_cancel_returns_to_menu_without_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, cap, root = _build_owner_router(tmp_path)
    _set_tunnel_mode(root, "cloudflare_quick")

    started: list[Any] = []

    async def _fake_start(**kwargs: Any) -> TunnelStatus:
        started.append(kwargs)
        return _healthy()

    monkeypatch.setattr("sevn.infrastructure.tunnel_autostart.start_configured_tunnel", _fake_start)

    await router.route_incoming(_callback("act:tunnel:on:cancel", callback_query_id="cq-cancel"))

    assert started == []
    assert "autostart" not in _read_tunnel(root)
    assert any("Cancelled" in (t or "") for _cq, t in cap.answered)


@pytest.mark.asyncio
async def test_tunnel_off_clears_autostart_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, cap, root = _build_owner_router(tmp_path)
    _set_tunnel_mode(root, "cloudflare_quick", autostart=True)

    stopped: list[Any] = []

    def _fake_stop(cfg: dict[str, Any], *, confirm: bool) -> TunnelStatus:
        stopped.append((cfg, confirm))
        return TunnelStatus(
            mode="cloudflare_quick", pid=None, healthy=False, public_url=None, error=None
        )

    from sevn.infrastructure.tunnel_manager import default_manager

    monkeypatch.setattr(default_manager, "stop", _fake_stop)

    await router.route_incoming(_callback("act:tunnel:off", callback_query_id="cq-off"))

    assert _read_tunnel(root).get("autostart") is False
    assert len(stopped) == 1
    assert any("Tunnel off" in (t or "") for _cq, t in cap.answered)


@pytest.mark.asyncio
async def test_tunnel_off_failed_stop_preserves_autostart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raising stop reports failure and leaves ``autostart=True`` (button stays "on").

    The provider may still be alive and publicly exposing the gateway, so the menu must
    not claim "off" — mirror of the confirmed-healthy ordering on the "on" path.
    """
    router, cap, root = _build_owner_router(tmp_path)
    _set_tunnel_mode(root, "cloudflare_quick", autostart=True)

    def _fake_stop(cfg: dict[str, Any], *, confirm: bool) -> TunnelStatus:
        raise RuntimeError("cloudflared refused to terminate")

    from sevn.infrastructure.tunnel_manager import default_manager

    monkeypatch.setattr(default_manager, "stop", _fake_stop)

    await router.route_incoming(_callback("act:tunnel:off", callback_query_id="cq-off-fail"))

    assert _read_tunnel(root).get("autostart") is True
    assert any("Tunnel stop failed" in (t or "") for _cq, t in cap.answered)


@pytest.mark.asyncio
async def test_tunnel_unknown_target_is_noop_and_does_not_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unexpected ``tunnel:*`` callback must no-op, not tear down a live tunnel."""
    router, _cap, root = _build_owner_router(tmp_path)
    _set_tunnel_mode(root, "cloudflare_quick", autostart=True)

    stopped: list[Any] = []

    def _fake_stop(cfg: dict[str, Any], *, confirm: bool) -> TunnelStatus:
        stopped.append((cfg, confirm))
        return TunnelStatus(
            mode="cloudflare_quick", pid=None, healthy=False, public_url=None, error=None
        )

    from sevn.infrastructure.tunnel_manager import default_manager

    monkeypatch.setattr(default_manager, "stop", _fake_stop)

    await router.route_incoming(_callback("act:tunnel:bogus", callback_query_id="cq-bogus"))

    assert stopped == []
    assert _read_tunnel(root).get("autostart") is True


@pytest.mark.asyncio
async def test_tunnel_on_failed_start_does_not_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raising start reports failure and leaves ``autostart`` unset (boot won't retry)."""
    router, cap, root = _build_owner_router(tmp_path)
    _set_tunnel_mode(root, "cloudflare_quick")

    async def _fake_start(**_kwargs: Any) -> TunnelStatus:
        raise RuntimeError("cloudflared binary not found on PATH")

    monkeypatch.setattr("sevn.infrastructure.tunnel_autostart.start_configured_tunnel", _fake_start)

    await router.route_incoming(_callback("act:tunnel:on:confirm", callback_query_id="cq-fail"))

    assert "autostart" not in _read_tunnel(root)
    assert any("Tunnel start failed" in (t or "") for _cq, t in cap.answered)


@pytest.mark.asyncio
async def test_tunnel_on_unhealthy_start_does_not_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unhealthy start reports failure and leaves ``autostart`` unset."""
    router, cap, root = _build_owner_router(tmp_path)
    _set_tunnel_mode(root, "cloudflare_quick")

    async def _fake_start(**_kwargs: Any) -> TunnelStatus:
        return TunnelStatus(
            mode="cloudflare_quick",
            pid=None,
            healthy=False,
            public_url=None,
            error="exited with code 1",
        )

    monkeypatch.setattr("sevn.infrastructure.tunnel_autostart.start_configured_tunnel", _fake_start)

    await router.route_incoming(
        _callback("act:tunnel:on:confirm", callback_query_id="cq-unhealthy")
    )

    assert "autostart" not in _read_tunnel(root)
    assert any("Tunnel start failed" in (t or "") for _cq, t in cap.answered)


@pytest.mark.asyncio
async def test_tunnel_on_unconfigured_mode_does_not_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, cap, root = _build_owner_router(tmp_path)  # no infrastructure.tunnel

    started: list[Any] = []

    async def _fake_start(**kwargs: Any) -> TunnelStatus:
        started.append(kwargs)
        return _healthy()

    monkeypatch.setattr("sevn.infrastructure.tunnel_autostart.start_configured_tunnel", _fake_start)

    await router.route_incoming(_callback("act:tunnel:on", callback_query_id="cq-none"))

    assert started == []
    assert _read_tunnel(root).get("autostart") is None
    assert any("No tunnel configured" in (t or "") for _cq, t in cap.answered)


@pytest.mark.asyncio
async def test_tunnel_on_denied_for_non_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, _cap, root = _build_owner_router(tmp_path)
    _set_tunnel_mode(root, "cloudflare_quick")

    started: list[Any] = []

    async def _fake_start(**kwargs: Any) -> TunnelStatus:
        started.append(kwargs)
        return _healthy()

    monkeypatch.setattr("sevn.infrastructure.tunnel_autostart.start_configured_tunnel", _fake_start)

    await router.route_incoming(
        _callback("act:tunnel:on", user_id="intruder", callback_query_id="cq-deny")
    )

    assert started == []
    assert "autostart" not in _read_tunnel(root)
