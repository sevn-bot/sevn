"""Pinned managed installs of the CLI runtimes (plan 0025 D5, D6, W4).

Downloads come from a local HTTP server on 127.0.0.1 that serves fake archives;
the test manifest is installed with ``sevn.runtime.installs.use_manifest(path)``.
Proxy variables point at a dead local port, so a stray request to the real
vendor URLs fails fast instead of reaching the network. ``HOME`` is a temp
directory with fake CLI credential folders that must stay untouched.
"""

from __future__ import annotations

import asyncio
import errno
import os
import secrets
import sqlite3
import stat
import subprocess
import sys
import threading
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, NoReturn

import pytest
from support.archives import cursor_tree, script, sha256, tar_gz, zip_bytes
from support.fileserver import FileServer, serve_files
from support.repo import repo_root

_RUNTIMES = ("claude", "opencode", "codex", "cursor-agent")
_PLATFORMS = ("linux-x64", "linux-arm64", "darwin-arm64", "darwin-x64")
_MANIFEST = repo_root() / "host" / "src" / "sevn" / "runtime" / "manifest.toml"
_CODEX_BIN = "codex-x86_64-unknown-linux-musl"

# W0.2 pins, copied from the plan's "W0 facts — D5 manifest pins" table.
_VERSIONS = {
    "claude": "2.1.309",
    "opencode": "1.19.5",
    "codex": "0.166.0",
    "cursor-agent": "2026.10.22-27dcf5f",
}
_FORMATS = {
    ("claude", "linux-x64"): "raw",
    ("opencode", "linux-x64"): "tar.gz",
    ("opencode", "darwin-arm64"): "zip",
    ("codex", "linux-x64"): "tar.gz",
    ("cursor-agent", "linux-x64"): "tar.gz",
}
_PINS = [
    ("claude", "linux-x64",
     "https://downloads.claude.ai/claude-code-releases/2.1.309/linux-x64/claude",
     "4d704a8aecbe038affa3000f498ae17c1b4f753add8facb8764120affc99b658"),
    ("claude", "linux-arm64",
     "https://downloads.claude.ai/claude-code-releases/2.1.309/linux-arm64/claude",
     "9796dd26899337f687739a0b39a7353b639f062a3436a7b941fcf19a1b757a9b"),
    ("claude", "darwin-arm64",
     "https://downloads.claude.ai/claude-code-releases/2.1.309/darwin-arm64/claude",
     "5eadc0009cdcdbc0d06e58110d7b2baf88ced6088b1c33a60a21217fe410619c"),
    ("claude", "darwin-x64",
     "https://downloads.claude.ai/claude-code-releases/2.1.309/darwin-x64/claude",
     "200e0d775ae55c040db3bb8db8de3e22efcddbd7e0abff5ab50dd10f6853425d"),
    ("opencode", "linux-x64",
     "https://github.com/anomalyco/opencode/releases/download/v1.19.5/opencode-linux-x64.tar.gz",
     "588310a336fa3b9df36b3f0225b26f679d453efaad0cf3d66c3651ef3ec1647a"),
    ("opencode", "linux-arm64",
     "https://github.com/anomalyco/opencode/releases/download/v1.19.5/opencode-linux-arm64.tar.gz",
     "fae5be262d693b7c5e562856cc473e59e741772936db0c0600ac0d5ed5bd088b"),
    ("opencode", "darwin-arm64",
     "https://github.com/anomalyco/opencode/releases/download/v1.19.5/opencode-darwin-arm64.zip",
     "c1c9e62521192192ef4c3ed1355ada2144055bddb61682217e997b03c55203c1"),
    ("opencode", "darwin-x64",
     "https://github.com/anomalyco/opencode/releases/download/v1.19.5/opencode-darwin-x64.zip",
     "b0212efa6db347187225a17fa3a31c6b261bf4c9f1589a290b0ca902d720d250"),
    ("codex", "linux-x64",
     "https://github.com/openai/codex/releases/download/rust-v0.166.0/"
     "codex-x86_64-unknown-linux-musl.tar.gz",
     "a0bf572d2f93f056c6712a6da348e96078dc84f3885fd7be67807ef389cb3978"),
    ("codex", "linux-arm64",
     "https://github.com/openai/codex/releases/download/rust-v0.166.0/"
     "codex-aarch64-unknown-linux-musl.tar.gz",
     "94eb707605ec2646b2e05b7edf7c4e7b3ccf02b16237c34ae9beb8cfb7f810a9"),
    ("codex", "darwin-arm64",
     "https://github.com/openai/codex/releases/download/rust-v0.166.0/"
     "codex-aarch64-apple-darwin.tar.gz",
     "c48824462fc57681eafb0925d97b11b589010475613904f570b42fea53e240d5"),
    ("codex", "darwin-x64",
     "https://github.com/openai/codex/releases/download/rust-v0.166.0/"
     "codex-x86_64-apple-darwin.tar.gz",
     "db0c38713c36199b12e7c8d1629386c35a4ce8f99e1c9ce72f1725a74df67b57"),
    ("cursor-agent", "linux-x64",
     "https://downloads.cursor.com/lab/2026.10.22-27dcf5f/linux/x64/agent-cli-package.tar.gz",
     "85296944e4600a83c4b764f578d1502bf9c416db200d33a593e8f3ecabfdc294"),
    ("cursor-agent", "linux-arm64",
     "https://downloads.cursor.com/lab/2026.10.22-27dcf5f/linux/arm64/agent-cli-package.tar.gz",
     "22a36df9720830668ccd4d707e5190204ab9c8a0efb2f068cc914895f804d3ec"),
    ("cursor-agent", "darwin-arm64",
     "https://downloads.cursor.com/lab/2026.10.22-27dcf5f/darwin/arm64/agent-cli-package.tar.gz",
     "2f5b0a3dd5fb951cecffac813867d8a08d810e59837d59fd5f12d69b922398d7"),
    ("cursor-agent", "darwin-x64",
     "https://downloads.cursor.com/lab/2026.10.22-27dcf5f/darwin/x64/agent-cli-package.tar.gz",
     "7a3cfbf0fcfb979b6213feb5f9fd10fbc7cd4e51ab28c3b572bb935e0b114961"),
]  # fmt: skip


# --- arrange -----------------------------------------------------------------


@dataclass
class Env:
    tmp: Path
    user: Path
    data: Path
    root: Path
    system_bin: Path


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    user = tmp_path / "user"
    user.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    system_bin = tmp_path / "system-bin"
    system_bin.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("SEVN_HOME", str(data))
    monkeypatch.setenv("SEVN_WORKSPACES", str(data / "workspaces"))
    monkeypatch.setenv("PATH", f"{system_bin}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.delenv("SEVN_RUNTIMES_DIR", raising=False)
    monkeypatch.delenv("SEVN_SECRETS__BACKEND", raising=False)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    # Anything that is not 127.0.0.1 goes to a dead proxy and fails fast.
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    (data / "config.toml").write_text('[secrets]\nbackend = "age-file"\n', encoding="utf-8")
    return Env(tmp_path, user, data, data / "runtimes", system_bin)


@pytest.fixture
def server(tmp_path: Path) -> Iterator[FileServer]:
    with serve_files(tmp_path / "www") as state:
        yield state


@pytest.fixture
def no_bundled_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sevn.runtime.installs.bundled_claude_path", lambda: None)


@dataclass
class Pin:
    version: str
    url: str
    sha: str
    binary: str
    fmt: str
    strip: int = 0


def _write_manifest(
    path: Path, pins: dict[str, Pin], platforms: tuple[str, ...] = _PLATFORMS
) -> Path:
    lines: list[str] = []
    for name, pin in pins.items():
        lines += [f'[runtimes."{name}"]', f'version = "{pin.version}"', ""]
        for platform in platforms:
            lines += [
                f'[runtimes."{name}".platforms."{platform}"]',
                f'url = "{pin.url}"',
                f'sha256 = "{pin.sha}"',
                f'binary = "{pin.binary}"',
                f'format = "{pin.fmt}"',
            ]
            if pin.strip:
                lines.append(f"strip_components = {pin.strip}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def use_manifest(tmp_path: Path) -> Iterator[Any]:
    from sevn.runtime import installs

    def apply(pins: dict[str, Pin], platforms: tuple[str, ...] = _PLATFORMS) -> Path:
        path = _write_manifest(tmp_path / "manifest.toml", pins, platforms)
        installs.use_manifest(path)
        return path

    try:
        yield apply
    finally:
        installs.use_manifest(None)


def _publish(server: FileServer, name: str, version: str, fmt: str) -> Pin:
    """Serve one fake runtime archive in the vendor shape for ``fmt``."""
    marker = f"{name} {version}"
    if fmt == "raw":
        data = script(marker)
        url = server.put(f"{name}/{version}/claude", data)
        return Pin(version, url, sha256(data), "claude", "raw")
    if fmt == "zip":
        data = zip_bytes({"opencode": (script(marker), 0o755)})
        url = server.put(f"{name}/v{version}/opencode.zip", data)
        return Pin(version, url, sha256(data), "opencode", "zip")
    if fmt == "tar.gz":
        data = tar_gz({_CODEX_BIN: (script(marker), 0o755)})
        url = server.put(f"{name}/rust-v{version}/codex.tar.gz", data)
        return Pin(version, url, sha256(data), _CODEX_BIN, "tar.gz")
    if fmt == "tree":
        data = tar_gz(cursor_tree(marker), top="dist-package")
        url = server.put(f"{name}/{version}/agent-cli-package.tar.gz", data)
        return Pin(version, url, sha256(data), "cursor-agent", "tar.gz", strip=1)
    raise AssertionError(fmt)


_SHAPES = {"claude": "raw", "opencode": "zip", "codex": "tar.gz", "cursor-agent": "tree"}


def _publish_all(server: FileServer, version: str = "1.0.0") -> dict[str, Pin]:
    return {name: _publish(server, name, version, shape) for name, shape in _SHAPES.items()}


def _run(path: Path) -> str:
    completed = subprocess.run(  # noqa: S603 — a fake runtime this test wrote
        [str(path)], capture_output=True, text=True, timeout=10, check=True
    )
    return completed.stdout.strip()


def _files_under(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() or p.is_symlink())


def _system_copy(env: Env, name: str) -> Path:
    path = env.system_bin / name
    path.write_bytes(script(f"system {name}"))
    path.chmod(0o755)
    return path


def _invoke(args: list[str]) -> Any:
    from sevn.cli import app
    from typer.testing import CliRunner

    return CliRunner().invoke(app, args)


def _out(result: Any) -> str:
    return f"{result.output}\n{getattr(result, 'stderr', '') or ''}"


# --- manifest (D5) -----------------------------------------------------------


def test_manifest_schema() -> None:
    data = tomllib.loads(_MANIFEST.read_text(encoding="utf-8"))
    runtimes = data["runtimes"]
    assert set(runtimes) == set(_RUNTIMES)
    for name in _RUNTIMES:
        entry = runtimes[name]
        assert isinstance(entry["version"], str) and entry["version"], name
        assert set(entry["platforms"]) == set(_PLATFORMS), name
        for platform, pin in entry["platforms"].items():
            where = f"{name} {platform}"
            assert pin["url"].startswith("https://"), where
            assert entry["version"] in pin["url"], where
            assert len(pin["sha256"]) == 64, where
            assert set(pin["sha256"]) <= set("0123456789abcdef"), where
            assert pin["binary"], where
            assert pin["format"] in {"raw", "tar.gz", "zip"}, where
            expected_strip = 1 if name == "cursor-agent" else 0
            assert pin.get("strip_components", 0) == expected_strip, where


@pytest.mark.parametrize(
    ("name", "platform", "url", "digest"), _PINS, ids=[f"{p[0]}-{p[1]}" for p in _PINS]
)
def test_manifest_pins_match_w0(name: str, platform: str, url: str, digest: str) -> None:
    data = tomllib.loads(_MANIFEST.read_text(encoding="utf-8"))
    entry = data["runtimes"][name]
    assert entry["version"] == _VERSIONS[name]
    pin = entry["platforms"][platform]
    assert pin["url"] == url
    assert pin["sha256"] == digest
    if (name, platform) in _FORMATS:
        assert pin["format"] == _FORMATS[(name, platform)]
    if name == "codex":
        triple = url.rsplit("/", 1)[1].removesuffix(".tar.gz")
        assert pin["binary"] == triple
    else:
        assert pin["binary"] == name


def test_load_manifest_reads_the_packaged_pins() -> None:
    from sevn.runtime.installs import load_manifest

    manifest = load_manifest()
    assert set(manifest.runtimes) == set(_RUNTIMES)
    claude = manifest.runtimes["claude"]
    assert claude.version == "2.1.309"
    assert claude.platforms["linux-x64"].format == "raw"
    assert claude.platforms["linux-x64"].binary == "claude"
    cursor = manifest.runtimes["cursor-agent"].platforms["darwin-arm64"]
    assert cursor.strip_components == 1
    assert manifest.runtimes["opencode"].platforms["darwin-x64"].format == "zip"


@pytest.mark.parametrize(
    ("platform", "machine", "expected"),
    [
        ("linux", "x86_64", "linux-x64"),
        ("linux", "amd64", "linux-x64"),
        ("linux", "aarch64", "linux-arm64"),
        ("linux", "arm64", "linux-arm64"),
        ("darwin", "arm64", "darwin-arm64"),
        ("darwin", "x86_64", "darwin-x64"),
    ],
)
def test_platform_key(
    monkeypatch: pytest.MonkeyPatch, platform: str, machine: str, expected: str
) -> None:
    from sevn.runtime.installs import platform_key

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr("platform.machine", lambda: machine)
    assert platform_key() == expected


@pytest.mark.parametrize(("platform", "machine"), [("linux", "riscv64"), ("win32", "AMD64")])
def test_platform_key_rejects_unsupported_hosts(
    monkeypatch: pytest.MonkeyPatch, platform: str, machine: str
) -> None:
    from sevn.runtime.installs import InstallError, platform_key

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr("platform.machine", lambda: machine)
    with pytest.raises(InstallError) as caught:
        platform_key()
    assert caught.value.code == "unsupported_platform"


# --- install (D6) ------------------------------------------------------------


@pytest.mark.parametrize("name", _RUNTIMES)
def test_install_each_vendor_shape(
    env: Env, server: FileServer, use_manifest: Any, no_bundled_claude: None, name: str
) -> None:
    from sevn.runtime.installs import install, resolve

    pins = _publish_all(server)
    use_manifest(pins)
    version_dir = install(name)
    assert version_dir == env.root / name / "1.0.0"
    entry = version_dir / pins[name].binary
    assert entry.is_file()
    assert entry.stat().st_mode & stat.S_IXUSR
    expected = "node cursor-agent 1.0.0" if name == "cursor-agent" else f"{name} 1.0.0"
    assert _run(entry) == expected
    resolved = resolve(name)
    assert resolved is not None
    assert resolved.source == "managed"
    assert resolved.version == "1.0.0"
    assert resolved.path.resolve() == entry.resolve()


def test_cursor_agent_keeps_the_whole_tree(env: Env, server: FileServer, use_manifest: Any) -> None:
    from sevn.runtime.installs import install

    use_manifest(_publish_all(server))
    version_dir = install("cursor-agent")
    assert (version_dir / "node").is_file()
    assert (version_dir / "index.js").is_file()
    assert (version_dir / "lib" / "native.node").is_file()
    assert not (version_dir / "dist-package").exists()


def test_install_verifies_sha_before_extract(
    env: Env, server: FileServer, use_manifest: Any
) -> None:
    from sevn.runtime.installs import InstallError, install

    pins = _publish_all(server)
    good = pins["codex"].sha
    pins["codex"].sha = "0" * 64
    use_manifest(pins)
    with pytest.raises(InstallError) as caught:
        install("codex")
    assert caught.value.code == "checksum_mismatch"
    message = str(caught.value)
    assert "codex" in message
    assert "0" * 64 in message
    assert good in message
    assert _files_under(env.root) == []
    assert not (env.root / "codex" / "1.0.0").exists()


def test_install_switches_current_atomically(
    env: Env, server: FileServer, use_manifest: Any, no_bundled_claude: None
) -> None:
    from sevn.runtime.installs import install, resolve

    first = _publish(server, "opencode", "1.0.0", "zip")
    use_manifest({"opencode": first})
    install("opencode")
    current = env.root / "opencode" / "current"
    assert current.is_symlink()
    assert current.resolve() == (env.root / "opencode" / "1.0.0").resolve()

    second = _publish(server, "opencode", "2.0.0", "zip")
    server.slow[second.url.removeprefix(server.base)] = 0.4
    use_manifest({"opencode": second})
    missing: list[int] = []
    stop = threading.Event()

    def watch() -> None:
        # Only ENOENT is a real absence. On APFS, stat through a symlink that a
        # rename is replacing can raise EINVAL for an instant; the link is
        # still there, so count it as present and keep watching.
        while not stop.is_set():
            try:
                os.stat(current)
            except FileNotFoundError:
                missing.append(1)
            except OSError:
                continue

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        install("opencode")
    finally:
        stop.set()
        watcher.join(timeout=5)

    assert missing == [], "current disappeared while switching versions"
    assert current.is_symlink()
    assert current.resolve() == (env.root / "opencode" / "2.0.0").resolve()
    assert (env.root / "opencode" / "1.0.0").is_dir()
    assert sorted(p.name for p in (env.root / "opencode").iterdir()) == [
        "1.0.0",
        "2.0.0",
        "current",
    ]
    resolved = resolve("opencode")
    assert resolved is not None
    assert resolved.version == "2.0.0"
    assert _run(resolved.path) == "opencode 2.0.0"
    assert _files_under(env.root / ".tmp") == []


def test_failed_upgrade_keeps_current(env: Env, server: FileServer, use_manifest: Any) -> None:
    from sevn.runtime.installs import InstallError, install

    use_manifest({"opencode": _publish(server, "opencode", "1.0.0", "zip")})
    install("opencode")
    broken = _publish(server, "opencode", "2.0.0", "zip")
    broken.sha = "f" * 64
    use_manifest({"opencode": broken})
    with pytest.raises(InstallError):
        install("opencode")
    current = env.root / "opencode" / "current"
    assert current.resolve() == (env.root / "opencode" / "1.0.0").resolve()
    assert not (env.root / "opencode" / "2.0.0").exists()


def test_unlisted_version_requires_sha256(env: Env, server: FileServer, use_manifest: Any) -> None:
    from sevn.runtime.installs import InstallError, install

    use_manifest({"opencode": _publish(server, "opencode", "1.0.0", "zip")})
    server.requests.clear()
    with pytest.raises(InstallError) as caught:
        install("opencode", version="9.9.9")
    assert caught.value.code == "sha256_required"
    assert "9.9.9" in str(caught.value)
    assert "--sha256" in str(caught.value)
    assert server.requests == []
    assert _files_under(env.root) == []


def test_unlisted_version_with_sha256_uses_the_version_url(
    env: Env, server: FileServer, use_manifest: Any
) -> None:
    from sevn.runtime.installs import install

    use_manifest({"opencode": _publish(server, "opencode", "1.0.0", "zip")})
    other = _publish(server, "opencode", "9.9.9", "zip")
    server.requests.clear()
    version_dir = install("opencode", version="9.9.9", sha256=other.sha)
    assert version_dir == env.root / "opencode" / "9.9.9"
    assert server.requests == [other.url.removeprefix(server.base)]
    assert _run(version_dir / "opencode") == "opencode 9.9.9"


def test_unlisted_version_with_a_wrong_sha256_is_refused(
    env: Env, server: FileServer, use_manifest: Any
) -> None:
    from sevn.runtime.installs import InstallError, install

    use_manifest({"opencode": _publish(server, "opencode", "1.0.0", "zip")})
    _publish(server, "opencode", "9.9.9", "zip")
    with pytest.raises(InstallError) as caught:
        install("opencode", version="9.9.9", sha256="a" * 64)
    assert caught.value.code == "checksum_mismatch"
    assert _files_under(env.root / "opencode" / "9.9.9") == []


def test_install_rejects_an_unknown_runtime(
    env: Env, server: FileServer, use_manifest: Any
) -> None:
    from sevn.runtime.installs import InstallError, install

    use_manifest(_publish_all(server))
    with pytest.raises(InstallError) as caught:
        install("nope")
    assert caught.value.code == "unknown_runtime"
    assert str(caught.value) == "unknown runtime: nope"


def test_install_rejects_a_platform_missing_from_the_manifest(
    env: Env, server: FileServer, use_manifest: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.installs import InstallError, install

    use_manifest(_publish_all(server), platforms=("linux-arm64",))
    monkeypatch.setattr("sevn.runtime.installs.platform_key", lambda: "darwin-x64")
    server.requests.clear()
    with pytest.raises(InstallError) as caught:
        install("claude")
    assert caught.value.code == "unsupported_platform"
    assert server.requests == []


def test_install_download_failure_leaves_no_files(
    env: Env, server: FileServer, use_manifest: Any
) -> None:
    from sevn.runtime.installs import InstallError, install

    pins = _publish_all(server)
    pins["claude"].url = server.url("claude/missing/claude")
    use_manifest(pins)
    with pytest.raises(InstallError) as caught:
        install("claude")
    assert caught.value.code == "download_failed"
    assert _files_under(env.root) == []


def _escape_archives(fmt: str) -> bytes:
    payload = script("escaped")
    if fmt == "tar.gz":
        return tar_gz({"opencode": (payload, 0o755), "../../escaped": (payload, 0o755)})
    return zip_bytes({"opencode": (payload, 0o755), "../../escaped": (payload, 0o755)})


@pytest.mark.parametrize("fmt", ["tar.gz", "zip"])
def test_install_rejects_archive_escape(
    env: Env, server: FileServer, use_manifest: Any, fmt: str
) -> None:
    from sevn.runtime.installs import InstallError, install

    data = _escape_archives(fmt)
    url = server.put(f"opencode/v1.0.0/evil.{fmt}", data)
    use_manifest({"opencode": Pin("1.0.0", url, sha256(data), "opencode", fmt)})
    with pytest.raises(InstallError) as caught:
        install("opencode")
    assert caught.value.code == "unsafe_archive"
    assert not (env.data / "escaped").exists()
    assert not (env.root / "escaped").exists()
    assert not (env.root / "opencode" / "1.0.0").exists()


# --- resolve (D6) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("managed", "system", "bundled", "expected"),
    [
        (True, True, True, "managed"),
        (False, True, True, "system"),
        (False, False, True, "bundled"),
        (False, False, False, None),
    ],
    ids=["managed-first", "system-next", "bundled-last", "none"],
)
def test_resolve_order(
    env: Env,
    server: FileServer,
    use_manifest: Any,
    monkeypatch: pytest.MonkeyPatch,
    managed: bool,
    system: bool,
    bundled: bool,
    expected: str | None,
) -> None:
    from sevn.runtime.installs import install, resolve

    use_manifest(_publish_all(server))
    bundled_path = env.tmp / "sdk" / "_bundled" / "claude"
    bundled_path.parent.mkdir(parents=True)
    bundled_path.write_bytes(script("bundled claude"))
    bundled_path.chmod(0o755)
    monkeypatch.setattr(
        "sevn.runtime.installs.bundled_claude_path", lambda: bundled_path if bundled else None
    )
    if managed:
        install("claude")
    if system:
        _system_copy(env, "claude")

    resolved = resolve("claude")
    if expected is None:
        assert resolved is None
        return
    assert resolved is not None
    assert resolved.source == expected
    paths = {
        "managed": env.root / "claude" / "1.0.0" / "claude",
        "system": env.system_bin / "claude",
        "bundled": bundled_path,
    }
    assert resolved.path.resolve() == paths[expected].resolve()


def test_bundled_copy_is_only_for_claude(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.runtime.installs import resolve

    bundled_path = env.tmp / "bundled-claude"
    bundled_path.write_bytes(script("bundled"))
    bundled_path.chmod(0o755)
    monkeypatch.setattr("sevn.runtime.installs.bundled_claude_path", lambda: bundled_path)
    for name in ("opencode", "codex", "cursor-agent"):
        assert resolve(name) is None, name


@pytest.mark.parametrize("name", ["opencode", "codex", "cursor-agent"])
def test_resolve_finds_each_system_copy(env: Env, name: str) -> None:
    from sevn.runtime.installs import resolve

    path = _system_copy(env, name)
    resolved = resolve(name)
    assert resolved is not None
    assert resolved.source == "system"
    assert resolved.path.resolve() == path.resolve()


def test_use_system_false_ignores_path(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.runtime.installs import resolve

    (env.data / "config.toml").write_text(
        '[secrets]\nbackend = "age-file"\n\n'
        "[runtimes.claude]\nuse_system = false\n\n"
        "[runtimes.opencode]\nuse_system = false\n\n"
        '[runtimes."cursor-agent"]\nuse_system = false\n',
        encoding="utf-8",
    )
    bundled_path = env.tmp / "bundled-claude"
    bundled_path.write_bytes(script("bundled"))
    bundled_path.chmod(0o755)
    monkeypatch.setattr("sevn.runtime.installs.bundled_claude_path", lambda: bundled_path)
    for name in ("claude", "opencode", "cursor-agent", "codex"):
        _system_copy(env, name)

    claude = resolve("claude")
    assert claude is not None
    assert claude.source == "bundled"
    assert resolve("opencode") is None
    assert resolve("cursor-agent") is None
    codex = resolve("codex")
    assert codex is not None
    assert codex.source == "system"


@pytest.mark.parametrize("how", ["env", "config"])
def test_runtimes_dir_override(
    env: Env, server: FileServer, use_manifest: Any, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    from sevn.runtime.installs import install, resolve

    target = env.tmp / "opt" / "sevn" / "runtimes"
    if how == "env":
        monkeypatch.setenv("SEVN_RUNTIMES_DIR", str(target))
    else:
        (env.data / "config.toml").write_text(
            f'[secrets]\nbackend = "age-file"\n\n[runtimes]\ndir = "{target}"\n',
            encoding="utf-8",
        )
    use_manifest(_publish_all(server))
    version_dir = install("opencode")
    assert version_dir == target / "opencode" / "1.0.0"
    assert not env.root.exists()
    resolved = resolve("opencode")
    assert resolved is not None
    assert resolved.path.resolve() == (target / "opencode" / "1.0.0" / "opencode").resolve()


def test_bundled_claude_path_points_into_the_sdk() -> None:
    import claude_agent_sdk
    from sevn.runtime.installs import bundled_claude_path

    expected = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    found = bundled_claude_path()
    if not expected.is_file():
        assert found is None
        return
    assert found is not None
    assert found.resolve() == expected.resolve()


# --- remove (D6) -------------------------------------------------------------


def _fill(conn: sqlite3.Connection, table: str, overrides: dict[str, object]) -> None:
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    row: dict[str, object] = {}
    for _cid, name, kind, notnull, default, primary in columns:
        if name in overrides:
            row[name] = overrides[name]
            continue
        if not (notnull or primary) or default is not None:
            continue
        upper = str(kind).upper()
        if "INT" in upper or "BOOL" in upper:
            row[name] = 0
        elif "DATE" in upper or "TIME" in upper:
            row[name] = "2026-11-01 00:00:00.000000"
        elif "JSON" in upper:
            row[name] = "{}"
        else:
            row[name] = f"{table}-{name}"
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", list(row.values()))  # noqa: S608 — names come from the migrated schema, values are bound


def _turn(home: Path, runtime: str, status: str) -> None:
    from support.botcore import upgrade_home

    asyncio.run(upgrade_home(home))
    with sqlite3.connect(home / "sevn.db") as conn:
        _fill(conn, "bots", {"id": "bot_1", "runtime": runtime})
        _fill(
            conn,
            "agents",
            {
                "id": "agt_1",
                "bot_id": "bot_1",
                "thread_id": "thr_1",
                "runtime": runtime,
                "status": "running",
            },
        )
        _fill(conn, "threads", {"id": "thr_1", "bot_id": "bot_1", "agent_id": "agt_1"})
        _fill(conn, "turns", {"id": "trn_1", "agent_id": "agt_1", "thread_id": "thr_1",
                              "status": status, "job_ids": "[]"})  # fmt: skip


@pytest.mark.parametrize("status", ["running", "waiting"])
def test_remove_current_refused_while_turn_runs(
    env: Env, server: FileServer, use_manifest: Any, status: str
) -> None:
    from sevn.runtime.installs import InstallError, install, remove

    use_manifest({"claude": _publish(server, "claude", "1.0.0", "raw")})
    install("claude")
    use_manifest({"claude": _publish(server, "claude", "2.0.0", "raw")})
    install("claude")
    _turn(env.data, "claude", status)

    with pytest.raises(InstallError) as caught:
        remove("claude")
    assert caught.value.code == "runtime_busy"
    assert "claude" in str(caught.value)
    with pytest.raises(InstallError):
        remove("claude", version="2.0.0")
    assert (env.root / "claude" / "current").resolve() == (env.root / "claude" / "2.0.0").resolve()


@pytest.mark.parametrize("status", ["running", "waiting"])
def test_remove_older_version_refused_while_turn_runs(
    env: Env, server: FileServer, use_manifest: Any, status: str
) -> None:
    from sevn.runtime.installs import InstallError, install, remove

    # A turn can start on 1.0.0 and still be spawning from its tree after 2.0.0 is current.
    use_manifest({"claude": _publish(server, "claude", "1.0.0", "raw")})
    install("claude")
    use_manifest({"claude": _publish(server, "claude", "2.0.0", "raw")})
    install("claude")
    _turn(env.data, "claude", status)

    with pytest.raises(InstallError) as caught:
        remove("claude", version="1.0.0")
    assert caught.value.code == "runtime_busy"
    assert "claude" in str(caught.value)
    assert (env.root / "claude" / "1.0.0").is_dir()


def test_remove_older_version_after_the_turn_ends(
    env: Env, server: FileServer, use_manifest: Any
) -> None:
    from sevn.runtime.installs import install, remove

    use_manifest({"claude": _publish(server, "claude", "1.0.0", "raw")})
    install("claude")
    use_manifest({"claude": _publish(server, "claude", "2.0.0", "raw")})
    install("claude")
    _turn(env.data, "claude", "done")

    remove("claude", version="1.0.0")
    assert not (env.root / "claude" / "1.0.0").exists()
    assert (env.root / "claude" / "current").resolve() == (env.root / "claude" / "2.0.0").resolve()


def test_remove_after_the_turn_ends(env: Env, server: FileServer, use_manifest: Any) -> None:
    from sevn.runtime.installs import install, remove, resolve

    use_manifest({"claude": _publish(server, "claude", "1.0.0", "raw")})
    install("claude")
    _turn(env.data, "claude", "done")
    remove("claude")
    assert not (env.root / "claude" / "1.0.0").exists()
    assert not os.path.lexists(env.root / "claude" / "current")
    resolved = resolve("claude")
    assert resolved is None or resolved.source != "managed"


def test_a_running_turn_of_another_runtime_does_not_block(
    env: Env, server: FileServer, use_manifest: Any
) -> None:
    from sevn.runtime.installs import install, remove

    use_manifest({"opencode": _publish(server, "opencode", "1.0.0", "zip")})
    install("opencode")
    _turn(env.data, "claude", "running")
    remove("opencode")
    assert not (env.root / "opencode" / "1.0.0").exists()


def test_remove_without_a_database_is_allowed(
    env: Env, server: FileServer, use_manifest: Any
) -> None:
    from sevn.runtime.installs import install, remove

    use_manifest({"opencode": _publish(server, "opencode", "1.0.0", "zip")})
    install("opencode")
    assert not (env.data / "sevn.db").exists()
    remove("opencode")
    assert not (env.root / "opencode" / "1.0.0").exists()


def test_remove_not_installed(env: Env) -> None:
    from sevn.runtime.installs import InstallError, remove

    with pytest.raises(InstallError) as caught:
        remove("codex")
    assert caught.value.code == "not_installed"


# --- CLI ---------------------------------------------------------------------


def test_cli_install_all_then_list(
    env: Env, server: FileServer, use_manifest: Any, no_bundled_claude: None
) -> None:
    import json

    use_manifest(_publish_all(server))
    _system_copy(env, "codex")
    installed = _invoke(["runtimes", "install", "--all"])
    assert installed.exit_code == 0, _out(installed)

    listed = _invoke(["runtimes", "list", "--json"])
    assert listed.exit_code == 0, _out(listed)
    body = json.loads(listed.stdout)
    assert set(body) == set(_RUNTIMES)
    for name in _RUNTIMES:
        assert body[name]["managed"] == ["1.0.0"], name
        assert body[name]["current"] == "1.0.0", name
        assert body[name]["used"] == "managed", name
    assert Path(body["codex"]["system"]).resolve() == (env.system_bin / "codex").resolve()
    assert body["claude"]["system"] is None


def test_cli_list_reports_unmanaged_runtimes(
    env: Env, server: FileServer, use_manifest: Any, no_bundled_claude: None
) -> None:
    import json

    use_manifest(_publish_all(server))
    _system_copy(env, "opencode")
    body = json.loads(_invoke(["runtimes", "list", "--json"]).stdout)
    assert body["opencode"] == {
        "managed": [],
        "current": None,
        "system": str(env.system_bin / "opencode"),
        "used": "system",
    }
    assert body["claude"]["used"] == "none"


def test_cli_unlisted_version_without_sha256_never_downloads(env: Env) -> None:
    # Default manifest; a download attempt would hit the dead proxy and fail differently.
    result = _invoke(["runtimes", "install", "opencode", "--version", "0.0.1-test"])
    assert result.exit_code == 1, _out(result)
    assert "--sha256" in _out(result)
    assert _files_under(env.root) == []


def test_cli_remove_refused_while_busy(env: Env, server: FileServer, use_manifest: Any) -> None:
    use_manifest({"claude": _publish(server, "claude", "1.0.0", "raw")})
    assert _invoke(["runtimes", "install", "claude"]).exit_code == 0
    _turn(env.data, "claude", "running")
    result = _invoke(["runtimes", "remove", "claude"])
    assert result.exit_code == 1, _out(result)
    assert "running" in _out(result)
    assert (env.root / "claude" / "1.0.0").is_dir()


def test_cli_checksum_failure_exits_nonzero(
    env: Env, server: FileServer, use_manifest: Any
) -> None:
    pins = _publish_all(server)
    pins["opencode"].sha = "0" * 64
    use_manifest(pins)
    result = _invoke(["runtimes", "install", "opencode"])
    assert result.exit_code == 1, _out(result)
    assert "checksum" in _out(result)
    assert _files_under(env.root) == []


# --- Claude runtime wiring (W4.2) --------------------------------------------


class _CapturingSdk:
    seen: ClassVar[list[Any]] = []

    def __init__(self, options: Any) -> None:
        _CapturingSdk.seen.append(options)

    async def connect(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def disconnect(self) -> None:
        return None


def _same_file(left: str | Path, right: Path) -> bool:
    return os.path.realpath(left) == os.path.realpath(right)


@pytest.fixture
def capturing_sdk(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    _CapturingSdk.seen = []
    monkeypatch.setattr("sevn.runtime.runtimes.claude.ClaudeSDKClient", _CapturingSdk)
    return _CapturingSdk.seen


async def test_claude_runtime_passes_cli_path(
    env: Env, server: FileServer, use_manifest: Any, capturing_sdk: list[Any]
) -> None:
    from sevn.runtime.installs import install
    from sevn.runtime.runtimes.claude import SdkClaudeClient

    use_manifest({"claude": _publish(server, "claude", "1.0.0", "raw")})
    await asyncio.to_thread(install, "claude")
    client = SdkClaudeClient()
    await client.connect(cwd=str(env.tmp))
    assert len(capturing_sdk) == 1
    cli_path = capturing_sdk[0].cli_path
    assert cli_path is not None
    assert _same_file(cli_path, env.root / "claude" / "1.0.0" / "claude")


async def test_claude_runtime_without_any_cli_leaves_cli_path_unset(
    env: Env, capturing_sdk: list[Any], no_bundled_claude: None
) -> None:
    from sevn.runtime.runtimes.claude import SdkClaudeClient

    client = SdkClaudeClient()
    await client.connect(cwd=str(env.tmp))
    assert capturing_sdk[0].cli_path is None


async def test_claude_runtime_uses_the_system_claude_when_allowed(
    env: Env, capturing_sdk: list[Any], no_bundled_claude: None
) -> None:
    from sevn.runtime.runtimes.claude import SdkClaudeClient

    system = _system_copy(env, "claude")
    await SdkClaudeClient().connect(cwd=str(env.tmp))
    assert _same_file(capturing_sdk[0].cli_path, system)


# --- credentials (global convention 12) --------------------------------------

_WATCHED: list[Path] = []
_TOUCHED: list[str] = []
_HOOKED = False


def _audit(event: str, args: tuple[object, ...]) -> None:
    if not _WATCHED or event not in {
        "open",
        "os.listdir",
        "os.scandir",
        "os.remove",
        "os.rename",
        "shutil.copyfile",
        "shutil.rmtree",
    }:
        return
    for arg in args:
        if isinstance(arg, (str, bytes, os.PathLike)):
            text = os.fsdecode(arg)
            if any(text.startswith(str(root)) for root in _WATCHED):
                _TOUCHED.append(f"{event} {text}")


def _snapshot(paths: list[Path]) -> dict[str, tuple[bytes, int]]:
    found: dict[str, tuple[bytes, int]] = {}
    for root in paths:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                found[str(path)] = (path.read_bytes(), path.stat().st_mtime_ns)
    return found


def test_install_never_touches_credential_dirs(
    env: Env, server: FileServer, use_manifest: Any
) -> None:
    global _HOOKED
    from sevn.runtime.installs import install, remove, resolve

    credential_files = {
        ".claude/.credentials.json": secrets.token_urlsafe(24),
        ".codex/auth.json": secrets.token_urlsafe(24),
        ".cursor/cli-config.json": secrets.token_urlsafe(24),
        ".local/share/opencode/auth.json": secrets.token_urlsafe(24),
    }
    for relative, token in credential_files.items():
        path = env.user / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'{{"token": "{token}"}}', encoding="utf-8")
    roots = [
        env.user / ".claude",
        env.user / ".codex",
        env.user / ".cursor",
        env.user / ".local" / "share" / "opencode",
    ]
    before = _snapshot(roots)
    if not _HOOKED:
        sys.addaudithook(_audit)
        _HOOKED = True
    use_manifest(_publish_all(server))
    _TOUCHED.clear()
    _WATCHED[:] = [root.resolve() for root in roots] + roots
    try:
        for name in _RUNTIMES:
            install(name)
            assert resolve(name) is not None
        listed = _invoke(["runtimes", "list", "--json"])
        assert listed.exit_code == 0, _out(listed)
        remove("opencode")
    finally:
        _WATCHED.clear()
    assert _TOUCHED == []
    assert _snapshot(roots) == before
    for token in credential_files.values():
        for path in _files_under(env.root):
            if path.is_file() and not path.is_symlink():
                assert token.encode() not in path.read_bytes()


# --- WV F4: a read-only runtimes root fails typed (D13) -----------------------

_needs_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions"
)


@pytest.fixture
def freeze() -> Iterator[Any]:
    """Make a tree read-only (like the image's root-owned /opt/sevn/runtimes); undo after."""
    frozen: list[Path] = []

    def apply(root: Path) -> None:
        for path in [root, *root.rglob("*")]:
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o555)
                frozen.append(path)

    try:
        yield apply
    finally:
        for path in reversed(frozen):
            path.chmod(0o755)


@_needs_non_root
def test_install_into_a_read_only_root_fails_typed(
    env: Env, server: FileServer, use_manifest: Any, freeze: Any
) -> None:
    from sevn.runtime.installs import InstallError, install

    use_manifest(_publish_all(server))
    env.root.mkdir(parents=True)
    freeze(env.root)
    server.requests.clear()
    with pytest.raises(InstallError) as caught:
        install("opencode")
    assert caught.value.code == "read_only_root"
    assert str(env.root) in str(caught.value)
    assert server.requests == [], "the root is checked before downloading"
    assert list(env.root.iterdir()) == []


@_needs_non_root
def test_remove_from_a_read_only_root_fails_typed(
    env: Env, server: FileServer, use_manifest: Any, freeze: Any
) -> None:
    from sevn.runtime.installs import InstallError, install, remove

    use_manifest(_publish_all(server))
    install("opencode")
    freeze(env.root)
    with pytest.raises(InstallError) as caught:
        remove("opencode")
    assert caught.value.code == "read_only_root"
    assert str(env.root) in str(caught.value)
    assert (env.root / "opencode" / "1.0.0" / "opencode").is_file()


@_needs_non_root
@pytest.mark.parametrize("command", ["install", "remove"])
def test_cli_reports_a_read_only_root(
    env: Env, server: FileServer, use_manifest: Any, freeze: Any, command: str
) -> None:
    from sevn.runtime.installs import install

    use_manifest(_publish_all(server))
    if command == "remove":
        install("opencode")
    else:
        env.root.mkdir(parents=True)
    freeze(env.root)
    result = _invoke(["runtimes", command, "opencode"])
    assert result.exit_code == 1, _out(result)
    assert str(env.root) in _out(result)
    assert "Traceback" not in _out(result)
    assert "PermissionError" not in _out(result)


@pytest.mark.parametrize("via_cli", [False, True], ids=["api", "cli"])
@pytest.mark.parametrize(
    ("command", "failure_point", "error_number"),
    [
        ("install", "sevn.runtime.installs.tempfile.mkdtemp", errno.ENOSPC),
        ("install", "sevn.runtime.installs._unpack", errno.ENOSPC),
        ("install", "pathlib.Path.rename", errno.EACCES),
        ("install", "sevn.runtime.installs.os.replace", errno.EACCES),
        ("remove", "pathlib.Path.rename", errno.EACCES),
        ("remove", "pathlib.Path.unlink", errno.EACCES),
    ],
    ids=["staging", "extraction", "publish", "switch", "remove-rename", "remove-link"],
)
def test_runtime_filesystem_failure_uses_typed_error(
    env: Env,
    server: FileServer,
    use_manifest: Any,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    failure_point: str,
    error_number: int,
    via_cli: bool,
) -> None:
    from sevn.runtime.installs import InstallError, install, remove

    use_manifest(_publish_all(server))
    previous = install("opencode")
    use_manifest(_publish_all(server, version="2.0.0"))
    failed_path = env.root / ".tmp" / "failed-operation"
    failure = OSError(error_number, os.strerror(error_number), str(failed_path))

    def fail(*_args: object, **_kwargs: object) -> NoReturn:
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(failure_point, fail)
        if via_cli:
            result = _invoke(["runtimes", command, "opencode"])
            assert result.exit_code == 1, _out(result)
            assert isinstance(result.exception, SystemExit), result.exception
            assert f"cannot {command} opencode" in _out(result)
            assert str(failed_path) in _out(result)
            assert "Traceback" not in _out(result)
        else:
            with pytest.raises(InstallError) as caught:
                if command == "install":
                    install("opencode")
                else:
                    remove("opencode")
            assert caught.value.code == f"{command}_failed"
            assert caught.value.__cause__ is failure
            assert str(failed_path) in caught.value.message

    # A failed upgrade never replaces the working runtime or its current link.
    # Failed removal may have unlinked current, but the version remains on disk.
    assert (previous / "opencode").is_file()
    if command == "install":
        assert (env.root / "opencode" / "current").resolve() == previous
