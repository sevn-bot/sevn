"""Seatbelt, bubblewrap, and per-bot network."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from support.botcore import arm_configured, upgrade_home

_HOSTS_MARKER = "seatbelt-marker"


async def _pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, access: str = "workspace"
) -> tuple[object, object]:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Nimbus", access=access)
    agent = await AgentService().spawn(bot.id)
    return bot, agent


def _note(workspace: object) -> str | None:
    matches = list(Path(str(workspace)).rglob("note.txt"))
    if not matches:
        return None
    return matches[0].read_text(encoding="utf-8")


def _network(home: Path, bot_id: str, value: str) -> None:
    import sqlite3

    with sqlite3.connect(home / "sevn.db") as connection:
        connection.execute("UPDATE bots SET network = ? WHERE id = ?", (value, bot_id))
        connection.commit()


class _MarkerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"network-marker"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")
async def test_shell_seatbelt_denies_home_ssh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools.shell import execute

    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "known_hosts").write_text(_HOSTS_MARKER + "\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    bot, agent = await _pair(tmp_path, monkeypatch)
    wrote = await execute(bot.id, agent.id, "printf hi > note.txt")
    assert wrote.executed is True
    assert wrote.returncode == 0
    assert _note(bot.workspace_path) == "hi"
    shown = await execute(bot.id, agent.id, 'printf %s "$HOME"')
    assert shown.stdout.strip() == str(home)
    denied = await execute(bot.id, agent.id, 'cat "$HOME/.ssh/known_hosts"')
    assert denied.executed is True
    assert denied.returncode != 0
    assert _HOSTS_MARKER not in denied.stdout
    assert _HOSTS_MARKER not in denied.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
async def test_shell_bwrap_denies_outside_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools.shell import execute

    bot, agent = await _pair(tmp_path, monkeypatch)
    outside = tmp_path / "outside" / "nope.txt"
    outside.parent.mkdir()
    wrote = await execute(bot.id, agent.id, "printf hi > note.txt")
    assert wrote.executed is True
    assert wrote.returncode == 0
    assert _note(bot.workspace_path) == "hi"
    denied = await execute(bot.id, agent.id, f"printf x > {outside}")
    assert denied.executed is True
    assert denied.returncode != 0
    assert not outside.exists()


@pytest.mark.skipif(
    sys.platform not in {"darwin", "linux"},
    reason="sandbox home masking is macOS or Linux",
)
async def test_shell_denies_sevn_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.tools.shell import execute

    bot, agent = await _pair(tmp_path, monkeypatch)
    keys = tmp_path / "keys"
    keys.mkdir(exist_ok=True)
    (keys / "marker").write_text(_HOSTS_MARKER + "\n", encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    (run / "marker").write_text(_HOSTS_MARKER + "\n", encoding="utf-8")
    for path in (keys / "marker", run / "marker"):
        shown = await execute(bot.id, agent.id, f'cat "{path}"')
        assert shown.executed is True
        assert _HOSTS_MARKER not in shown.stdout
        assert _HOSTS_MARKER not in shown.stderr


@pytest.mark.skipif(
    sys.platform not in {"darwin", "linux"},
    reason="sandbox network is macOS or Linux",
)
async def test_network_off_blocks_curl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.tools.shell import execute

    bot, agent = await _pair(tmp_path, monkeypatch)
    _network(tmp_path, str(bot.id), "off")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MarkerHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        wrote = await execute(bot.id, agent.id, "printf hi > note.txt")
        assert wrote.returncode == 0
        probed = await execute(
            bot.id,
            agent.id,
            f"curl --max-time 2 --fail-with-body http://127.0.0.1:{port}/",
        )
        assert probed.executed is True
        assert probed.returncode != 0
        assert "network-marker" not in probed.stdout
    finally:
        server.shutdown()
        thread.join(timeout=2)


async def test_shell_is_deferred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sevn.tools.shell
    from sevn.tools.registry import toolsets_for

    bot, _agent = await _pair(tmp_path, monkeypatch)
    assert sevn.tools.shell.__name__ == "sevn.tools.shell"
    eager: set[str] = set()
    deferred: set[str] = set()
    for item in toolsets_for(bot):
        eager.update(item.eager)
        deferred.update(item.deferred)
    assert "shell" in deferred
    assert "shell" not in eager


@pytest.mark.skipif(
    sys.platform not in {"darwin", "linux"},
    reason="sandbox home masking is macOS or Linux",
)
async def test_shell_denies_home_outside_the_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools.shell import execute

    home = tmp_path / "home"
    (home / ".docker").mkdir(parents=True)
    (home / ".docker" / "config.json").write_text(_HOSTS_MARKER, encoding="utf-8")
    (home / ".zsh_history").write_text(_HOSTS_MARKER, encoding="utf-8")
    (home / ".gitconfig").write_text("[user]\n\tname = Marker\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    bot, agent = await _pair(tmp_path, monkeypatch)
    for path in (home / ".docker" / "config.json", home / ".zsh_history"):
        shown = await execute(bot.id, agent.id, f'cat "{path}"')
        assert shown.executed is True
        assert shown.returncode != 0
        assert _HOSTS_MARKER not in shown.stdout
    listed = await execute(bot.id, agent.id, f'ls -a "{home}"')
    assert ".zsh_history" not in listed.stdout
    config = await execute(bot.id, agent.id, f'cat "{home / ".gitconfig"}"')
    assert "Marker" in config.stdout


def test_bwrap_argv_unshares_every_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from sevn.sandbox.bubblewrap import argv

    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".local" / "bin").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SEVN_HOME", str(tmp_path / "sevn"))
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/bwrap")
    workspace = tmp_path / "ws"
    shared = tmp_path / "Shared"
    closed = argv("true", workspace=workspace, shared=shared, network=False)
    assert "--unshare-all" in closed
    assert "--new-session" in closed
    assert "--share-net" not in closed
    home_mask = closed.index(str(home)) - 1
    assert closed[home_mask] == "--tmpfs"
    readable = str(home / ".local" / "bin")
    assert closed[closed.index(readable) - 1] == "--ro-bind"
    assert str(home / ".ssh") not in closed
    assert closed.index("--bind") > home_mask
    opened = argv("true", workspace=workspace, shared=shared, network=True)
    assert "--share-net" in opened


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
async def test_shell_bwrap_cannot_see_host_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools.shell import execute

    bot, agent = await _pair(tmp_path, monkeypatch)
    host_pid = os.getpid()
    probed = await execute(bot.id, agent.id, f"kill -0 {host_pid}; cat /proc/{host_pid}/environ")
    assert probed.executed is True
    assert probed.returncode != 0
    assert "SEVN_HOME" not in probed.stdout


async def test_shell_times_out_and_stops_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sevn.tools.shell as shell
    from sevn.tools.shell import execute, tool_output

    monkeypatch.setattr(shell, "TIMEOUT_SECONDS", 0.5)
    bot, agent = await _pair(tmp_path, monkeypatch, access="full")
    loop = asyncio.get_running_loop()
    started = loop.time()
    ran = await execute(bot.id, agent.id, "sleep 30", approved=True)
    assert loop.time() - started < 10
    assert ran.executed is True
    assert ran.timed_out is True
    assert ran.returncode != 0
    assert "timed out" in tool_output(ran)


async def test_cancelled_shell_kills_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools.shell import execute

    bot, agent = await _pair(tmp_path, monkeypatch, access="full")
    workspace = Path(str(bot.workspace_path))
    task = asyncio.create_task(
        execute(bot.id, agent.id, "echo $$ > child.pid; exec sleep 30", approved=True)
    )
    pid_file = workspace / "child.pid"
    for _ in range(200):
        if pid_file.is_file() and pid_file.read_text(encoding="utf-8").strip():
            break
        await asyncio.sleep(0.05)
    pid = int(pid_file.read_text(encoding="utf-8").strip())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


async def _wait_gone(pid: int) -> bool:
    for _ in range(100):
        if _gone(pid):
            return True
        await asyncio.sleep(0.05)
    return False


async def test_timeout_stops_children_after_the_shell_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The leader exits 0 at once; its background child must not survive the timeout."""
    import sevn.tools.shell as shell

    monkeypatch.setattr(shell, "TIMEOUT_SECONDS", 0.5)
    ran = await shell._run(  # pyright: ignore[reportPrivateUsage]
        ["/bin/sh", "-c", "sleep 30 & echo $! > child.pid; exit 0"], tmp_path, dict(os.environ)
    )
    assert ran.timed_out is True
    pid = int((tmp_path / "child.pid").read_text(encoding="utf-8").strip())
    assert await _wait_gone(pid)


async def test_timeout_kills_children_that_ignore_sigterm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SIGTERM ends the leader; a child that ignores it still gets SIGKILL.

    The child does not hold the shell's pipes, so waiting on the leader returns as
    soon as it dies, before any SIGKILL would be sent.
    """
    import sevn.tools.shell as shell

    monkeypatch.setattr(shell, "TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(shell, "_TERM_GRACE", 0.3)
    ran = await shell._run(  # pyright: ignore[reportPrivateUsage]
        [
            "/bin/sh",
            "-c",
            "(trap '' TERM; exec sleep 30 </dev/null >/dev/null 2>&1) & echo $! > child.pid; wait",
        ],
        tmp_path,
        dict(os.environ),
    )
    assert ran.timed_out is True
    pid = int((tmp_path / "child.pid").read_text(encoding="utf-8").strip())
    assert await _wait_gone(pid)


async def test_shell_caps_output_and_reports_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools.shell import OUTPUT_LIMIT, execute, tool_output

    bot, agent = await _pair(tmp_path, monkeypatch, access="full")
    big = await execute(
        bot.id, agent.id, f"head -c {OUTPUT_LIMIT * 3} /dev/zero | tr '\\0' a", approved=True
    )
    assert big.returncode == 0
    assert big.truncated is True
    assert len(big.stdout) == OUTPUT_LIMIT
    failed = await execute(bot.id, agent.id, "echo out; echo oops >&2; exit 3", approved=True)
    text = tool_output(failed)
    assert text.startswith("exit code: 3")
    assert "stdout:\nout" in text
    assert "stderr:\noops" in text


def _outside_tmp_home() -> Path | None:
    """A sevn home outside ``/tmp``, which the sandbox already hides."""
    import tempfile

    # mkdtemp makes a private 0700 directory, so the shared /var/tmp is safe here.
    root = Path("/var/tmp")  # noqa: S108
    if not root.is_dir() or not os.access(root, os.W_OK):
        return None
    return Path(tempfile.mkdtemp(prefix="sevn-sibling-", dir=root))


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
async def test_shell_cannot_read_another_bots_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService
    from sevn.tools.shell import execute

    home = _outside_tmp_home()
    if home is None:
        pytest.skip("no writable directory outside /tmp")
    try:
        arm_configured(monkeypatch, home)
        await upgrade_home(home)
        owner = await BotService().create("Owner")
        other = await BotService().create("Other")
        agent = await AgentService().spawn(other.id)
        secret = Path(owner.workspace_path) / "private.txt"
        secret.write_text(_HOSTS_MARKER, encoding="utf-8")
        shown = await execute(other.id, agent.id, f'cat "{secret}"')
        assert shown.executed is True
        assert shown.returncode != 0
        assert _HOSTS_MARKER not in shown.stdout
        listed = await execute(other.id, agent.id, f'ls "{Path(owner.workspace_path).parent}"')
        assert Path(owner.workspace_path).name not in listed.stdout
        wrote = await execute(other.id, agent.id, "printf hi > note.txt")
        assert wrote.returncode == 0
        assert _note(other.workspace_path) == "hi"
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_bwrap_argv_masks_sevn_home_and_workspaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from sevn.sandbox.bubblewrap import argv

    user_home = tmp_path / "user"
    user_home.mkdir()
    sevn_home = tmp_path / "data"
    workspaces = sevn_home / "workspaces"
    workspace = workspaces / "bot_a"
    shared = sevn_home / "Shared"
    for path in (workspace, workspaces / "bot_b", shared):
        path.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("SEVN_HOME", str(sevn_home))
    monkeypatch.setenv("SEVN_WORKSPACES", str(workspaces))
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/bwrap")
    args = argv("true", workspace=workspace, shared=shared, network=False)
    mask = args.index(str(sevn_home))
    assert args[mask - 1] == "--tmpfs"
    bind = args.index(str(workspace))
    assert args[bind - 1] == "--bind"
    assert bind > mask
    assert args.index(str(shared)) > mask


def test_bwrap_argv_masks_workspaces_outside_sevn_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from sevn.sandbox.bubblewrap import argv

    user_home = tmp_path / "user"
    user_home.mkdir()
    workspaces = tmp_path / "Sevn"
    workspace = workspaces / "bot_a"
    shared = tmp_path / "Shared"
    workspace.mkdir(parents=True)
    shared.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("SEVN_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("SEVN_WORKSPACES", str(workspaces))
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/bwrap")
    args = argv("true", workspace=workspace, shared=shared, network=False)
    mask = args.index(str(workspaces))
    assert args[mask - 1] == "--tmpfs"
    assert args.index(str(workspace)) > mask


def test_seatbelt_denies_sevn_home_and_workspaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.sandbox import seatbelt

    monkeypatch.setenv("SEVN_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("SEVN_WORKSPACES", str(tmp_path / "data" / "workspaces"))
    args = seatbelt.argv(
        "true",
        workspace=tmp_path / "data" / "workspaces" / "bot_a",
        shared=tmp_path / "data" / "Shared",
        network=False,
    )
    assert f"SEVN_HOME={tmp_path / 'data'}" in args
    assert f"SEVN_WORKSPACES={tmp_path / 'data' / 'workspaces'}" in args
    profile = Path(seatbelt.__file__).parent / "profiles" / "sevn-workspace.sb"
    text = profile.read_text(encoding="utf-8")
    home_deny = text.index('(deny file-read* (subpath (param "SEVN_HOME")))')
    workspaces_deny = text.index('(deny file-read* (subpath (param "SEVN_WORKSPACES")))')
    workspace_allow = text.index('(subpath (param "WORKSPACE"))')
    assert home_deny < workspace_allow
    assert workspaces_deny < workspace_allow


def _inside_scratch(path: str, workspace: object, agent_id: object) -> bool:
    scratch = Path(str(workspace)).resolve() / "tasks" / str(agent_id)
    return Path(path).is_relative_to(scratch)


@pytest.mark.skipif(
    sys.platform not in {"darwin", "linux"},
    reason="the workspace shell is confined on macOS or Linux",
)
async def test_workspace_shell_has_a_writable_tmpdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host TMPDIR is outside the sandbox's writable paths (read-only on
    macOS, hidden by the /tmp tmpfs on Linux), so the shell gets its own."""
    from sevn.tools.shell import execute

    host_tmp = tmp_path / "host-tmp"
    host_tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(host_tmp))
    bot, agent = await _pair(tmp_path, monkeypatch)
    shown = await execute(bot.id, agent.id, 'printf %s "$TMPDIR"')
    assert shown.returncode == 0, shown.stderr
    assert _inside_scratch(shown.stdout, bot.workspace_path, agent.id), shown.stdout
    made = await execute(bot.id, agent.id, 'f=$(mktemp) && printf ok > "$f" && cat "$f"')
    assert made.returncode == 0, made.stderr
    assert made.stdout == "ok"
