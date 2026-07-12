"""Secrets backend subtree models and coercion helpers for ``sevn.json``.

Module: sevn.config.sections.secrets
Depends: pydantic, sevn.config.defaults

Exports:
    EncryptedFileSubtreeDefaults — encrypted-file path defaults (``specs/06-secrets.md`` §5).
    EncryptedFileBackendEntry — ``secrets_backend.chain`` encrypted-file entry.
    MacOSKeychainBackendEntry — macOS keychain chain entry.
    LinuxSecretServiceBackendEntry — libsecret chain entry.
    OpenBaoBackendEntry — OpenBao KV chain entry.
    ProtonPassBackendEntry — Proton Pass CLI chain entry.
    SecretsBackendSectionConfig — ``secrets_backend`` subtree (``specs/06-secrets.md`` §5).
    effective_encrypted_file_key_source — resolve encrypted-file unlock mechanism.
"""

from __future__ import annotations

import sys
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    field_validator,
    model_validator,
)

from sevn.config.defaults import (
    DEFAULT_ENCRYPTED_FILE_KEY_SOURCE,
    DEFAULT_SECRET_CACHE_TTL_SECONDS,
)

JsonDict = dict[str, Any]


def _coerce_key_source(v: object) -> object:
    """Give an actionable error for the reserved ``os_keychain`` key source.

    Args:
        v (object): Raw ``key_source`` value before ``Literal`` coercion.

    Returns:
        object: Unchanged value (``Literal`` validation handles other invalids).

    Raises:
        ValueError: When ``os_keychain`` is requested (reserved, not yet implemented).

    Examples:
        >>> _coerce_key_source("passphrase")
        'passphrase'
        >>> _coerce_key_source("os_keychain")
        Traceback (most recent call last):
        ValueError: secrets_backend.encrypted_file.key_source 'os_keychain' is reserved and not yet supported; use 'passphrase' or 'master_key'
    """
    if isinstance(v, str) and v.strip().lower() == "os_keychain":
        msg = (
            "secrets_backend.encrypted_file.key_source 'os_keychain' is reserved and not yet "
            "supported; use 'passphrase' or 'master_key'"
        )
        raise ValueError(msg)
    return v


EncryptedFileKeySource = Annotated[
    Literal["passphrase", "master_key"], BeforeValidator(_coerce_key_source)
]
"""Explicit unlock mechanism for the encrypted-file store (``specs/06-secrets.md`` §5).

``passphrase`` derives the AEAD key from ``SEVN_SECRETS_PASSPHRASE`` (PBKDF2); ``master_key``
uses the raw 32-byte ``SEVN_SECRETS_MASTER_KEY``. Exactly one is used — the other env var is
ignored — so the environment can no longer silently change which key decrypts the store. The
``BeforeValidator`` gives an actionable error for the reserved ``os_keychain`` value.
"""


class EncryptedFileSubtreeDefaults(BaseModel):
    """Default path + key source for encrypted-file backend (``specs/06-secrets.md`` §5)."""

    model_config = ConfigDict(extra="forbid")

    path: str | None = None
    key_source: EncryptedFileKeySource | None = None


class EncryptedFileBackendEntry(BaseModel):
    """``type``: ``encrypted_file``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["encrypted_file"] = "encrypted_file"
    path: str | None = None
    key_source: EncryptedFileKeySource | None = None


class MacOSKeychainBackendEntry(BaseModel):
    """``type``: ``macos_keychain``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["macos_keychain"] = "macos_keychain"
    service: str | None = None


class LinuxSecretServiceBackendEntry(BaseModel):
    """``type``: ``linux_secret_service``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["linux_secret_service"] = "linux_secret_service"
    collection: str | None = None


class OpenBaoBackendEntry(BaseModel):
    """``type``: ``openbao`` (OSS KV; HashiCorp Vault commercial not supported)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["openbao"] = "openbao"
    address: str
    mount: str = "secret"
    prefix: str = ""
    token: str | None = None
    namespace: str | None = None


class ProtonPassBackendEntry(BaseModel):
    """``type``: ``proton_pass``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["proton_pass"] = "proton_pass"
    vault: str | None = None
    item_selector: str | None = None
    cli_path: str | None = None


BackendEntry = Annotated[
    EncryptedFileBackendEntry
    | MacOSKeychainBackendEntry
    | LinuxSecretServiceBackendEntry
    | OpenBaoBackendEntry
    | ProtonPassBackendEntry,
    Discriminator("type"),
]


class SecretsBackendSectionConfig(BaseModel):
    """``secrets_backend`` subtree in ``sevn.json`` (``specs/06-secrets.md`` §5)."""

    model_config = ConfigDict(extra="forbid")

    cache_ttl_seconds: int = Field(default=DEFAULT_SECRET_CACHE_TTL_SECONDS, ge=0)
    chain: list[BackendEntry] | None = None
    write_targets: list[str] | Literal["first_writable"] = "first_writable"
    encrypted_file: EncryptedFileSubtreeDefaults | None = None
    openbao: JsonDict | None = None
    proton_pass: JsonDict | None = None

    @field_validator("chain", mode="before")
    @classmethod
    def _reject_commercial_vault_types(cls, v: object) -> object:
        """Reject HashiCorp / enterprise vault shim types at parse time.

        Args:
            cls (type): Model class.
            v (object): Raw ``chain`` field before coercion.

        Returns:
            object: Unchanged list or raw value.

        Examples:
            >>> SecretsBackendSectionConfig._reject_commercial_vault_types(None) is None
            True
        """
        if v is None or not isinstance(v, list):
            return v
        for item in v:
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if t in ("hashicorp_vault", "vault", "vault_enterprise"):
                msg = f"unsupported secrets backend type {t!r}; use openbao or encrypted_file"
                raise ValueError(msg)
        return v

    @model_validator(mode="before")
    @classmethod
    def _reject_commercial_vault_keys(cls, data: object) -> object:
        """Reject unsupported commercial vault keys on the section object.

        Args:
            cls (type): Model class.
            data (object): Raw mapping before model init.

        Returns:
            object: Unchanged mapping or non-dict passthrough.

        Examples:
            >>> SecretsBackendSectionConfig._reject_commercial_vault_keys({"cache_ttl_seconds": 1})
            {'cache_ttl_seconds': 1}
        """
        if not isinstance(data, dict):
            return data
        for key in data:
            lk = key.lower()
            if lk in ("hashicorp_vault", "vault_enterprise"):
                msg = f"unsupported secrets_backend key {key!r}"
                raise ValueError(msg)
        return data


def effective_encrypted_file_key_source(
    section: SecretsBackendSectionConfig | None,
) -> str:
    """Resolve the encrypted-file unlock mechanism: chain entry > section default > passphrase.

    Used by callers that only have the ``secrets_backend`` section (daemon env propagation,
    migration). The per-entry value on the first ``encrypted_file`` chain entry wins, then the
    ``encrypted_file`` defaults block, then ``DEFAULT_ENCRYPTED_FILE_KEY_SOURCE`` (``passphrase``).

    Args:
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.

    Returns:
        str: ``"passphrase"`` or ``"master_key"``.

    Examples:
        >>> effective_encrypted_file_key_source(None)
        'passphrase'
        >>> effective_encrypted_file_key_source(
        ...     SecretsBackendSectionConfig(encrypted_file=EncryptedFileSubtreeDefaults(
        ...         key_source="master_key"))
        ... )
        'master_key'
    """
    if section is not None:
        if section.chain:
            for ent in section.chain:
                if isinstance(ent, EncryptedFileBackendEntry) and ent.key_source is not None:
                    return ent.key_source
        if section.encrypted_file is not None and section.encrypted_file.key_source is not None:
            return section.encrypted_file.key_source
    return DEFAULT_ENCRYPTED_FILE_KEY_SOURCE


def _legacy_secrets_string_to_dict(value: str) -> dict[str, object]:
    """Map legacy single-string ``secrets_backend`` to a section object.

    Args:
        value (str): Legacy token (for example ``encrypted-file``).

    Returns:
        dict[str, object]: Normalized ``secrets_backend`` dict.

    Examples:
        >>> out = _legacy_secrets_string_to_dict("encrypted-file")
        >>> out["chain"][0]["type"]
        'encrypted_file'
    """
    normalized = {
        "encrypted-file": "encrypted_file",
        "keychain": "keychain",
        "openbao": "openbao",
        "proton-pass": "proton_pass",
    }
    if value not in normalized:
        msg = f"unsupported legacy secrets_backend value {value!r}"
        raise ValueError(msg)
    tag = normalized[value]
    if tag == "encrypted_file":
        return {"chain": [{"type": "encrypted_file"}]}
    if tag == "keychain":
        if sys.platform == "darwin":
            chain: list[dict[str, str]] = [
                {"type": "macos_keychain"},
                {"type": "encrypted_file"},
            ]
        else:
            chain = [
                {"type": "linux_secret_service"},
                {"type": "encrypted_file"},
            ]
        return {"chain": chain}
    if tag == "openbao":
        msg = (
            "legacy secrets_backend 'openbao' requires a structured object "
            "with address, mount, and token"
        )
        raise ValueError(msg)
    if tag == "proton_pass":
        msg = (
            "legacy secrets_backend 'proton-pass' requires a structured object "
            "with vault / CLI settings"
        )
        raise ValueError(msg)
    msg = f"unreachable legacy tag {tag!r}"
    raise AssertionError(msg)


def _coerce_secrets_backend_model(value: object) -> object:
    """Normalize ``secrets_backend`` field to a mapping or model.

    Args:
        value (object): Raw JSON fragment or model instance.

    Returns:
        object: ``None``, an existing ``SecretsBackendSectionConfig``, or a ``dict`` for Pydantic.

    Examples:
        >>> _coerce_secrets_backend_model(None) is None
        True
    """
    if value is None or isinstance(value, SecretsBackendSectionConfig):
        return value
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return _legacy_secrets_string_to_dict(value)
    msg = f"invalid secrets_backend type: {type(value).__name__}"
    raise ValueError(msg)
