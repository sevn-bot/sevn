"""Unit tests for sevn.infrastructure.tunnel_manager."""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sevn.infrastructure.tunnel_manager import TunnelManager

# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


def test_status_no_process_returns_unhealthy() -> None:
    mgr = TunnelManager()
    s = mgr.status({"mode": "none"})
    assert s.healthy is False
    assert s.pid is None
    assert s.error is None
    assert s.mode == "none"


def test_status_running_process_returns_healthy() -> None:
    mgr = TunnelManager()
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 99999
    mgr._process = mock_proc  # type: ignore[assignment]

    s = mgr.status({"mode": "cloudflare", "hostname": "bot.example.com"})
    assert s.healthy is True
    assert s.pid == 99999
    assert s.public_url == "https://bot.example.com"
    assert s.mission_control_url == "https://bot.example.com/"
    assert s.error is None


def test_status_prefers_pid_file_hostname_for_quick_tunnel(tmp_path: Path) -> None:
    mgr = TunnelManager(pid_file=tmp_path / "tunnel.pid")
    mgr._pid_file.write_text(
        '{"pid": 4242, "mode": "cloudflare_quick", "hostname": "live.trycloudflare.com"}',
        encoding="utf-8",
    )
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 4242
    mgr._process = mock_proc  # type: ignore[assignment]

    s = mgr.status({"mode": "cloudflare_quick"})
    assert s.healthy is True
    assert s.mission_control_url == "https://live.trycloudflare.com/"


def test_status_exited_process_clears_and_reports_error() -> None:
    mgr = TunnelManager()
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = 1
    mock_proc.pid = 4242
    mgr._process = mock_proc  # type: ignore[assignment]

    s = mgr.status({"mode": "cloudflare"})
    assert s.healthy is False
    assert s.pid is None
    assert s.error is not None
    assert "1" in s.error
    assert mgr._process is None


def test_status_no_hostname_gives_no_public_url() -> None:
    mgr = TunnelManager()
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 12345
    mgr._process = mock_proc  # type: ignore[assignment]

    s = mgr.status({"mode": "cloudflare"})
    assert s.public_url is None


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


def test_start_requires_confirm() -> None:
    mgr = TunnelManager()
    with pytest.raises(ValueError, match="confirm=True"):
        mgr.start({"mode": "cloudflare", "token": "tok"}, confirm=False)


def test_start_rejects_unrunnable_mode() -> None:
    mgr = TunnelManager()
    with pytest.raises(ValueError, match="does not support mode"):
        mgr.start({"mode": "none"}, confirm=True)


def test_start_raises_when_binary_missing() -> None:
    mgr = TunnelManager()
    with (
        patch("shutil.which", return_value=None),
        pytest.raises(RuntimeError, match="cloudflared binary not found"),
    ):
        mgr.start({"mode": "cloudflare", "token": "tok"}, confirm=True)


def test_start_raises_without_credentials() -> None:
    mgr = TunnelManager()
    with (
        patch("shutil.which", return_value="/usr/local/bin/cloudflared"),
        pytest.raises(RuntimeError, match="config_path"),
    ):
        mgr.start({"mode": "cloudflare"}, confirm=True)


def test_start_with_token_spawns_process() -> None:
    mgr = TunnelManager()
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 42

    with (
        patch("shutil.which", return_value="/usr/local/bin/cloudflared"),
        patch("subprocess.Popen", return_value=mock_proc) as popen_mock,
    ):
        s = mgr.start({"mode": "cloudflare", "token": "mytoken"}, confirm=True)

    assert s.healthy is True
    assert s.pid == 42
    cmd = popen_mock.call_args[0][0]
    assert "cloudflared" in cmd[0]
    assert "--token" in cmd
    assert "mytoken" in cmd


def test_start_with_config_path_spawns_process() -> None:
    mgr = TunnelManager()
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 43

    with (
        patch("shutil.which", return_value="/usr/bin/cloudflared"),
        patch("subprocess.Popen", return_value=mock_proc) as popen_mock,
    ):
        s = mgr.start(
            {"mode": "cloudflare", "config_path": "/etc/cloudflared/config.yml"},
            confirm=True,
        )

    assert s.healthy is True
    cmd = popen_mock.call_args[0][0]
    assert "--config" in cmd
    assert "/etc/cloudflared/config.yml" in cmd


def test_start_noop_when_already_running() -> None:
    mgr = TunnelManager()
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 55
    mgr._process = mock_proc  # type: ignore[assignment]

    with patch("subprocess.Popen") as popen_mock:
        s = mgr.start({"mode": "cloudflare", "token": "t"}, confirm=True)

    popen_mock.assert_not_called()
    assert s.pid == 55


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


def test_stop_requires_confirm() -> None:
    mgr = TunnelManager()
    with pytest.raises(ValueError, match="confirm=True"):
        mgr.stop({"mode": "cloudflare"}, confirm=False)


def test_stop_with_no_process_is_idempotent() -> None:
    mgr = TunnelManager()
    s = mgr.stop({"mode": "none"}, confirm=True)
    assert s.healthy is False


def test_stop_terminates_running_process() -> None:
    mgr = TunnelManager()
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mgr._process = mock_proc  # type: ignore[assignment]

    s = mgr.stop({"mode": "cloudflare"}, confirm=True)

    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()
    assert mgr._process is None
    assert s.healthy is False


def test_stop_kills_on_timeout() -> None:
    mgr = TunnelManager()
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="cf", timeout=5), None]
    mgr._process = mock_proc  # type: ignore[assignment]

    mgr.stop({"mode": "cloudflare"}, confirm=True)

    mock_proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# module-level singleton
# ---------------------------------------------------------------------------


def test_default_manager_exported() -> None:
    from sevn.infrastructure.tunnel_manager import default_manager

    assert isinstance(default_manager, TunnelManager)
    assert default_manager.status({"mode": "none"}).healthy is False


# ---------------------------------------------------------------------------
# ngrok / tailscale provider command building
# ---------------------------------------------------------------------------


def test_start_ngrok_uses_authtoken_env_and_port() -> None:
    mgr = TunnelManager()
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 71

    with (
        patch("shutil.which", return_value="/usr/local/bin/ngrok"),
        patch("subprocess.Popen", return_value=mock_proc) as popen_mock,
    ):
        s = mgr.start(
            {"mode": "ngrok", "ngrok_authtoken": "ngtok", "local_port": 3005},
            confirm=True,
        )

    assert s.healthy is True
    cmd = popen_mock.call_args[0][0]
    assert cmd[0].endswith("ngrok")
    assert "http" in cmd
    assert "3005" in cmd
    env = popen_mock.call_args.kwargs["env"]
    assert env["NGROK_AUTHTOKEN"] == "ngtok"
    assert popen_mock.call_args.kwargs["stderr"] == subprocess.DEVNULL


def test_start_ngrok_requires_authtoken() -> None:
    mgr = TunnelManager()
    with (
        patch("shutil.which", return_value="/usr/local/bin/ngrok"),
        pytest.raises(RuntimeError, match="ngrok_authtoken"),
    ):
        mgr.start({"mode": "ngrok"}, confirm=True)


def test_start_tailscale_funnel_runs_background_command(tmp_path: object) -> None:
    from pathlib import Path

    pid_file = Path(str(tmp_path)) / "tunnel.pid"
    mgr = TunnelManager(pid_file=pid_file)
    completed = subprocess.CompletedProcess(args=[], returncode=0)

    with (
        patch("shutil.which", return_value="/usr/bin/tailscale"),
        patch("subprocess.run", return_value=completed) as run_mock,
    ):
        s = mgr.start({"mode": "tailscale_funnel", "local_port": 3001}, confirm=True)

    cmd = run_mock.call_args[0][0]
    assert cmd[0].endswith("tailscale")
    assert "funnel" in cmd
    assert "--bg" in cmd
    assert "3001" in cmd
    assert s.healthy is True


def test_stop_tailscale_runs_reset(tmp_path: object) -> None:
    import json
    from pathlib import Path

    pid_file = Path(str(tmp_path)) / "tunnel.pid"
    pid_file.write_text(
        json.dumps({"pid": 0, "mode": "tailscale_funnel", "hostname": ""}),
        encoding="utf-8",
    )
    mgr = TunnelManager(pid_file=pid_file)

    with (
        patch("shutil.which", return_value="/usr/bin/tailscale"),
        patch("subprocess.run") as run_mock,
    ):
        s = mgr.stop({"mode": "tailscale_funnel"}, confirm=True)

    cmd = run_mock.call_args[0][0]
    assert cmd[-2:] == ["funnel", "reset"]
    assert s.healthy is False
    assert not pid_file.exists()


def test_start_missing_binary_reports_provider() -> None:
    mgr = TunnelManager()
    with (
        patch("shutil.which", return_value=None),
        pytest.raises(RuntimeError, match="ngrok binary not found"),
    ):
        mgr.start({"mode": "ngrok", "ngrok_authtoken": "t"}, confirm=True)


# ---------------------------------------------------------------------------
# pid-file cross-process tracking
# ---------------------------------------------------------------------------


def test_pid_file_status_tracks_live_pid(tmp_path: object) -> None:
    import json
    import os
    from pathlib import Path

    pid_file = Path(str(tmp_path)) / "tunnel.pid"
    pid_file.write_text(
        json.dumps({"pid": os.getpid(), "mode": "cloudflare", "hostname": "bot.example.com"}),
        encoding="utf-8",
    )
    mgr = TunnelManager(pid_file=pid_file)
    s = mgr.status({"mode": "cloudflare", "hostname": "bot.example.com"})
    assert s.healthy is True
    assert s.pid == os.getpid()
    assert s.public_url == "https://bot.example.com"


def test_pid_file_status_clears_stale_pid(tmp_path: object) -> None:
    import json
    from pathlib import Path

    pid_file = Path(str(tmp_path)) / "tunnel.pid"
    pid_file.write_text(
        json.dumps({"pid": 2_147_483_000, "mode": "cloudflare", "hostname": ""}),
        encoding="utf-8",
    )
    mgr = TunnelManager(pid_file=pid_file)
    s = mgr.status({"mode": "cloudflare"})
    assert s.healthy is False
    assert not pid_file.exists()


def test_stop_kills_pid_file_process_when_handle_exited(tmp_path: object) -> None:
    import json
    from pathlib import Path

    live = subprocess.Popen(["sleep", "30"])
    try:
        pid_file = Path(str(tmp_path)) / "tunnel.pid"
        pid_file.write_text(
            json.dumps({"pid": live.pid, "mode": "cloudflare", "hostname": ""}),
            encoding="utf-8",
        )
        mgr = TunnelManager(pid_file=pid_file)
        # Stale in-memory handle for an already-exited process.
        stale = MagicMock(spec=subprocess.Popen)
        stale.poll.return_value = 0
        mgr._process = stale

        mgr.stop({"mode": "cloudflare"}, confirm=True)

        stale.terminate.assert_not_called()
        assert not pid_file.exists()
        # stop() must have signalled the pid-file process; wait() reaps the exit.
        try:
            rc = live.wait(timeout=5)
        except subprocess.TimeoutExpired:
            rc = None
        assert rc is not None
    finally:
        live.terminate()
        with contextlib.suppress(Exception):
            live.wait(timeout=5)


def test_start_writes_pid_file(tmp_path: object) -> None:
    import json
    from pathlib import Path

    pid_file = Path(str(tmp_path)) / "run" / "tunnel.pid"
    mgr = TunnelManager(pid_file=pid_file)
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 4242

    with (
        patch("shutil.which", return_value="/usr/local/bin/cloudflared"),
        patch("subprocess.Popen", return_value=mock_proc),
    ):
        mgr.start({"mode": "cloudflare", "token": "t", "hostname": "h.example.com"}, confirm=True)

    assert pid_file.is_file()
    data = json.loads(pid_file.read_text(encoding="utf-8"))
    assert data["pid"] == 4242
    assert data["mode"] == "cloudflare"


def test_status_unhealthy_on_mode_mismatch(tmp_path: object) -> None:
    import json
    from pathlib import Path

    live = subprocess.Popen(["sleep", "30"])
    try:
        pid_file = Path(str(tmp_path)) / "tunnel.pid"
        pid_file.write_text(
            json.dumps({"pid": live.pid, "mode": "ngrok", "hostname": "old.example.com"}),
            encoding="utf-8",
        )
        mgr = TunnelManager(pid_file=pid_file)
        s = mgr.status({"mode": "cloudflare", "hostname": "new.example.com"})
        assert s.healthy is False
        assert s.pid == live.pid
        assert s.error is not None
        assert "ngrok" in s.error
        assert "cloudflare" in s.error
    finally:
        live.terminate()
        with contextlib.suppress(Exception):
            live.wait(timeout=5)


def test_exited_handle_falls_through_to_live_pidfile(tmp_path: object) -> None:
    import json
    from pathlib import Path

    live = subprocess.Popen(["sleep", "30"])
    try:
        pid_file = Path(str(tmp_path)) / "tunnel.pid"
        pid_file.write_text(
            json.dumps({"pid": live.pid, "mode": "cloudflare", "hostname": "bot.example.com"}),
            encoding="utf-8",
        )
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = 1
        mock_proc.pid = 4242
        mgr = TunnelManager(pid_file=pid_file)
        mgr._process = mock_proc
        mgr._started_mode = "cloudflare"

        s = mgr.status({"mode": "cloudflare", "hostname": "bot.example.com"})

        assert s.healthy is True
        assert s.pid == live.pid
        assert s.public_url == "https://bot.example.com"
        assert s.error is None
        assert mgr._process is None
    finally:
        live.terminate()
        with contextlib.suppress(Exception):
            live.wait(timeout=5)


def test_exited_in_memory_process_clears_pidfile(tmp_path: object) -> None:
    import json
    from pathlib import Path

    pid_file = Path(str(tmp_path)) / "tunnel.pid"
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = 1
    mock_proc.pid = 4242
    pid_file.write_text(
        json.dumps({"pid": 4242, "mode": "cloudflare", "hostname": ""}),
        encoding="utf-8",
    )
    mgr = TunnelManager(pid_file=pid_file)
    mgr._process = mock_proc
    mgr._started_mode = "cloudflare"

    s = mgr.status({"mode": "cloudflare"})

    assert s.healthy is False
    assert s.error is not None
    assert not pid_file.exists()


def test_start_stops_tailscale_marker_when_switching_mode(tmp_path: object) -> None:
    import json
    from pathlib import Path

    pid_file = Path(str(tmp_path)) / "tunnel.pid"
    pid_file.write_text(
        json.dumps({"pid": 0, "mode": "tailscale_funnel", "hostname": ""}),
        encoding="utf-8",
    )
    mgr = TunnelManager(pid_file=pid_file)
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 5151

    with (
        patch("sevn.infrastructure.tunnel_manager._run_tailscale_stop") as tailscale_stop,
        patch("shutil.which", return_value="/usr/local/bin/cloudflared"),
        patch("subprocess.Popen", return_value=mock_proc),
    ):
        mgr.start(
            {"mode": "cloudflare", "token": "t", "hostname": "h.example.com"},
            confirm=True,
        )

    tailscale_stop.assert_called_once_with("tailscale_funnel")
    data = json.loads(pid_file.read_text(encoding="utf-8"))
    assert data["mode"] == "cloudflare"


def test_start_stops_pidfile_tunnel_when_in_memory_mode_mismatch(tmp_path: object) -> None:
    import json
    from pathlib import Path

    pid_file = Path(str(tmp_path)) / "tunnel.pid"
    pid_file.write_text(
        json.dumps({"pid": 0, "mode": "tailscale_funnel", "hostname": ""}),
        encoding="utf-8",
    )
    mgr = TunnelManager(pid_file=pid_file)
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 4242
    mgr._process = mock_proc
    mgr._started_mode = "ngrok"
    replacement = MagicMock(spec=subprocess.Popen)
    replacement.poll.return_value = None
    replacement.pid = 5151

    with (
        patch("sevn.infrastructure.tunnel_manager._run_tailscale_stop") as tailscale_stop,
        patch("shutil.which", return_value="/usr/local/bin/cloudflared"),
        patch("subprocess.Popen", return_value=replacement),
    ):
        mgr.start(
            {"mode": "cloudflare", "token": "t", "hostname": "h.example.com"},
            confirm=True,
        )

    tailscale_stop.assert_called_once_with("tailscale_funnel")
    data = json.loads(pid_file.read_text(encoding="utf-8"))
    assert data["mode"] == "cloudflare"


def test_start_stops_orphan_pidfile_when_in_memory_already_running(tmp_path: object) -> None:
    import json
    from pathlib import Path

    pid_file = Path(str(tmp_path)) / "tunnel.pid"
    pid_file.write_text(
        json.dumps({"pid": 0, "mode": "tailscale_serve", "hostname": ""}),
        encoding="utf-8",
    )
    mgr = TunnelManager(pid_file=pid_file)
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 4242
    mgr._process = mock_proc
    mgr._started_mode = "cloudflare"

    with (
        patch("sevn.infrastructure.tunnel_manager._run_tailscale_stop") as tailscale_stop,
        patch("subprocess.Popen") as popen_mock,
    ):
        mgr.start(
            {"mode": "cloudflare", "token": "t", "hostname": "h.example.com"},
            confirm=True,
        )

    tailscale_stop.assert_called_once_with("tailscale_serve")
    popen_mock.assert_not_called()
    assert not pid_file.exists()


def test_stop_uses_pidfile_tailscale_mode_not_config(tmp_path: object) -> None:
    import json
    from pathlib import Path

    pid_file = Path(str(tmp_path)) / "tunnel.pid"
    pid_file.write_text(
        json.dumps({"pid": 0, "mode": "tailscale_serve", "hostname": ""}),
        encoding="utf-8",
    )
    mgr = TunnelManager(pid_file=pid_file)

    with patch("sevn.infrastructure.tunnel_manager._run_tailscale_stop") as tailscale_stop:
        mgr.stop({"mode": "cloudflare"}, confirm=True)

    tailscale_stop.assert_called_once_with("tailscale_serve")
    assert not pid_file.exists()


def test_start_replaces_tunnel_when_mode_mismatch(tmp_path: object) -> None:
    import json
    from pathlib import Path

    live = subprocess.Popen(["sleep", "30"])
    try:
        pid_file = Path(str(tmp_path)) / "tunnel.pid"
        pid_file.write_text(
            json.dumps({"pid": live.pid, "mode": "ngrok", "hostname": ""}),
            encoding="utf-8",
        )
        mgr = TunnelManager(pid_file=pid_file)
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = None
        mock_proc.pid = 5151

        with (
            patch("shutil.which", return_value="/usr/local/bin/cloudflared"),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            mgr.start(
                {"mode": "cloudflare", "token": "t", "hostname": "h.example.com"}, confirm=True
            )

        try:
            rc = live.wait(timeout=5)
        except subprocess.TimeoutExpired:
            rc = None
        assert rc is not None
        data = json.loads(pid_file.read_text(encoding="utf-8"))
        assert data["pid"] == 5151
        assert data["mode"] == "cloudflare"
    finally:
        live.terminate()
        with contextlib.suppress(Exception):
            live.wait(timeout=5)


def test_start_fails_when_pid_file_not_writable(tmp_path: object) -> None:
    from pathlib import Path

    pid_file = Path(str(tmp_path)) / "tunnel.pid"
    pid_file.mkdir()
    mgr = TunnelManager(pid_file=pid_file)
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 6161

    with (
        patch("shutil.which", return_value="/usr/local/bin/cloudflared"),
        patch("subprocess.Popen", return_value=mock_proc),
        pytest.raises(RuntimeError, match="pid file"),
    ):
        mgr.start({"mode": "cloudflare", "token": "t"}, confirm=True)

    mock_proc.terminate.assert_called_once()
    assert mgr._process is None
