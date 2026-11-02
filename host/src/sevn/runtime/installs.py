"""Pinned, checksummed installs of the CLI runtimes, and which copy the host runs (plan 0025 D6).

Managed copies live under ``<root>/<name>/<version>/`` with ``<root>/<name>/current`` a
symlink to the version in use. The root is ``SEVN_RUNTIMES_DIR``, else ``[runtimes] dir``,
else ``$SEVN_HOME/runtimes``. ``install`` downloads to ``<root>/.tmp``, checks the SHA-256
before anything is extracted, extracts into a staging directory under ``.tmp``, renames it
into place, and swaps ``current`` with one ``rename``.

``resolve(name)`` answers which copy the host would run: the managed ``current``, then the
copy on ``PATH`` when ``[runtimes."<name>"] use_system`` is true (the default), then, for
``claude`` only, the CLI bundled with ``claude-agent-sdk``.

Everything here is blocking file and network I/O: async callers go through
``asyncio.to_thread``. Nothing here reads the CLIs' own login directories.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import platform
import re
import shutil
import sqlite3
import stat
import sys
import tarfile
import tempfile
import tomllib
import uuid
import zipfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sevn.config import Settings
from sevn.paths import Paths
from sevn.runtime.errors import InstallError

__all__ = [
    "RUNTIMES",
    "InstallError",
    "Installed",
    "Manifest",
    "PlatformPin",
    "Resolved",
    "RuntimePin",
    "bundled_claude_path",
    "install",
    "installed",
    "load_manifest",
    "platform_key",
    "remove",
    "resolve",
    "runtimes_root",
    "use_manifest",
]

type Source = Literal["managed", "system", "bundled"]
type ArchiveFormat = Literal["raw", "tar.gz", "zip"]

#: The CLI runtimes sevn knows how to run.
RUNTIMES: tuple[str, ...] = ("claude", "opencode", "codex", "cursor-agent")

_CURRENT = "current"
_TMP = ".tmp"
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1 << 20
_TIMEOUT = httpx.Timeout(30.0, read=120.0)
_BUSY_STATUSES = ("running", "waiting")

_manifest_override: Path | None = None


# --- manifest (D5) -----------------------------------------------------------


class PlatformPin(BaseModel):
    """One runtime download for one platform."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    sha256: str = Field(pattern=_SHA256.pattern)
    binary: str
    format: ArchiveFormat
    strip_components: int = Field(default=0, ge=0)

    @field_validator("binary")
    @classmethod
    def _relative_binary(cls, value: str) -> str:
        if _member_parts(value) is None or value.endswith("/"):
            raise ValueError("binary must be a relative path inside the archive")
        return value


class RuntimePin(BaseModel):
    """The pinned version of one runtime and its per-platform downloads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(pattern=_VERSION.pattern)
    platforms: dict[str, PlatformPin]


class Manifest(BaseModel):
    """``runtime/manifest.toml``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runtimes: dict[str, RuntimePin]

    @field_validator("runtimes")
    @classmethod
    def _safe_names(cls, value: dict[str, RuntimePin]) -> dict[str, RuntimePin]:
        for name in value:
            if not _NAME.fullmatch(name):
                raise ValueError(f"invalid runtime name: {name!r}")
        return value


def use_manifest(path: Path | None) -> None:
    """Read pins from ``path`` instead of the packaged manifest; ``None`` restores it."""
    global _manifest_override
    _manifest_override = path


def load_manifest() -> Manifest:
    """The pins: the override from ``use_manifest``, else the packaged ``manifest.toml``."""
    try:
        if _manifest_override is not None:
            text = _manifest_override.read_text(encoding="utf-8")
        else:
            text = resources.files("sevn.runtime").joinpath("manifest.toml").read_text("utf-8")
        return Manifest.model_validate(tomllib.loads(text))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise InstallError("invalid_manifest", f"cannot read the runtime manifest: {exc}") from exc


def platform_key() -> str:
    """``linux-x64``, ``linux-arm64``, ``darwin-arm64`` or ``darwin-x64`` for this host."""
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    host: str = sys.platform
    system = "linux" if host.startswith("linux") else {"darwin": "darwin"}.get(host)
    if system is None or arch is None:
        raise InstallError(
            "unsupported_platform", f"managed runtimes are not available for {host} {machine}"
        )
    return f"{system}-{arch}"


# --- paths and settings ------------------------------------------------------


def _settings() -> Settings:
    return Settings.load()


def runtimes_root(settings: Settings | None = None) -> Path:
    """``SEVN_RUNTIMES_DIR``, else ``[runtimes] dir``, else ``$SEVN_HOME/runtimes``.

    A relative directory is taken relative to ``$SEVN_HOME``.
    """
    home = Paths.from_env().home
    raw = os.environ.get("SEVN_RUNTIMES_DIR", "").strip()
    if raw:
        return _anchored(Path(raw), home)
    configured = (settings or _settings()).runtimes.dir
    if configured is not None:
        return _anchored(configured, home)
    return home / "runtimes"


def _anchored(path: Path, home: Path) -> Path:
    path = path.expanduser()
    return path if path.is_absolute() else home / path


# --- resolve -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Resolved:
    """The binary the host would run for one runtime."""

    path: Path
    source: Source
    version: str | None = None


@dataclass(frozen=True, slots=True)
class Installed:
    """The managed versions of one runtime and the one ``current`` points at."""

    versions: tuple[str, ...]
    current: str | None


def bundled_claude_path() -> Path | None:
    """The Claude CLI shipped inside the ``claude-agent-sdk`` wheel, when there is one."""
    try:
        import claude_agent_sdk
    except ImportError:
        return None
    candidate = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    return candidate if candidate.is_file() else None


def resolve(name: str) -> Resolved | None:
    """The copy of ``name`` the host would run, or ``None`` when there is none."""
    if not _NAME.fullmatch(name):
        return None
    settings = _settings()
    managed = _managed_entry(runtimes_root(settings), name)
    if managed is not None:
        return managed
    if settings.runtimes.for_runtime(name).use_system:
        found = shutil.which(name)
        if found is not None and Path(found).is_absolute():
            return Resolved(Path(found), "system")
    if name == "claude":
        bundled = bundled_claude_path()
        if bundled is not None:
            return Resolved(bundled, "bundled")
    return None


def installed(name: str) -> Installed:
    """The managed versions of ``name`` under the runtimes root."""
    directory = _runtime_dir(runtimes_root(), name)
    return Installed(_versions(directory), _current_version(directory))


def _managed_entry(root: Path, name: str) -> Resolved | None:
    directory = root / name
    version = _current_version(directory)
    if version is None:
        return None
    entry = directory / version / name
    if not entry.is_file() or not os.access(entry, os.X_OK):
        return None
    return Resolved(entry, "managed", version)


def _runtime_dir(root: Path, name: str) -> Path:
    if not _NAME.fullmatch(name):
        raise InstallError("unknown_runtime", f"unknown runtime: {name}")
    return root / name


def _current_version(directory: Path) -> str | None:
    try:
        target = os.readlink(directory / _CURRENT)
    except OSError:
        return None
    version = PurePosixPath(target).name
    if not _VERSION.fullmatch(version) or version == _CURRENT:
        return None
    if not (directory / version).is_dir():
        return None
    return version


def _versions(directory: Path) -> tuple[str, ...]:
    try:
        entries = list(directory.iterdir())
    except OSError:
        return ()
    found = [
        entry.name
        for entry in entries
        if entry.name != _CURRENT
        and _VERSION.fullmatch(entry.name)
        and entry.is_dir()
        and not entry.is_symlink()
    ]
    return tuple(sorted(found, key=_version_key))


def _version_key(version: str) -> tuple[tuple[int, int, str], ...]:
    return tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"[.+-]", version)
    )


# --- install -----------------------------------------------------------------


def install(name: str, *, version: str | None = None, sha256: str | None = None) -> Path:
    """Install ``name`` and point ``current`` at it; returns ``<root>/<name>/<version>``.

    The pinned version needs no hash. Any other version needs ``sha256`` and downloads the
    pinned URL with the version replaced. A version that is already installed is not
    downloaded again; ``current`` is switched to it.
    """
    manifest = load_manifest()
    entry = manifest.runtimes.get(name)
    if entry is None:
        raise InstallError("unknown_runtime", f"unknown runtime: {name}")
    key = platform_key()
    pin = entry.platforms.get(key)
    if pin is None:
        raise InstallError("unsupported_platform", f"{name} has no pinned download for {key}")
    chosen, url, expected = _target(name, entry, pin, version, sha256)

    root = runtimes_root()
    directory = root / name
    _require_writable(root, directory)
    version_dir = directory / chosen
    if (version_dir / name).is_file():
        _switch_current(root, directory, chosen)
        return version_dir

    tmp = root / _TMP
    tmp.mkdir(parents=True, exist_ok=True)
    download = _download(url, tmp, name, chosen, expected)
    staging = Path(tempfile.mkdtemp(prefix=f"{name}-{chosen}-", dir=tmp))
    try:
        try:
            _unpack(download, staging, pin)
        finally:
            download.unlink(missing_ok=True)
        _finish_tree(staging, name, pin.binary)
        directory.mkdir(parents=True, exist_ok=True)
        try:
            staging.rename(version_dir)
        except OSError:
            # Another install of the same version won the rename; keep its copy.
            if not (version_dir / name).is_file():
                raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    _switch_current(root, directory, chosen)
    return version_dir


def _target(
    name: str, entry: RuntimePin, pin: PlatformPin, version: str | None, sha256: str | None
) -> tuple[str, str, str]:
    """``(version, url, expected sha256)`` for a request."""
    given = None if sha256 is None else sha256.strip().lower()
    if given is not None and not _SHA256.fullmatch(given):
        raise InstallError("sha256_required", "--sha256 must be 64 hexadecimal characters")
    if version is None or version == entry.version:
        if given is not None and given != pin.sha256:
            raise InstallError(
                "checksum_mismatch",
                f"checksum mismatch for {name} {entry.version}: the manifest pins "
                f"{pin.sha256}, --sha256 was {given}",
            )
        return entry.version, pin.url, pin.sha256
    if not _VERSION.fullmatch(version) or version == _CURRENT:
        raise InstallError("invalid_version", f"invalid version: {version!r}")
    if given is None:
        raise InstallError(
            "sha256_required",
            f"{name} {version} is not pinned in the manifest (pinned: {entry.version}); "
            f"pass --sha256 with the SHA-256 of its download",
        )
    parts = urlsplit(pin.url)
    url = urlunsplit(parts._replace(path=parts.path.replace(entry.version, version)))
    return version, url, given


def _download(url: str, tmp: Path, name: str, version: str, expected: str) -> Path:
    """One GET into a file under ``tmp``; the file is removed unless the hash matches."""
    handle, raw_path = tempfile.mkstemp(prefix=f"{name}-{version}-", suffix=".download", dir=tmp)
    path = Path(raw_path)
    digest = hashlib.sha256()
    try:
        with os.fdopen(handle, "wb") as out:
            try:
                with (
                    httpx.Client(follow_redirects=True, timeout=_TIMEOUT) as client,
                    client.stream("GET", url) as response,
                ):
                    if response.status_code != 200:
                        raise InstallError(
                            "download_failed",
                            f"download of {name} {version} failed: HTTP {response.status_code} "
                            f"from {url}",
                        )
                    for chunk in response.iter_bytes(_CHUNK):
                        digest.update(chunk)
                        out.write(chunk)
            except (httpx.HTTPError, OSError) as exc:
                raise InstallError(
                    "download_failed", f"download of {name} {version} failed: {exc}"
                ) from exc
        actual = digest.hexdigest()
        if actual != expected:
            raise InstallError(
                "checksum_mismatch",
                f"checksum mismatch for {name} {version}: expected {expected}, got {actual}",
            )
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def _require_writable(root: Path, *paths: Path) -> None:
    """Refuse before any download or change when the root (or a directory under it) is
    read-only, like the images' root-owned ``/opt/sevn/runtimes`` (plan 0025 D13)."""
    for path in (root, *paths):
        existing = path
        while not existing.exists() and existing.parent != existing:
            existing = existing.parent
        if not os.access(existing, os.W_OK | os.X_OK):
            raise InstallError(
                "read_only_root",
                f"the runtimes root {root} is read-only ({existing} is not writable); "
                "set SEVN_RUNTIMES_DIR or [runtimes] dir to a writable directory",
            )


def _switch_current(root: Path, directory: Path, version: str) -> None:
    """Point ``current`` at ``version`` with one rename, so it never goes missing."""
    tmp = root / _TMP
    tmp.mkdir(parents=True, exist_ok=True)
    link = tmp / f"current-{uuid.uuid4().hex}"
    os.symlink(version, link)
    try:
        os.replace(link, directory / _CURRENT)
    except BaseException:
        link.unlink(missing_ok=True)
        raise


# --- archives ----------------------------------------------------------------


def _unsafe(message: str) -> InstallError:
    return InstallError("unsafe_archive", message)


def _member_parts(name: str) -> tuple[str, ...] | None:
    """The path parts of an archive member, or ``None`` when it could leave the target."""
    if name.startswith("/") or "\\" in name or "\x00" in name:
        return None
    parts = tuple(part for part in name.split("/") if part not in ("", "."))
    if any(part == ".." for part in parts):
        return None
    return parts


def _strip(name: str, strip: int) -> str | None:
    """The member path after dropping ``strip`` leading parts; ``None`` drops the member."""
    parts = _member_parts(name)
    if parts is None:
        raise _unsafe(f"archive member escapes the install directory: {name!r}")
    kept = parts[strip:]
    return "/".join(kept) if kept else None


def _check_link(member: str, target: str) -> None:
    if target.startswith("/"):
        raise _unsafe(f"archive link points outside the install directory: {member!r}")
    joined = os.path.normpath(os.path.join(os.path.dirname(member), target))
    if joined == ".." or joined.startswith("../"):
        raise _unsafe(f"archive link points outside the install directory: {member!r}")


def _unpack(download: Path, staging: Path, pin: PlatformPin) -> None:
    try:
        match pin.format:
            case "raw":
                entry = staging / pin.binary
                entry.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(download, entry)
            case "tar.gz":
                _unpack_tar(download, staging, pin.strip_components)
            case "zip":
                _unpack_zip(download, staging, pin.strip_components)
    except (tarfile.TarError, zipfile.BadZipFile, EOFError) as exc:
        raise _unsafe(f"cannot extract the archive: {exc}") from exc


def _unpack_tar(download: Path, staging: Path, strip: int) -> None:
    with tarfile.open(download, "r:gz") as archive:
        members: list[tarfile.TarInfo] = []
        for member in archive.getmembers():
            name = _strip(member.name, strip)
            if name is None:
                continue
            if member.issym():
                _check_link(name, member.linkname)
                members.append(member.replace(name=name, deep=False))
            elif member.islnk():
                linkname = _strip(member.linkname, strip)
                if linkname is None:
                    raise _unsafe(f"archive hard link has no target: {member.name!r}")
                members.append(member.replace(name=name, linkname=linkname, deep=False))
            elif member.isfile() or member.isdir():
                members.append(member.replace(name=name, deep=False))
            else:
                raise _unsafe(f"archive member is not a file, directory or link: {member.name!r}")
        # The ``data`` filter re-checks every path and link against the target on disk.
        archive.extractall(staging, members=members, filter="data")


def _unpack_zip(download: Path, staging: Path, strip: int) -> None:
    with zipfile.ZipFile(download) as archive:
        files: list[tuple[zipfile.ZipInfo, str, int]] = []
        links: list[tuple[str, str]] = []
        for info in archive.infolist():
            name = _strip(info.filename, strip)
            if name is None:
                continue
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                target = archive.read(info).decode("utf-8")
                _check_link(name, target)
                links.append((name, target))
            elif info.is_dir():
                (staging / name).mkdir(parents=True, exist_ok=True)
            else:
                permissions = stat.S_IMODE(mode) or 0o644
                files.append((info, name, (permissions & 0o755) | 0o600))
        for info, name, permissions in files:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not _inside(target.parent, staging):
                raise _unsafe(f"archive member escapes the install directory: {name!r}")
            with archive.open(info) as source, target.open("xb") as sink:
                shutil.copyfileobj(source, sink, _CHUNK)
            target.chmod(permissions)
        # Links last, so no file above is written through a link from the archive.
        for name, target in links:
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, path)


def _inside(path: Path, root: Path) -> bool:
    real = Path(os.path.realpath(path))
    base = Path(os.path.realpath(root))
    return real == base or base in real.parents


def _finish_tree(staging: Path, name: str, binary: str) -> None:
    """Check every link stays inside, mark the entrypoint executable, alias it as ``name``."""
    for path in staging.rglob("*"):
        if path.is_symlink() and not _inside(path, staging):
            raise _unsafe(f"archive link points outside the install directory: {path.name!r}")
    entry = staging / binary
    if not _inside(entry, staging) or not entry.is_file():
        raise _unsafe(f"the download has no {binary}")
    real = Path(os.path.realpath(entry))
    real.chmod(stat.S_IMODE(real.stat().st_mode) | 0o755)
    alias = staging / name
    if binary != name and not os.path.lexists(alias):
        os.symlink(binary, alias)
    # mkdtemp makes the staging directory private; the installed tree is world-readable.
    staging.chmod(0o755)


# --- remove ------------------------------------------------------------------


def remove(name: str, *, version: str | None = None) -> None:
    """Remove one managed version, or every managed version and ``current``.

    Refuses with ``runtime_busy`` when ``current`` would go while a turn of ``name`` is
    running or waiting.
    """
    known = set(RUNTIMES) | set(load_manifest().runtimes)
    if name not in known:
        raise InstallError("unknown_runtime", f"unknown runtime: {name}")
    root = runtimes_root()
    directory = _runtime_dir(root, name)
    versions = _versions(directory)
    current = _current_version(directory)
    has_link = os.path.lexists(directory / _CURRENT)
    if version is None:
        doomed = list(versions)
        drops_current = has_link
        if not doomed and not has_link:
            raise InstallError("not_installed", f"{name} has no managed install")
    else:
        if version not in versions:
            raise InstallError("not_installed", f"{name} {version} is not installed")
        doomed = [version]
        drops_current = version == current
    _require_writable(root, directory)
    if drops_current and _busy(name):
        raise InstallError(
            "runtime_busy",
            f"cannot remove the current {name}: a {name} turn is running or waiting; "
            "try again when it ends",
        )
    if drops_current:
        (directory / _CURRENT).unlink(missing_ok=True)
    tmp = root / _TMP
    tmp.mkdir(parents=True, exist_ok=True)
    for doomed_version in doomed:
        # Move aside first, so the version disappears in one step.
        trash = tmp / f"remove-{name}-{doomed_version}-{uuid.uuid4().hex}"
        (directory / doomed_version).rename(trash)
        shutil.rmtree(trash, ignore_errors=True)
    with contextlib.suppress(OSError):
        directory.rmdir()


def _busy(name: str) -> bool:
    """Whether a turn of an agent on runtime ``name`` is running or waiting."""
    db = Paths.from_env().db
    if not db.is_file():
        return False
    query = (
        "SELECT 1 FROM turns JOIN agents ON agents.id = turns.agent_id "
        "WHERE agents.runtime = ? AND turns.status IN (?, ?) LIMIT 1"
    )
    try:
        with contextlib.closing(sqlite3.connect(db, timeout=5)) as conn:
            row = conn.execute(query, (name, *_BUSY_STATUSES)).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return False
        raise InstallError(
            "runtime_busy", f"cannot check for running {name} turns in {db}: {exc}"
        ) from exc
    except sqlite3.Error as exc:
        raise InstallError(
            "runtime_busy", f"cannot check for running {name} turns in {db}: {exc}"
        ) from exc
    return row is not None
