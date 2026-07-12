"""Proton Pass CLI bridge (``specs/06-secrets.md`` §3.2).

Module: sevn.security.secrets.backends.proton_pass
Depends: asyncio, os, shutil

Exports:
    ProtonPassCliBackend — wraps CLI; unavailable CLI ⇒ ``get`` returns ``None``.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from sevn.security.secrets.errors import SecretsBackendError

_DELETE_NOT_FOUND_MARKERS = (
    "not found",
    "does not exist",
    "no such",
    "could not find",
)


class ProtonPassCliBackend:
    """Invoke a Proton Pass compatible CLI (``proton-pass`` by default)."""

    def __init__(
        self,
        *,
        cli_path: str | None = None,
        vault: str | None = None,
        item_selector: str | None = None,
    ) -> None:
        """Configure the Proton Pass CLI bridge.

        Args:
            cli_path (str | None): Override CLI binary; defaults to ``proton-pass``.
            vault (str | None): Optional vault name passed via ``--vault``.
            item_selector (str | None): Static selector substituted for the logical key
                (used when one CLI item maps to multiple logical keys).

        Examples:
            >>> b = ProtonPassCliBackend()
            >>> b.__class__.__name__
            'ProtonPassCliBackend'
        """
        self._cli = cli_path or "proton-pass"
        self._vault = vault
        self._selector = item_selector

    def _resolved_cli(self) -> str | None:
        """Return the absolute path of the configured CLI if present on PATH.

        Returns:
            str | None: Absolute path or ``None`` when the CLI is missing.

        Examples:
            >>> import inspect
            >>> inspect.signature(ProtonPassCliBackend._resolved_cli).return_annotation
            'str | None'
        """
        path = shutil.which(self._cli)
        return path  # noqa: RET504

    def _item_label(self, key: str) -> str:
        """Return the CLI item label for a logical secret key.

        Args:
            key (str): Logical secret id.

        Returns:
            str: ``item_selector`` when configured, else ``key``.

        Examples:
            >>> ProtonPassCliBackend(item_selector="vault-item")._item_label("logical")
            'vault-item'
        """
        return self._selector or key

    def _vault_flags(self, *, pass_cli: bool) -> list[str]:
        """Return vault selector argv for the active CLI dialect.

        Args:
            pass_cli (bool): When True, emit ``pass-cli`` ``--vault-name`` flags.

        Returns:
            list[str]: Vault flags, or empty when no vault is configured.

        Examples:
            >>> ProtonPassCliBackend(vault="ops")._vault_flags(pass_cli=True)
            ['--vault-name', 'ops']
        """
        if not self._vault:
            return []
        if pass_cli:
            return ["--vault-name", self._vault]
        return ["--vault", self._vault]

    @staticmethod
    def _is_pass_cli(exe: str) -> bool:
        """Return True when ``exe`` is the ``pass-cli`` dialect (``item`` subcommands).

        Args:
            exe (str): Resolved CLI path.

        Returns:
            bool: True for ``pass-cli`` / ``*-pass-cli`` binary names.

        Examples:
            >>> ProtonPassCliBackend._is_pass_cli("/usr/bin/pass-cli")
            True
            >>> ProtonPassCliBackend._is_pass_cli("/usr/bin/proton-pass")
            False
        """
        base = Path(exe).name
        return base == "pass-cli" or base.endswith("-pass-cli")

    def _subprocess_env(self) -> dict[str, str]:
        """Build subprocess env with Proton Pass auth vars and passphrase bridge.

        Returns:
            dict[str, str]: Copy of ``os.environ`` with ``PROTON_PASS_PASSWORD`` bridged
                from ``SEVN_SECRETS_PASSPHRASE`` when unset.

        Examples:
            >>> import os
            >>> os.environ["SEVN_SECRETS_PASSPHRASE"] = "pw"
            >>> env = ProtonPassCliBackend()._subprocess_env()
            >>> env.get("PROTON_PASS_PASSWORD") == "pw"
            True
            >>> _ = os.environ.pop("SEVN_SECRETS_PASSPHRASE", None)
        """
        env = os.environ.copy()
        passphrase = env.get("SEVN_SECRETS_PASSPHRASE", "").strip()
        if passphrase and not env.get("PROTON_PASS_PASSWORD", "").strip():
            env["PROTON_PASS_PASSWORD"] = passphrase
        return env

    async def _run(self, args: list[str]) -> tuple[int, bytes, bytes]:
        """Run the CLI and return ``(returncode, stdout, stderr)``.

        Args:
            args (list[str]): Full argv including the executable path.

        Returns:
            tuple[int, bytes, bytes]: Process exit code and captured streams.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ProtonPassCliBackend._run)
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
        """Return plaintext for ``key`` via ``proton-pass show`` or ``pass-cli item view``.

        Args:
            key (str): Logical secret id (used as CLI argument when no selector set).

        Returns:
            str | None: Plaintext on success, ``None`` when CLI missing or call fails.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ProtonPassCliBackend.get)
            True
        """
        exe = self._resolved_cli()
        if exe is None:
            return None
        label = self._item_label(key)
        if self._is_pass_cli(exe):
            args = [exe, "item", "view", *self._vault_flags(pass_cli=True), "--item-title", label]
        else:
            args = [exe, *self._vault_flags(pass_cli=False), "show", label]
        code, out, _err = await self._run(args)
        if code != 0:
            return None
        text = out.decode("utf-8").strip()
        return text or None

    async def set(self, key: str, value: str) -> None:
        """Persist ``value`` for ``key`` via the Proton Pass CLI.

        Args:
            key (str): Logical secret id.
            value (str): UTF-8 plaintext to store.

        Raises:
            SecretsBackendError: When the CLI is missing or exits non-zero.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ProtonPassCliBackend.set)
            True
        """
        exe = self._resolved_cli()
        if exe is None:
            msg = "proton pass CLI is not installed or not on PATH"
            raise SecretsBackendError(msg)
        label = self._item_label(key)
        if self._is_pass_cli(exe):
            args = [
                exe,
                "item",
                "update",
                *self._vault_flags(pass_cli=True),
                "--item-title",
                label,
                "--field",
                f"password={value}",
            ]
        else:
            args = [exe, *self._vault_flags(pass_cli=False), "set", label, value]
        code, _out, err = await self._run(args)
        if code != 0:
            detail = err.decode("utf-8", errors="replace").strip()
            msg = f"proton pass CLI set failed (exit {code}): {detail}"
            raise SecretsBackendError(msg)

    async def delete(self, key: str) -> None:
        """Remove the item for ``key`` if present (idempotent when already absent).

        Args:
            key (str): Logical secret id.

        Raises:
            SecretsBackendError: When the CLI is missing or exits non-zero (except not-found).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ProtonPassCliBackend.delete)
            True
        """
        exe = self._resolved_cli()
        if exe is None:
            msg = "proton pass CLI is not installed or not on PATH"
            raise SecretsBackendError(msg)
        label = self._item_label(key)
        if self._is_pass_cli(exe):
            args = [
                exe,
                "item",
                "delete",
                *self._vault_flags(pass_cli=True),
                "--item-title",
                label,
            ]
        else:
            args = [exe, *self._vault_flags(pass_cli=False), "delete", label]
        code, _out, err = await self._run(args)
        if code == 0:
            return
        if self._delete_not_found(err):
            return
        detail = err.decode("utf-8", errors="replace").strip()
        msg = f"proton pass CLI delete failed (exit {code}): {detail}"
        raise SecretsBackendError(msg)

    @staticmethod
    def _delete_not_found(stderr: bytes) -> bool:
        """Return True when CLI stderr indicates the item was already absent.

        Args:
            stderr (bytes): Captured stderr from the delete subprocess.

        Returns:
            bool: True for benign not-found messages.

        Examples:
            >>> ProtonPassCliBackend._delete_not_found(b"item not found")
            True
        """
        text = stderr.decode("utf-8", errors="replace").lower()
        return any(marker in text for marker in _DELETE_NOT_FOUND_MARKERS)
