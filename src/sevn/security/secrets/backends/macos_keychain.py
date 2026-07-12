"""macOS Keychain via ``security`` CLI (``specs/06-secrets.md`` §3.2).

Module: sevn.security.secrets.backends.macos_keychain
Depends: asyncio, sevn.config.defaults

Exports:
    MacOSKeychainBackend — generic-password entries; no-op off Darwin.
"""

from __future__ import annotations

import asyncio
import os
import platform

from sevn.config.defaults import DEFAULT_MACOS_KEYCHAIN_SERVICE


def _keychain_disabled() -> bool:
    """Return True when host Keychain access must be suppressed (tests/CI).

    The ``security`` CLI pops an interactive access dialog on macOS. Test and CI runs
    set ``SEVN_DISABLE_KEYCHAIN`` (repo-root ``conftest.py``) so no subprocess ever
    touches the operator's real login Keychain — ``get``/``delete`` behave as off-Darwin
    no-ops and ``set`` raises like the unsupported-platform path.

    Returns:
        bool: True when ``SEVN_DISABLE_KEYCHAIN`` is truthy.

    Examples:
        >>> isinstance(_keychain_disabled(), bool)
        True
    """
    return os.environ.get("SEVN_DISABLE_KEYCHAIN", "").strip().lower() in ("1", "true", "yes")


class MacOSKeychainBackend:
    """Store one logical key per generic-password item (account=key, service=constant)."""

    def __init__(self, *, service: str | None = None) -> None:
        """Configure the Keychain service name used for generic-password entries.

        Args:
            service (str | None): Service name; ``None`` uses
                ``DEFAULT_MACOS_KEYCHAIN_SERVICE``.

        Examples:
            >>> b = MacOSKeychainBackend()
            >>> b.__class__.__name__
            'MacOSKeychainBackend'
        """
        self._service = service or DEFAULT_MACOS_KEYCHAIN_SERVICE

    def _darwin(self) -> bool:
        """Return whether the current platform is macOS.

        Returns:
            bool: True when ``platform.system() == "Darwin"``.

        Examples:
            >>> import inspect
            >>> inspect.signature(MacOSKeychainBackend._darwin).return_annotation
            'bool'
        """
        return platform.system() == "Darwin" and not _keychain_disabled()

    async def get(self, key: str) -> str | None:
        """Return plaintext for ``key`` via ``security find-generic-password``.

        Args:
            key (str): Logical secret id (used as the account field).

        Returns:
            str | None: Plaintext on success, ``None`` if missing or off-Darwin.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MacOSKeychainBackend.get)
            True
        """
        if not self._darwin():
            return None
        proc = await asyncio.create_subprocess_exec(
            "security",
            "find-generic-password",
            "-a",
            key,
            "-s",
            self._service,
            "-w",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _err = await proc.communicate()
        if proc.returncode != 0:
            return None
        return out.decode("utf-8").rstrip("\n")

    async def set(self, key: str, value: str, *, allow_any_app: bool = False) -> None:
        """Persist ``value`` for ``key`` via ``security add-generic-password -U``.

        Args:
            key (str): Logical secret id (account field).
            value (str): UTF-8 plaintext to store.
            allow_any_app (bool): When True, add ``-A`` so any application may read the item
                without a GUI trust prompt. Required for headless daemon self-unlock (the login
                keychain itself remains the lock boundary). Default keeps the restrictive ACL.

        Raises:
            NotImplementedError: If called off-Darwin (only macOS is supported).
            RuntimeError: If the ``security`` CLI returns a non-zero status.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MacOSKeychainBackend.set)
            True
        """
        if not self._darwin():
            msg = "MacOSKeychainBackend.set is only supported on macOS"
            raise NotImplementedError(msg)
        argv = [
            "security",
            "add-generic-password",
            "-a",
            key,
            "-s",
            self._service,
            "-w",
            value,
            "-U",
        ]
        if allow_any_app:
            argv.append("-A")
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _out, err = await proc.communicate()
        if proc.returncode != 0:
            detail = err.decode("utf-8", errors="replace").strip()
            msg = f"security add-generic-password failed: {detail}"
            raise RuntimeError(msg)

    async def delete(self, key: str) -> None:
        """Remove the Keychain item matching ``key`` if present (idempotent).

        Args:
            key (str): Logical secret id (account field).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MacOSKeychainBackend.delete)
            True
        """
        if not self._darwin():
            return
        proc = await asyncio.create_subprocess_exec(
            "security",
            "delete-generic-password",
            "-a",
            key,
            "-s",
            self._service,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
