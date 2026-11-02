"""In-memory stand-in for ``keyring.backends.SecretService.Keyring`` (plan 0025 D4).

It implements the keyring backend API slice ``SecretServiceBackend`` uses:
``get_password``, ``set_password`` and ``delete_password``, keyed by
``(service, username)``. Two sevn homes must not collide through this API alone.
It never touches D-Bus.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeKeyring:
    store: dict[tuple[str, str], str] = field(default_factory=dict[tuple[str, str], str])
    locked: bool = False
    # A username containing one of these names fails to store.
    fail_set: set[str] = field(default_factory=set[str])
    # A username containing one of these names reads back a different value.
    wrong_read: set[str] = field(default_factory=set[str])
    ops: list[tuple[str, str, str]] = field(default_factory=list[tuple[str, str, str]])

    def get_password(self, service: str, username: str) -> str | None:
        self._check_locked()
        self.ops.append(("get", service, username))
        value = self.store.get((service, username))
        if value is not None and _matches(username, self.wrong_read):
            return value + "-tampered"
        return value

    def set_password(self, service: str, username: str, password: str) -> None:
        import keyring.errors

        self._check_locked()
        self.ops.append(("set", service, username))
        if _matches(username, self.fail_set):
            raise keyring.errors.PasswordSetError("fake keyring refused the write")
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        import keyring.errors

        self._check_locked()
        self.ops.append(("delete", service, username))
        if (service, username) not in self.store:
            raise keyring.errors.PasswordDeleteError("not found")
        del self.store[(service, username)]

    def values(self) -> list[str]:
        return list(self.store.values())

    def _check_locked(self) -> None:
        if self.locked:
            import keyring.errors

            raise keyring.errors.KeyringLocked("Failed to unlock the collection!")


def _matches(username: str, names: set[str]) -> bool:
    return any(name in username for name in names)
