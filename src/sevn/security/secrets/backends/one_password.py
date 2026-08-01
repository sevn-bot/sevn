"""1Password CLI bridge (``specs/06-secrets.md`` §3.2).

Module: sevn.security.secrets.backends.one_password
Depends: asyncio, os, shutil

Exports:
    OnePasswordCliBackend — wraps ``op`` CLI; missing CLI or auth ⇒ ``get`` returns ``None``.

Live resolution requires the 1Password CLI (``op``) on PATH and a signed-in account or
``OP_SERVICE_ACCOUNT_TOKEN``. Unit tests use fakes; no live 1Password account is required in CI.
"""

from __future__ import annotations

import asyncio
import os
import shutil

from sevn.security.secrets.errors import SecretsBackendError


class OnePasswordCliBackend:
    """Resolve logical keys via the 1Password CLI (``op read`` / ``op item get``)."""

    def __init__(
        self,
        *,
        cli_path: str | None = None,
        vault: str | None = None,
        account: str | None = None,
        field: str = "password",
    ) -> None:
        """Configure the 1Password CLI bridge.

        Args:
            cli_path (str | None): Override CLI binary; defaults to ``op``.
            vault (str | None): Vault name for ``op://vault/item/field`` references.
            account (str | None): Optional ``--account`` shorthand for multi-account setups.
            field (str): Default field label when ``key`` is an item title (not ``op://``).

        Examples:
            >>> b = OnePasswordCliBackend()
            >>> b.__class__.__name__
            'OnePasswordCliBackend'
        """
        self._cli = cli_path or "op"
        self._vault = vault
        self._account = account
        self._field = field

    def _resolved_cli(self) -> str | None:
        """Return the absolute path of ``op`` when present on PATH.

        Returns:
            str | None: Absolute path or ``None`` when the CLI is missing.

        Examples:
            >>> import inspect
            >>> inspect.signature(OnePasswordCliBackend._resolved_cli).return_annotation
            'str | None'
        """
        return shutil.which(self._cli)

    def _account_flags(self) -> list[str]:
        """Return optional ``--account`` argv flags.

        Returns:
            list[str]: Account flags or empty when unset.

        Examples:
            >>> OnePasswordCliBackend(account="work")._account_flags()
            ['--account', 'work']
        """
        if not self._account:
            return []
        return ["--account", self._account]

    def _reference_for(self, key: str) -> str:
        """Build an ``op read`` secret reference for a logical key.

        Args:
            key (str): Logical secret id or existing ``op://`` URI.

        Returns:
            str: Reference passed to ``op read`` or ``op item get``.

        Examples:
            >>> OnePasswordCliBackend(vault="Ops")._reference_for("api.key")
            'op://Ops/api.key/password'
        """
        if key.startswith("op://"):
            return key
        if self._vault:
            return f"op://{self._vault}/{key}/{self._field}"
        return key

    async def _run(self, args: list[str]) -> tuple[int, bytes, bytes]:
        """Run the CLI and return ``(returncode, stdout, stderr)``.

        Args:
            args (list[str]): Full argv including the executable path.

        Returns:
            tuple[int, bytes, bytes]: Process exit code and captured streams.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(OnePasswordCliBackend._run)
            True
        """
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        out, err = await proc.communicate()
        return proc.returncode or 0, out, err

    async def get(self, key: str) -> str | None:
        """Return plaintext for ``key`` via ``op read`` or ``op item get``.

        Args:
            key (str): Logical secret id, item title, or ``op://`` reference.

        Returns:
            str | None: Plaintext on success; ``None`` when CLI missing or lookup fails.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(OnePasswordCliBackend.get)
            True
        """
        exe = self._resolved_cli()
        if exe is None:
            return None
        ref = self._reference_for(key)
        if ref.startswith("op://"):
            args = [exe, "read", ref, *self._account_flags()]
        else:
            args = [
                exe,
                "item",
                "get",
                ref,
                "--fields",
                f"label={self._field}",
                *self._account_flags(),
            ]
        code, out, _err = await self._run(args)
        if code != 0:
            return None
        text = out.decode("utf-8").strip()
        return text or None

    async def set(self, key: str, value: str) -> None:
        """Persist ``value`` for ``key`` when the CLI supports item edit.

        Args:
            key (str): Logical secret id or ``op://`` reference.
            value (str): UTF-8 plaintext to store.

        Raises:
            SecretsBackendError: When the CLI is missing or exits non-zero.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(OnePasswordCliBackend.set)
            True
        """
        exe = self._resolved_cli()
        if exe is None:
            msg = "1Password CLI (op) is not installed or not on PATH"
            raise SecretsBackendError(msg)
        ref = self._reference_for(key)
        if ref.startswith("op://"):
            args = [exe, "item", "edit", ref, f"{self._field}={value}", *self._account_flags()]
        else:
            args = [
                exe,
                "item",
                "edit",
                ref,
                f"{self._field}={value}",
                *self._account_flags(),
            ]
        code, _out, err = await self._run(args)
        if code != 0:
            detail = err.decode("utf-8", errors="replace").strip()
            msg = f"1Password CLI set failed (exit {code}): {detail}"
            raise SecretsBackendError(msg)

    async def delete(self, key: str) -> None:
        """Remove the item for ``key`` when present (idempotent when absent).

        Args:
            key (str): Logical secret id or ``op://`` reference.

        Raises:
            SecretsBackendError: When the CLI is missing or exits non-zero (except not-found).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(OnePasswordCliBackend.delete)
            True
        """
        exe = self._resolved_cli()
        if exe is None:
            msg = "1Password CLI (op) is not installed or not on PATH"
            raise SecretsBackendError(msg)
        ref = self._reference_for(key)
        item_ref = (
            ref
            if not ref.startswith("op://")
            else ref.rsplit("/", 1)[0].replace(f"/{self._field}", "", 1)
        )
        args = [exe, "item", "delete", item_ref, *self._account_flags()]
        code, _out, err = await self._run(args)
        if code == 0:
            return
        detail = err.decode("utf-8", errors="replace").lower()
        if "not found" in detail or "doesn't exist" in detail:
            return
        err_text = err.decode("utf-8", errors="replace").strip()
        msg = f"1Password CLI delete failed (exit {code}): {err_text}"
        raise SecretsBackendError(msg)
