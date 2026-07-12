"""Linux secret service via optional ``secretstorage`` (``specs/06-secrets.md`` §3.2).
Module: sevn.security.secrets.backends.linux_secret_service
Depends: secretstorage (optional)
Exports:
    LinuxSecretServiceBackend — default collection; missing dep ⇒ ``get`` is always ``None``.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from loguru import logger

from sevn.config.defaults import DEFAULT_LINUX_SECRET_COLLECTION_LABEL

_warned_unavailable = False


class LinuxSecretServiceBackend:
    """D-Bus libsecret via ``secretstorage`` when installed."""

    def __init__(self, *, collection_label: str | None = None) -> None:
        """Configure the backend label.
        Args:
            collection_label (str | None): libsecret collection label;
                ``None`` falls back to ``DEFAULT_LINUX_SECRET_COLLECTION_LABEL``.
        Examples:
            >>> b = LinuxSecretServiceBackend()
            >>> b.__class__.__name__
            'LinuxSecretServiceBackend'
        """
        self._label = collection_label or DEFAULT_LINUX_SECRET_COLLECTION_LABEL

    def _secretstorage(self) -> Any | None:  # pragma: no cover — optional import
        """Import the optional ``secretstorage`` package or return ``None``.
        Returns:
            Any | None: Imported module when available, otherwise ``None``.
        Examples:
            >>> import inspect
            >>> "self" in inspect.signature(
            ...     LinuxSecretServiceBackend._secretstorage
            ... ).parameters
            True
        """
        import importlib.util

        if importlib.util.find_spec("secretstorage") is None:
            return None
        import secretstorage  # pyright: ignore[reportMissingImports]

        return secretstorage

    def _read_sync(self, key: str) -> str | None:
        """Read a libsecret item synchronously (used by ``get`` via to_thread).
        Args:
            key (str): Logical secret id (matched on ``sevn.logical_key`` attr).
        Returns:
            str | None: Plaintext if found, ``None`` if missing or unsupported.
        Examples:
            >>> import inspect
            >>> "key" in inspect.signature(
            ...     LinuxSecretServiceBackend._read_sync
            ... ).parameters
            True
        """
        global _warned_unavailable
        ss = self._secretstorage()
        if ss is None:
            return None
        try:
            bus = ss.dbus_init()
            collection = ss.get_default_collection(bus)
            if collection is None:
                return None
            if collection.is_locked():
                collection.unlock()
            for item in collection.search_items({"sevn.logical_key": key}):
                secret = item.get_secret()
                if secret:
                    return cast("str", secret.decode("utf-8"))
        except Exception:
            if not _warned_unavailable:
                logger.info(
                    "linux_secret_service: session DBus or libsecret unavailable; "
                    "falling back to later backends in the chain",
                )
                _warned_unavailable = True
            return None
        return None

    async def get(self, key: str) -> str | None:
        """Return plaintext for ``key`` from the default libsecret collection.
        Args:
            key (str): Logical secret id.
        Returns:
            str | None: Plaintext if the item exists and the bus is available,
                otherwise ``None``.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinuxSecretServiceBackend.get)
            True
        """
        return await asyncio.to_thread(self._read_sync, key)

    async def set(self, key: str, value: str) -> None:
        """Persist ``value`` for ``key`` in the default libsecret collection.
        Args:
            key (str): Logical secret id.
            value (str): UTF-8 plaintext to store.
        Raises:
            NotImplementedError: If ``secretstorage`` is not installed or no default
                collection is available.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinuxSecretServiceBackend.set)
            True
        """

        def _write() -> None:
            ss = self._secretstorage()
            if ss is None:
                msg = "secretstorage is not installed"
                raise NotImplementedError(msg)
            bus = ss.dbus_init()
            collection = ss.get_default_collection(bus)
            if collection is None:
                msg = "no default libsecret collection"
                raise NotImplementedError(msg)
            if collection.is_locked():
                collection.unlock()
            collection.create_item(
                f"sevn:{key}",
                {"sevn.logical_key": key, "sevn.collection": self._label},
                value.encode("utf-8"),
                replace=True,
            )

        await asyncio.to_thread(_write)

    async def delete(self, key: str) -> None:
        """Remove the libsecret item matching ``key`` if present (idempotent).
        Args:
            key (str): Logical secret id.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinuxSecretServiceBackend.delete)
            True
        """

        def _remove() -> None:
            ss = self._secretstorage()
            if ss is None:
                return
            try:
                bus = ss.dbus_init()
                collection = ss.get_default_collection(bus)
                if collection is None:
                    return
                for item in collection.search_items({"sevn.logical_key": key}):
                    item.delete()
                    return
            except Exception:
                return

        await asyncio.to_thread(_remove)
