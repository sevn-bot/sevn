"""Bitwarden CLI bridge (``specs/06-secrets.md`` §3.2).

Module: sevn.security.secrets.backends.bitwarden
Depends: asyncio, json, os, shutil

Exports:
    BitwardenCliBackend — wraps ``bw`` CLI; missing CLI or session ⇒ ``get`` returns ``None``.

Live resolution requires the Bitwarden CLI (``bw``) on PATH and an unlocked session
(``BW_SESSION`` or ``bw unlock --raw``). Unit tests use fakes; no live Bitwarden vault in CI.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil

from sevn.security.secrets.errors import SecretsBackendError


class BitwardenCliBackend:
    """Resolve logical keys via the Bitwarden CLI (``bw get password`` / ``bw get item``)."""

    def __init__(
        self,
        *,
        cli_path: str | None = None,
        collection: str | None = None,
        field: str = "password",
    ) -> None:
        """Configure the Bitwarden CLI bridge.

        Args:
            cli_path (str | None): Override CLI binary; defaults to ``bw``.
            collection (str | None): Optional collection name filter (reserved for future use).
            field (str): Field name for ``bw get item … --field`` when not fetching password.

        Examples:
            >>> b = BitwardenCliBackend()
            >>> b.__class__.__name__
            'BitwardenCliBackend'
        """
        self._cli = cli_path or "bw"
        self._collection = collection
        self._field = field

    def _resolved_cli(self) -> str | None:
        """Return the absolute path of ``bw`` when present on PATH.

        Returns:
            str | None: Absolute path or ``None`` when the CLI is missing.

        Examples:
            >>> import inspect
            >>> inspect.signature(BitwardenCliBackend._resolved_cli).return_annotation
            'str | None'
        """
        return shutil.which(self._cli)

    def _subprocess_env(self) -> dict[str, str]:
        """Return a copy of ``os.environ`` for subprocess invocation.

        Returns:
            dict[str, str]: Environment passed to ``bw`` child processes.

        Examples:
            >>> isinstance(BitwardenCliBackend()._subprocess_env(), dict)
            True
        """
        return os.environ.copy()

    async def _run(self, args: list[str]) -> tuple[int, bytes, bytes]:
        """Run the CLI and return ``(returncode, stdout, stderr)``.

        Args:
            args (list[str]): Full argv including the executable path.

        Returns:
            tuple[int, bytes, bytes]: Process exit code and captured streams.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BitwardenCliBackend._run)
            True
        """
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._subprocess_env(),
        )
        out, err = await proc.communicate()
        return proc.returncode or 0, out, err

    async def get(self, key: str) -> str | None:
        """Return plaintext for ``key`` via ``bw get password`` or ``bw get item``.

        Args:
            key (str): Item name or id understood by the Bitwarden CLI.

        Returns:
            str | None: Plaintext on success; ``None`` when CLI missing or lookup fails.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BitwardenCliBackend.get)
            True
        """
        exe = self._resolved_cli()
        if exe is None:
            return None
        if not os.environ.get("BW_SESSION", "").strip():
            return None
        if self._field == "password":
            args = [exe, "get", "password", key]
        else:
            args = [exe, "get", "item", key, "--field", self._field]
        code, out, _err = await self._run(args)
        if code != 0:
            return None
        text = out.decode("utf-8").strip()
        return text or None

    async def set(self, key: str, value: str) -> None:
        """Persist ``value`` for ``key`` via ``bw create item``.

        Args:
            key (str): Item name for the new login entry.
            value (str): UTF-8 password to store.

        Raises:
            SecretsBackendError: When the CLI is missing, session is locked, or create fails.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BitwardenCliBackend.set)
            True
        """
        exe = self._resolved_cli()
        if exe is None:
            msg = "Bitwarden CLI (bw) is not installed or not on PATH"
            raise SecretsBackendError(msg)
        if not os.environ.get("BW_SESSION", "").strip():
            msg = "Bitwarden CLI requires BW_SESSION (run bw unlock --raw)"
            raise SecretsBackendError(msg)
        payload = json.dumps({"login": {"username": "", "password": value}})
        args = [exe, "encode", payload]
        code, out, _err = await self._run(args)
        if code != 0:
            msg = "Bitwarden CLI encode failed"
            raise SecretsBackendError(msg)
        encoded = out.decode("utf-8").strip()
        create_args = [exe, "create", "item", encoded, "--name", key]
        code, _out, err = await self._run(create_args)
        if code != 0:
            detail = err.decode("utf-8", errors="replace").strip()
            msg = f"Bitwarden CLI set failed (exit {code}): {detail}"
            raise SecretsBackendError(msg)

    async def delete(self, key: str) -> None:
        """Remove the item for ``key`` when present (idempotent when absent).

        Args:
            key (str): Item name to search and delete.

        Raises:
            SecretsBackendError: When the CLI is missing or session is locked.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(BitwardenCliBackend.delete)
            True
        """
        exe = self._resolved_cli()
        if exe is None:
            msg = "Bitwarden CLI (bw) is not installed or not on PATH"
            raise SecretsBackendError(msg)
        if not os.environ.get("BW_SESSION", "").strip():
            msg = "Bitwarden CLI requires BW_SESSION (run bw unlock --raw)"
            raise SecretsBackendError(msg)
        list_args = [exe, "list", "items", "--search", key]
        code, out, _err = await self._run(list_args)
        if code != 0:
            return
        try:
            items = json.loads(out.decode("utf-8"))
        except json.JSONDecodeError:
            return
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            item_id = item.get("id")
            if name == key and isinstance(item_id, str):
                del_args = [exe, "delete", "item", item_id]
                await self._run(del_args)
                return
