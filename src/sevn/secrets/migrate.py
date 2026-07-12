"""Legacy plaintext ``.sevn/secrets`` promotion (`specs/06-secrets.md` §10.2).

Module: sevn.secrets.migrate
Depends: asyncio, json, pathlib, sevn.config.workspace_config, sevn.security.secrets.*

Exports:
    secrets_dir_under_content_root — ``<content_root>/.sevn/secrets``.
    legacy_plaintext_entries — load legacy map from disk (no decryption).
    remove_legacy_plaintext_artifacts — delete legacy files after promotion.
    promote_legacy_plaintext_to_encrypted_store — async copy into ``EncryptedFileBackend``.
    promote_legacy_plaintext_to_encrypted_store_sync — blocking wrapper.
    PromotionResult — promotion counts dataclass.
    encrypted_file_backend_for_workspace — ``EncryptedFileBackend`` + env wiring.
    non_legacy_files_present — unexpected filenames beside legacy artefacts.
    store_enc_reserved_path — conventional ``store.enc`` path under a secrets dir.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend
from sevn.security.secrets.factory import (
    parse_optional_master_key_hex,
    resolve_primary_encrypted_store_path,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.config.workspace_config import WorkspaceConfig


LEGACY_PLAINTEXT_JSON = "plaintext.json"
_LEGACY_FILE_SUFFIX = ".secret"
_RESERVED_NAMES = frozenset({"store.enc"})


def secrets_dir_under_content_root(content_root: Path) -> Path:
    """Return ``<content_root>/.sevn/secrets``.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        Path: Secrets directory (may not exist yet).

    Examples:
        >>> from pathlib import Path
        >>> secrets_dir_under_content_root(Path("/tmp/r")).parts[-3:]
        ('r', '.sevn', 'secrets')
    """
    return content_root / ".sevn" / "secrets"


def legacy_plaintext_entries(secrets_dir: Path) -> dict[str, str]:
    """Load legacy plaintext material without touching ``store.enc``.

    Supports:

    - ``plaintext.json`` — JSON object with string keys and string values.
    - ``<logical_key>.secret`` — one UTF-8 value per file (stem is the key).

    Args:
        secrets_dir (Path): Directory under ``.sevn/secrets``.

    Returns:
        dict[str, str]: Logical key → plaintext (empty when nothing legacy exists).

    Raises:
        ValueError: When ``plaintext.json`` is present but not a string→string map.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp()) / "secrets"
        >>> d.mkdir(parents=True)
        >>> _ = (d / LEGACY_PLAINTEXT_JSON).write_text(
        ...     '{"k":"v"}', encoding="utf-8"
        ... )
        >>> legacy_plaintext_entries(d)["k"]
        'v'
    """
    out: dict[str, str] = {}
    if not secrets_dir.is_dir():
        return out
    plain_file = secrets_dir / LEGACY_PLAINTEXT_JSON
    if plain_file.is_file():
        try:
            raw = json.loads(plain_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            msg = f"{LEGACY_PLAINTEXT_JSON} is not valid JSON ({exc})"
            raise ValueError(msg) from exc
        if not isinstance(raw, dict):
            msg = f"{LEGACY_PLAINTEXT_JSON} root must be a JSON object"
            raise ValueError(msg)
        for k, v in raw.items():
            if not isinstance(k, str) or not isinstance(v, str):
                msg = f"{LEGACY_PLAINTEXT_JSON} must map string keys to string values"
                raise ValueError(msg)
            out[k] = v
    for child in secrets_dir.glob(f"*{_LEGACY_FILE_SUFFIX}"):
        if not child.is_file():
            continue
        stem = child.stem
        if stem in out:
            msg = (
                f"duplicate legacy key {stem!r} ({LEGACY_PLAINTEXT_JSON} vs *{_LEGACY_FILE_SUFFIX})"
            )
            raise ValueError(msg)
        try:
            out[stem] = child.read_text(encoding="utf-8").strip()
        except OSError as exc:
            msg = f"cannot read legacy file {child}: {exc}"
            raise ValueError(msg) from exc
    return out


def remove_legacy_plaintext_artifacts(secrets_dir: Path) -> list[str]:
    """Remove ``plaintext.json`` and ``*.secret`` files under ``secrets_dir``.

    Args:
        secrets_dir (Path): Directory scanned by :func:`legacy_plaintext_entries`.

    Returns:
        list[str]: Basenames removed.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp()) / "secrets"
        >>> d.mkdir(parents=True)
        >>> _ = (d / LEGACY_PLAINTEXT_JSON).write_text("{}", encoding="utf-8")
        >>> remove_legacy_plaintext_artifacts(d) == [LEGACY_PLAINTEXT_JSON]
        True
    """
    removed: list[str] = []
    if not secrets_dir.is_dir():
        return removed
    pf = secrets_dir / LEGACY_PLAINTEXT_JSON
    if pf.is_file():
        pf.unlink(missing_ok=True)
        removed.append(pf.name)
    for child in list(secrets_dir.glob(f"*{_LEGACY_FILE_SUFFIX}")):
        if child.is_file():
            child.unlink(missing_ok=True)
            removed.append(child.name)
    return removed


def encrypted_file_backend_for_workspace(
    content_root: Path,
    workspace_config: WorkspaceConfig,
) -> EncryptedFileBackend:
    """Build ``EncryptedFileBackend`` using operator env + workspace paths.

    Args:
        content_root (Path): Resolved workspace content root.
        workspace_config (WorkspaceConfig): Parsed ``sevn.json``.

    Returns:
        EncryptedFileBackend: Writable store at the resolved encrypted path.

    Raises:
        ValueError: When neither ``SEVN_SECRETS_MASTER_KEY`` nor
            ``SEVN_SECRETS_PASSPHRASE`` is usable for writes.

    Examples:
        >>> encrypted_file_backend_for_workspace.__name__
        'encrypted_file_backend_for_workspace'
    """
    import os

    from sevn.config.workspace_config import effective_encrypted_file_key_source

    path = resolve_primary_encrypted_store_path(content_root, workspace_config.secrets_backend)
    # Seal with the configured key source only — never both — so migration writes a store the
    # daemons can later open under the same explicit mechanism.
    if effective_encrypted_file_key_source(workspace_config.secrets_backend) == "master_key":
        mk = parse_optional_master_key_hex()
        if mk is None:
            msg = (
                "set SEVN_SECRETS_MASTER_KEY (64 hex chars) before migrating or writing the "
                "encrypted store (secrets_backend.encrypted_file.key_source=master_key)"
            )
            raise ValueError(msg)
        return EncryptedFileBackend(path, master_key=mk, passphrase=None)
    passphrase = os.environ.get("SEVN_SECRETS_PASSPHRASE")
    if not passphrase:
        msg = (
            "set SEVN_SECRETS_PASSPHRASE before migrating or writing the encrypted store "
            "(secrets_backend.encrypted_file.key_source=passphrase)"
        )
        raise ValueError(msg)
    return EncryptedFileBackend(path, master_key=None, passphrase=passphrase)


@dataclass(frozen=True)
class PromotionResult:
    """Outcome of :func:`promote_legacy_plaintext_to_encrypted_store`."""

    keys_written: int
    keys_skipped_existing: int
    removed_legacy_files: list[str]


async def promote_legacy_plaintext_to_encrypted_store(
    *,
    content_root: Path,
    workspace_config: WorkspaceConfig,
    legacy_overwrites_encrypted: bool = True,
    delete_legacy_after: bool = True,
) -> PromotionResult:
    """Copy legacy plaintext entries into the encrypted file backend.

    Args:
        content_root (Path): Workspace content root.
        workspace_config (WorkspaceConfig): Parsed ``sevn.json``.
        legacy_overwrites_encrypted (bool): When False, existing encrypted keys
            are left unchanged.
        delete_legacy_after (bool): Remove legacy artifacts after successful writes.

    Returns:
        PromotionResult: Counts and removed legacy basenames.

    Raises:
        SecretsStoreCorruptError: When the encrypted store cannot be read.
        ValueError: Legacy layout errors from :func:`legacy_plaintext_entries`.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(promote_legacy_plaintext_to_encrypted_store)
        True
    """
    root = await asyncio.to_thread(content_root.resolve)
    secrets_dir = secrets_dir_under_content_root(root)
    legacy = legacy_plaintext_entries(secrets_dir)
    if not legacy:
        return PromotionResult(keys_written=0, keys_skipped_existing=0, removed_legacy_files=[])

    backend = encrypted_file_backend_for_workspace(root, workspace_config)
    written = 0
    skipped = 0
    for key, value in sorted(legacy.items()):
        existing = await backend.get(key)
        if existing is not None and not legacy_overwrites_encrypted:
            skipped += 1
            continue
        await backend.set(key, value)
        written += 1

    removed: list[str] = []
    if delete_legacy_after and written > 0:
        removed = remove_legacy_plaintext_artifacts(secrets_dir)

    return PromotionResult(
        keys_written=written,
        keys_skipped_existing=skipped,
        removed_legacy_files=removed,
    )


def promote_legacy_plaintext_to_encrypted_store_sync(
    *,
    content_root: Path,
    workspace_config: WorkspaceConfig,
    legacy_overwrites_encrypted: bool = True,
    delete_legacy_after: bool = True,
) -> PromotionResult:
    """Blocking wrapper for :func:`promote_legacy_plaintext_to_encrypted_store`.

    Args:
        content_root (Path): Workspace content root.
        workspace_config (WorkspaceConfig): Parsed ``sevn.json``.
        legacy_overwrites_encrypted (bool): Forwarded.
        delete_legacy_after (bool): Forwarded.

    Returns:
        PromotionResult: Async helper result.

    Examples:
        >>> promote_legacy_plaintext_to_encrypted_store_sync.__name__
        'promote_legacy_plaintext_to_encrypted_store_sync'
    """
    return asyncio.run(
        promote_legacy_plaintext_to_encrypted_store(
            content_root=content_root,
            workspace_config=workspace_config,
            legacy_overwrites_encrypted=legacy_overwrites_encrypted,
            delete_legacy_after=delete_legacy_after,
        ),
    )


def store_enc_reserved_path(secrets_dir: Path) -> Path:
    """Return the conventional ``store.enc`` path under ``secrets_dir``.

    Args:
        secrets_dir (Path): ``.sevn/secrets`` directory.

    Returns:
        Path: Path to ``store.enc`` (file may not exist).

    Examples:
        >>> from pathlib import Path
        >>> store_enc_reserved_path(Path("/tmp/.sevn/secrets")).name
        'store.enc'
    """
    return secrets_dir / "store.enc"


def non_legacy_files_present(secrets_dir: Path) -> list[str]:
    """List unexpected non-legacy files that could hold plaintext keys.

    Flags loose files other than ``store.enc``, ``plaintext.json``, ``*.secret``,
    and ``*.tmp`` so operators can review before migration.

    Args:
        secrets_dir (Path): Secrets directory.

    Returns:
        list[str]: Basenames of suspicious files.

    Examples:
        >>> from pathlib import Path
        >>> non_legacy_files_present(Path("/missing"))
        []
    """
    if not secrets_dir.is_dir():
        return []
    suspicious: list[str] = []
    for child in secrets_dir.iterdir():
        if not child.is_file():
            continue
        name = child.name
        if name in _RESERVED_NAMES:
            continue
        if name == LEGACY_PLAINTEXT_JSON:
            continue
        if name.endswith(_LEGACY_FILE_SUFFIX):
            continue
        if name.endswith(".tmp"):
            continue
        suspicious.append(name)
    return sorted(suspicious)
