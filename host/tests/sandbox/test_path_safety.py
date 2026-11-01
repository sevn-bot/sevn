"""Host-side operations must not trust paths writable by confined agents."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from sevn.domain.agents import AgentService
from sevn.domain.bots import BotService
from sevn.domain.errors import DomainError
from sevn.sandbox.seatbelt import install_shims
from support.botcore import arm_configured, upgrade_home


@pytest.mark.parametrize("poison", ["file", "parent", "hardlink"])
def test_shim_install_refuses_outside_links(tmp_path: Path, poison: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "mktemp"
    victim.write_text("preserve this fixture", encoding="utf-8")
    victim.chmod(0o600)
    folder = tmp_path / "workspace" / ".bin"
    folder.parent.mkdir()
    if poison == "parent":
        folder.symlink_to(outside, target_is_directory=True)
    else:
        folder.mkdir()
        if poison == "file":
            (folder / "mktemp").symlink_to(victim)
        else:
            os.link(victim, folder / "mktemp")
    with pytest.raises(DomainError, match="path is outside the workspace") as caught:
        install_shims(folder)
    assert caught.value.code == "path_outside_workspace"
    assert victim.read_text(encoding="utf-8") == "preserve this fixture"
    assert victim.stat().st_mode & 0o777 == 0o600


async def test_file_write_refuses_parent_swapped_during_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools import files

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    agent = await AgentService().spawn(bot.id)
    parent = Path(bot.workspace_path) / "data"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "note.txt"
    victim.write_text("preserve", encoding="utf-8")

    async def swap(_agent: str, _path: str) -> None:
        parent.rmdir()
        parent.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(files, "acquire_write", swap)
    with pytest.raises(DomainError, match="path is outside the workspace") as caught:
        await files.write_file(bot.id, agent.id, "data/note.txt", "overwritten")
    assert caught.value.code == "path_outside_workspace"
    assert victim.read_text(encoding="utf-8") == "preserve"


async def test_worktree_symlink_cannot_become_tool_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.session import open_session
    from sevn.store.models import Agent
    from sevn.tools.files import read_file
    from support.canary import canary

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    agent = await AgentService().spawn(bot.id)
    workspace = Path(bot.workspace_path)
    (workspace / ".git").mkdir()
    outside = tmp_path / "outside"
    (outside / ".git").mkdir(parents=True)
    root = tmp_path / "worktrees" / agent.id
    root.parent.mkdir(parents=True)
    root.symlink_to(outside, target_is_directory=True)
    async with open_session() as session:
        row = await session.get(Agent, agent.id)
        assert row is not None
        row.isolation = "worktree"
        await session.commit()
    with canary() as secret:
        (outside / "note.txt").write_text(secret.value, encoding="utf-8")
        with pytest.raises(DomainError, match="path is outside the workspace") as caught:
            await read_file(bot.id, agent.id, "note.txt")
        assert caught.value.code == "path_outside_workspace"
        secret.assert_absent(secret.value)


def test_bubblewrap_masks_host_socket_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from sevn.sandbox.bubblewrap import argv

    monkeypatch.setenv("SEVN_HOME", str(tmp_path / "host"))
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/bwrap")
    original = Path.is_dir
    monkeypatch.setattr(
        Path, "is_dir", lambda path: str(path) in {"/run", "/var/run"} or original(path)
    )
    command = argv("true", workspace=tmp_path / "ws", shared=tmp_path / "shared", network=False)
    for root in (Path("/run"), Path("/var/run")):
        assert any(
            command[i : i + 2] == ["--tmpfs", str(root.resolve())] for i in range(len(command) - 1)
        )


async def test_worktree_shell_cannot_change_host_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil
    import subprocess
    import sys

    from sevn.domain.session import open_session
    from sevn.store.models import Agent
    from sevn.tools.shell import execute

    if sys.platform == "linux" and shutil.which("bwrap") is None:
        pytest.skip("bubblewrap is not installed")
    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    agent = await AgentService().spawn(bot.id)
    root = tmp_path / "worktrees" / agent.id
    root.parent.mkdir(parents=True)
    for args in (
        ["init"],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        ["worktree", "add", "-b", "fixture", str(root)],
    ):
        await asyncio.to_thread(
            subprocess.run, ["git", *args], cwd=bot.workspace_path, check=True, capture_output=True
        )

    async with open_session() as session:
        row = await session.get(Agent, agent.id)
        assert row is not None
        row.isolation = "worktree"
        await session.commit()
    marker = root.parent / "marker"
    marker.write_text("preserve host parent", encoding="utf-8")
    await execute(bot.id, agent.id, "printf changed > ../marker")
    # Seatbelt refuses this write; bubblewrap may write to its private tmpfs.
    # Neither may change the real parent that controls the checkout root.
    assert marker.read_text(encoding="utf-8") == "preserve host parent"
    allowed = await execute(bot.id, agent.id, "printf ok > note.txt")
    assert allowed.returncode == 0, allowed.stderr
    assert (root / "note.txt").read_text(encoding="utf-8") == "ok"


async def test_scratch_creation_refuses_replaced_tasks_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.workspace import make_scratch

    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tasks").symlink_to(outside, target_is_directory=True)
    with pytest.raises(DomainError, match="path is outside the workspace") as caught:
        await make_scratch(workspace, "agent_fixture")
    assert caught.value.code == "path_outside_workspace"
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("network", [False, True])
def test_bubblewrap_restores_only_resolver_file_after_runtime_mask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, network: bool
) -> None:
    import shutil

    from sevn.sandbox import bubblewrap

    runtime = tmp_path / "run"
    resolver = runtime / "systemd" / "resolve" / "stub-resolv.conf"
    resolver.parent.mkdir(parents=True)
    resolver.write_text("nameserver 127.0.0.53\n", encoding="utf-8")
    config = tmp_path / "resolv.conf"
    config.symlink_to(resolver)
    monkeypatch.setattr(bubblewrap, "_RUNTIME_DIRS", (runtime,))
    monkeypatch.setattr(bubblewrap, "_RESOLV_CONF", config)
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/bwrap")
    monkeypatch.setenv("SEVN_HOME", str(tmp_path / "host"))
    args = bubblewrap.argv(
        "true", workspace=tmp_path / "ws", shared=tmp_path / "shared", network=network
    )
    rebind = ["--ro-bind", str(resolver), str(resolver)]
    indexes = [i for i in range(len(args)) if args[i : i + 3] == rebind]
    assert bool(indexes) is network
    if network:
        masks = [i for i in range(len(args)) if args[i : i + 2] == ["--tmpfs", str(runtime)]]
        assert masks and masks[0] < indexes[0]
        assert ["--bind", str(runtime), str(runtime)] not in [
            args[i : i + 3] for i in range(len(args))
        ]


async def test_linux_network_shell_reads_resolver_without_runtime_neighbors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shlex
    import shutil
    import sys

    from sevn.sandbox import bubblewrap
    from sevn.tools.shell import execute

    if sys.platform != "linux" or shutil.which("bwrap") is None:
        pytest.skip("requires Linux bubblewrap")
    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    await BotService().update(bot.id, network="on", fields={"network"})
    agent = await AgentService().spawn(bot.id)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    resolver = runtime / "resolv.conf"
    resolver.write_text("nameserver 127.0.0.53\n", encoding="utf-8")
    neighbor = runtime / "host-service"
    neighbor.write_text("must stay hidden", encoding="utf-8")
    config = tmp_path / "resolver-link"
    config.symlink_to(resolver)
    monkeypatch.setattr(bubblewrap, "_RUNTIME_DIRS", (runtime,))
    monkeypatch.setattr(bubblewrap, "_RESOLV_CONF", config)
    result = await execute(
        bot.id,
        agent.id,
        f"cat {shlex.quote(str(resolver))} && test ! -e {shlex.quote(str(neighbor))}",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "nameserver 127.0.0.53\n"
