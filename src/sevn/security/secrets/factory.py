"""Construct ``SecretsChain`` from ``sevn.json`` (``specs/06-secrets.md`` §4-§5).

Module: sevn.security.secrets.factory
Depends: ``sevn.config`` (no ``sevn.proxy`` imports).

Exports:
    Functions:
        secrets_chain_from_workspace — Build ordered backends + labels from config.
        resolve_backend — Alias for onboarding/doctor sentinel probes.
        default_chain_entries — Default backend preset when ``chain`` is omitted.
        parse_optional_master_key_hex — Decode ``SEVN_SECRETS_MASTER_KEY`` env.
        resolve_primary_encrypted_store_path — Resolve encrypted-file path from config.
"""

from __future__ import annotations

import binascii
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sevn.config.defaults import DEFAULT_ENCRYPTED_FILE_KEY_SOURCE
from sevn.config.workspace_config import (
    BackendEntry,
    EncryptedFileBackendEntry,
    LinuxSecretServiceBackendEntry,
    MacOSKeychainBackendEntry,
    OpenBaoBackendEntry,
    ProtonPassBackendEntry,
    SecretsBackendSectionConfig,
)
from sevn.security.secrets.backends.encrypted_file import (
    EncryptedFileBackend,
    default_encrypted_store_path,
)
from sevn.security.secrets.backends.linux_secret_service import LinuxSecretServiceBackend
from sevn.security.secrets.backends.macos_keychain import MacOSKeychainBackend
from sevn.security.secrets.backends.openbao import OpenBaoBackend
from sevn.security.secrets.backends.proton_pass import ProtonPassCliBackend
from sevn.security.secrets.chain import SecretsChain

if TYPE_CHECKING:
    from sevn.security.secrets.protocol import SecretsBackend

_EXPECTED_KEY_LEN = 32


def _ci_encrypted_file_only() -> bool:
    """Return True when ``CI`` env var is truthy.

    Returns:
        bool: True if encrypted-file-only chain should be forced.

    Examples:
        >>> import os
        >>> _ = os.environ.pop("CI", None)
        >>> _ci_encrypted_file_only()
        False
    """
    return os.environ.get("CI", "").lower() in ("1", "true", "yes")


def default_chain_entries() -> list[BackendEntry]:
    """Preset from ``specs/06-secrets.md`` §5 when ``chain`` is omitted.

    Returns:
        list[BackendEntry]: Default backend entries (platform aware).

    Examples:
        >>> entries = default_chain_entries()
        >>> bool(entries)
        True
    """
    if _ci_encrypted_file_only():
        return [EncryptedFileBackendEntry()]
    if sys.platform == "darwin":
        return [MacOSKeychainBackendEntry(), EncryptedFileBackendEntry()]
    return [LinuxSecretServiceBackendEntry(), EncryptedFileBackendEntry()]


def parse_optional_master_key_hex() -> bytes | None:
    """Parse ``SEVN_SECRETS_MASTER_KEY`` (64 hex chars to 32 bytes) when set.

    Returns:
        bytes | None: 32-byte key on success, ``None`` when env is unset or malformed.

    Examples:
        >>> import os
        >>> _ = os.environ.pop("SEVN_SECRETS_MASTER_KEY", None)
        >>> parse_optional_master_key_hex() is None
        True
    """
    raw = os.environ.get("SEVN_SECRETS_MASTER_KEY")
    if not raw:
        return None
    try:
        key = binascii.unhexlify(raw.strip())
    except binascii.Error:
        return None
    if len(key) != _EXPECTED_KEY_LEN:
        return None
    return key


def _encrypted_file_path(
    entry: EncryptedFileBackendEntry,
    content_root: Path,
    section: SecretsBackendSectionConfig,
) -> Path:
    """Resolve the encrypted store path for an entry.

    Args:
        entry (EncryptedFileBackendEntry): Encrypted-file entry from chain config.
        content_root (Path): Workspace content root (used for relative resolution).
        section (SecretsBackendSectionConfig): Parent secrets-backend config block.

    Returns:
        Path: Absolute resolved path for the encrypted store.

    Examples:
        >>> from sevn.config.workspace_config import (
        ...     EncryptedFileBackendEntry,
        ...     SecretsBackendSectionConfig,
        ... )
        >>> entry = EncryptedFileBackendEntry()
        >>> section = SecretsBackendSectionConfig()
        >>> p = _encrypted_file_path(entry, Path("/tmp"), section)
        >>> p.name
        'store.enc'
    """
    rel = entry.path
    if rel is None and section.encrypted_file is not None:
        rel = section.encrypted_file.path
    if rel is None:
        return default_encrypted_store_path(content_root)
    p = Path(rel)
    if not p.is_absolute():
        return (content_root / p).resolve()
    return p.resolve()


def _encrypted_file_key_source(
    entry: EncryptedFileBackendEntry,
    section: SecretsBackendSectionConfig,
) -> str:
    """Resolve the unlock mechanism for one encrypted-file entry.

    Precedence: the entry's own ``key_source`` > the section ``encrypted_file`` default >
    ``DEFAULT_ENCRYPTED_FILE_KEY_SOURCE`` (``passphrase``).

    Args:
        entry (EncryptedFileBackendEntry): The chain entry being built.
        section (SecretsBackendSectionConfig): Parent secrets-backend config block.

    Returns:
        str: ``"passphrase"`` or ``"master_key"``.

    Examples:
        >>> from sevn.config.workspace_config import (
        ...     EncryptedFileBackendEntry,
        ...     SecretsBackendSectionConfig,
        ... )
        >>> _encrypted_file_key_source(
        ...     EncryptedFileBackendEntry(), SecretsBackendSectionConfig()
        ... )
        'passphrase'
        >>> _encrypted_file_key_source(
        ...     EncryptedFileBackendEntry(key_source="master_key"), SecretsBackendSectionConfig()
        ... )
        'master_key'
    """
    if entry.key_source is not None:
        return entry.key_source
    if section.encrypted_file is not None and section.encrypted_file.key_source is not None:
        return section.encrypted_file.key_source
    return DEFAULT_ENCRYPTED_FILE_KEY_SOURCE


def _build_backend(
    entry: BackendEntry,
    content_root: Path,
    section: SecretsBackendSectionConfig,
) -> tuple[SecretsBackend, str]:
    """Build one backend instance + label from an entry config.

    Args:
        entry (BackendEntry): Typed backend config entry.
        content_root (Path): Workspace content root for path resolution.
        section (SecretsBackendSectionConfig): Parent secrets-backend config block.

    Returns:
        tuple[SecretsBackend, str]: Concrete backend and its type label.

    Raises:
        TypeError: If the entry type is unknown.

    Examples:
        >>> from sevn.config.workspace_config import (
        ...     EncryptedFileBackendEntry,
        ...     SecretsBackendSectionConfig,
        ... )
        >>> entry = EncryptedFileBackendEntry()
        >>> section = SecretsBackendSectionConfig()
        >>> _b, label = _build_backend(entry, Path("/tmp"), section)
        >>> label
        'encrypted_file'
    """
    if isinstance(entry, EncryptedFileBackendEntry):
        path = _encrypted_file_path(entry, content_root, section)
        # Single enforcement point: the explicit key_source decides which credential is used,
        # and only that one is passed to the backend (master_key XOR passphrase). A stray
        # SEVN_SECRETS_MASTER_KEY in the environment can no longer hijack a passphrase store.
        if _encrypted_file_key_source(entry, section) == "master_key":
            backend: SecretsBackend = EncryptedFileBackend(
                path, master_key=parse_optional_master_key_hex(), passphrase=None
            )
        else:  # "passphrase" (default)
            backend = EncryptedFileBackend(
                path, master_key=None, passphrase=os.environ.get("SEVN_SECRETS_PASSPHRASE")
            )
        return (backend, entry.type)
    if isinstance(entry, MacOSKeychainBackendEntry):
        return MacOSKeychainBackend(service=entry.service), entry.type
    if isinstance(entry, LinuxSecretServiceBackendEntry):
        return LinuxSecretServiceBackend(collection_label=entry.collection), entry.type
    if isinstance(entry, OpenBaoBackendEntry):
        return (
            OpenBaoBackend(
                address=entry.address,
                mount=entry.mount,
                prefix=entry.prefix,
                token=entry.token,
                namespace=entry.namespace,
            ),
            entry.type,
        )
    if isinstance(entry, ProtonPassBackendEntry):
        return (
            ProtonPassCliBackend(
                cli_path=entry.cli_path,
                vault=entry.vault,
                item_selector=entry.item_selector,
            ),
            entry.type,
        )
    msg = f"unknown backend entry {entry!r}"
    raise TypeError(msg)


def resolve_primary_encrypted_store_path(
    content_root: Path,
    section: SecretsBackendSectionConfig | None,
) -> Path:
    """Return the encrypted-file path implied by workspace ``secrets_backend``.

    Uses the first ``encrypted_file`` chain entry when present; otherwise the
    section ``encrypted_file.path`` default; otherwise
    ``default_encrypted_store_path``.

    Args:
        content_root (Path): Workspace content root.
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend``
            block from ``sevn.json``.

    Returns:
        Path: Resolved absolute path for ``EncryptedFileBackend``.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecretsBackendSectionConfig
        >>> resolve_primary_encrypted_store_path(Path("/tmp/w"), None).name
        'store.enc'
    """
    cfg = section if section is not None else SecretsBackendSectionConfig()
    entries = list(cfg.chain) if cfg.chain is not None else default_chain_entries()
    for ent in entries:
        if isinstance(ent, EncryptedFileBackendEntry):
            return _encrypted_file_path(ent, content_root.resolve(), cfg)
    return default_encrypted_store_path(content_root)


def secrets_chain_from_workspace(
    content_root: Path,
    section: SecretsBackendSectionConfig | None,
) -> SecretsChain:
    """Build a chain for ``content_root`` using workspace ``secrets_backend`` config.

    Args:
        content_root (Path): Workspace content root (used for path resolution).
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend``
            block from ``sevn.json``; ``None`` falls back to defaults.

    Returns:
        SecretsChain: Ordered backends with write-target policy applied.

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(secrets_chain_from_workspace)
        >>> list(sig.parameters)
        ['content_root', 'section']
    """
    cfg = section if section is not None else SecretsBackendSectionConfig()
    entries = list(cfg.chain) if cfg.chain is not None else default_chain_entries()
    backends: list[SecretsBackend] = []
    labels: list[str] = []
    for ent in entries:
        b, lab = _build_backend(ent, content_root.resolve(), cfg)
        backends.append(b)
        labels.append(lab)
    return SecretsChain(backends, write_targets=cfg.write_targets, backend_labels=labels)


def resolve_backend(
    content_root: Path,
    section: SecretsBackendSectionConfig | None,
) -> SecretsChain:
    """Build the secrets chain for live-validation / doctor probes.

    Args:
        content_root (Path): Workspace content root for path resolution.
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.

    Returns:
        SecretsChain: Ordered backends (same as ``secrets_chain_from_workspace``).

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecretsBackendSectionConfig
        >>> chain = resolve_backend(Path("/tmp/w"), SecretsBackendSectionConfig())
        >>> chain.__class__.__name__
        'SecretsChain'
    """
    return secrets_chain_from_workspace(content_root, section)
