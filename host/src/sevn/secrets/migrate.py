"""``sevn secret migrate``: move every secret to another backend (plan 0025 D4).

The order is fixed so a failure never loses a secret: check the target is reachable, copy
each secret and read it back, write ``secrets.backend`` to ``config.toml``, and only then
delete the source copies. Any failure before the config write removes what was copied and
leaves the source and the config as they were. No message ever contains a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import sevn.secrets
from sevn.config import BackendName, Settings
from sevn.errors import ConfigError
from sevn.paths import Paths
from sevn.secrets.backends import EnvBackend, SecretBackend, backend_named
from sevn.secrets.errors import SecretBackendReadOnly, SecretNotFound, SecretsBackendError

type MigrationTarget = Literal["secret-service", "age-file"]

TARGETS: tuple[MigrationTarget, ...] = ("secret-service", "age-file")

#: Failures that a backend raises for one secret (never for a programming error).
_BACKEND_FAILURES = (
    SecretsBackendError,
    SecretNotFound,
    SecretBackendReadOnly,
    OSError,
    ValueError,
)


class MigrationError(Exception):
    """Migration refused or failed. ``code`` is stable; the message names secrets, never values."""

    def __init__(self, code: str, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True)
class MigrationResult:
    source: BackendName
    target: MigrationTarget
    names: tuple[str, ...]
    #: Secrets copied to the target whose source copy could not be deleted.
    leftovers: tuple[str, ...] = ()


def parse_target(raw: str) -> MigrationTarget:
    for target in TARGETS:
        if raw == target:
            return target
    raise MigrationError(
        "unsupported_target",
        f"cannot migrate to {raw}: use --to secret-service or --to age-file",
        exit_code=2,
    )


def migrate(settings: Settings, paths: Paths, raw_target: str) -> MigrationResult:
    target_name = parse_target(raw_target)
    source_name = sevn.secrets.selected_backend(settings, paths)
    if source_name == target_name:
        raise MigrationError("already_using", f"already using {target_name}")
    source = backend_named(source_name, paths)
    if isinstance(source, EnvBackend):
        raise MigrationError(
            "read_only_source", "cannot migrate from env: environment secrets are read-only"
        )
    if target_name == "secret-service":
        _require_unlocked()
    target = backend_named(target_name, paths)
    try:
        names = tuple(source.names())
    except _BACKEND_FAILURES as exc:
        raise MigrationError(
            _code(exc), f"cannot list the secrets in {source_name}: {_reason(exc)}"
        ) from exc
    try:
        existing = set(target.names())
    except _BACKEND_FAILURES as exc:
        raise MigrationError(
            _code(exc), f"cannot read {target_name}: {_reason(exc)}; nothing was copied"
        ) from exc
    undo = _Undo(target, existing)
    for name in names:
        try:
            value = source.get(name)
            undo.remember(name)
            target.set(name, value)
            matches = target.get(name) == value
        except _BACKEND_FAILURES as exc:
            undo.run()
            raise MigrationError(
                _code(exc), f"could not copy {name}: {_reason(exc)}; nothing was changed"
            ) from exc
        if not matches:
            undo.run()
            raise MigrationError(
                "verify_failed",
                f"{name} did not read back the same value from {target_name}; nothing was changed",
            )
    try:
        sevn.secrets.pin_backend(paths, target_name)
    except (ConfigError, OSError) as exc:
        undo.run()
        raise MigrationError("config_failed", f"{exc}; nothing was changed") from exc
    leftovers: list[str] = []
    for name in names:
        try:
            source.delete(name)
        except SecretNotFound:
            continue
        except _BACKEND_FAILURES:
            leftovers.append(name)
    return MigrationResult(
        source=source_name, target=target_name, names=names, leftovers=tuple(leftovers)
    )


def _require_unlocked() -> None:
    state = sevn.secrets.probe_secret_service()
    if state == "locked":
        raise MigrationError(
            "secrets_locked",
            "secrets_locked: the Secret Service collection is locked; unlock it and retry. "
            "Nothing was copied.",
        )
    if state != "unlocked":
        raise MigrationError(
            "secrets_unavailable",
            "secrets_unavailable: no Secret Service answered on the session bus. "
            "Nothing was copied.",
        )


class _Undo:
    """Puts the target back as it was: new copies are deleted, overwritten items restored."""

    def __init__(self, target: SecretBackend, existing: set[str]) -> None:
        self._target = target
        self._existing = existing
        self._touched: list[str] = []
        self._previous: dict[str, str] = {}

    def remember(self, name: str) -> None:
        """Call before writing ``name`` to the target."""
        if name in self._existing and name not in self._previous:
            self._previous[name] = self._target.get(name)
        self._touched.append(name)

    def run(self) -> None:
        for name in reversed(self._touched):
            try:
                if name in self._previous:
                    self._target.set(name, self._previous[name])
                else:
                    self._target.delete(name)
            except _BACKEND_FAILURES:
                continue


def _code(exc: Exception) -> str:
    if isinstance(exc, SecretsBackendError):
        return exc.code
    return "copy_failed"


def _reason(exc: Exception) -> str:
    """A description of ``exc`` that cannot contain a secret value."""
    if isinstance(exc, SecretsBackendError | SecretNotFound | SecretBackendReadOnly):
        return str(exc)
    return type(exc).__name__
