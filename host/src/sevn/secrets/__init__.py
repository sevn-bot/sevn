"""Secret storage and the redaction registry.

This module holds the backend selection the host and the CLI share (plan 0025 D4) and the
Secret Service probe behind it. It must not import :mod:`sevn.secrets.backends` at import time:
the backends import the selection from here.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
import tempfile
import threading
import tomllib
from pathlib import Path
from typing import Literal, cast

from sevn.config import BackendName, Settings
from sevn.errors import ConfigError
from sevn.paths import Paths

type ProbeState = Literal["unlocked", "locked", "unavailable"]

#: How long the Secret Service probe may take before it counts as unavailable.
PROBE_TIMEOUT = 2.0


def probe_secret_service(timeout: float = PROBE_TIMEOUT) -> ProbeState:
    """Whether the default Secret Service collection is reachable and unlocked.

    Talks to ``secretstorage`` directly: ``keyring`` unlocks the collection on access, which
    on a desktop opens a prompt and blocks until it is answered (plan 0025 W0.4). The probe
    only reads ``Collection.is_locked()``, never unlocks, and gives up after ``timeout``
    seconds. Any failure (no bus, a stale socket, no daemon, no ``secretstorage``) is
    ``unavailable``. It never raises.
    """
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS", "") == "":
        return "unavailable"
    outcome: list[ProbeState] = []

    def work() -> None:
        outcome.append(_read_collection_state())

    thread = threading.Thread(target=work, name="sevn-secret-service-probe", daemon=True)
    thread.start()
    thread.join(max(timeout, 0.0))
    return outcome[0] if outcome else "unavailable"


def _read_collection_state() -> ProbeState:
    try:
        secretstorage = importlib.import_module("secretstorage")
    except ImportError:
        return "unavailable"
    try:
        connection = secretstorage.dbus_init()
    except Exception:  # noqa: BLE001 — OSError, D-Bus and secretstorage errors all mean "unavailable"
        return "unavailable"
    try:
        locked = bool(secretstorage.Collection(connection).is_locked())
    except Exception:  # noqa: BLE001 — a probe never raises; any D-Bus error is "unavailable"
        return "unavailable"
    finally:
        _close(connection)
    return "locked" if locked else "unlocked"


def _close(connection: object) -> None:
    close = getattr(connection, "close", None)
    if callable(close):
        try:
            close()
        except OSError:
            return


def selected_backend(settings: Settings, paths: Paths) -> BackendName:
    """The secret backend this host uses (plan 0025 D4).

    A configured ``secrets.backend`` always wins. Otherwise: macOS uses the Keychain; Linux
    keeps an existing ``secrets.age`` (existing secrets never move silently); Linux with a
    session bus and an unlocked collection uses the Secret Service; everything else uses
    the age file.
    """
    configured = settings.secrets.backend
    if configured is not None:
        return configured
    if sys.platform == "darwin":
        return "keychain"
    if not sys.platform.startswith("linux"):
        return "age-file"
    if paths.secrets_file.is_file():
        return "age-file"
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS", "") == "":
        return "age-file"
    if probe_secret_service() == "unlocked":
        return "secret-service"
    return "age-file"


_TABLE = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(?:#.*)?$")
_ARRAY_TABLE = re.compile(r"^\s*\[\[")
_BACKEND_KEY = re.compile(r"^(\s*)backend\s*=")
_DOTTED_KEY = re.compile(r"^(\s*)secrets\s*\.\s*backend\s*=")


def pin_backend(paths: Paths, backend: BackendName) -> Path:
    """Write ``[secrets] backend = "<backend>"`` to ``config.toml``, keeping every other key.

    Raises :class:`ConfigError` when the file cannot be parsed or the edit does not produce
    the expected value; the file is then left as it was.
    """
    path = paths.home / "config.toml"
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        original = ""
    try:
        tomllib.loads(original)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config.toml: {exc}") from exc
    updated = _with_backend(original, backend)
    try:
        parsed = tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(_pin_hint(path, backend)) from exc
    section: object = parsed.get("secrets")
    if (
        not isinstance(section, dict)
        or cast("dict[str, object]", section).get("backend") != backend
    ):
        raise ConfigError(_pin_hint(path, backend))
    _write_text(path, updated)
    return path


def _pin_hint(path: Path, backend: str) -> str:
    return f'edit {path} by hand: under [secrets], add backend = "{backend}"'


def _with_backend(text: str, backend: str) -> str:
    lines = text.splitlines(keepends=True)
    value = f'"{backend}"'
    table: str | None = None
    header_at: int | None = None
    for index, line in enumerate(lines):
        if _ARRAY_TABLE.match(line):
            table = None
            continue
        header = _TABLE.match(line)
        if header is not None:
            table = header.group(1).replace(" ", "")
            if table == "secrets":
                header_at = index
            continue
        eol = "\n" if line.endswith("\n") else ""
        if table == "secrets" and (match := _BACKEND_KEY.match(line)):
            lines[index] = f"{match.group(1)}backend = {value}{eol}"
            return "".join(lines)
        if table is None and (match := _DOTTED_KEY.match(line)):
            lines[index] = f"{match.group(1)}secrets.backend = {value}{eol}"
            return "".join(lines)
    if header_at is not None:
        lines.insert(header_at + 1, f"backend = {value}\n")
        return "".join(lines)
    prefix = "".join(lines)
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix:
        prefix += "\n"
    return f"{prefix}[secrets]\nbackend = {value}\n"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    descriptor, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
