"""Encrypted JSON map on disk with AEAD (``specs/06-secrets.md`` §3.1).

Module: sevn.security.secrets.backends.encrypted_file
Depends: cryptography, sevn.config.defaults

Exports:
    Classes:
        EncryptedFileBackend — Logical key to UTF-8 string map, AES-256-GCM + PBKDF2.
    Functions:
        default_encrypted_store_path — Default ``.sevn/secrets/store.enc`` path.

Plaintext encoding:
    JSON object mapping logical keys to string values (OAuth bundles stored as one string).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from sevn.config.defaults import (
    DEFAULT_ENCRYPTED_SECRET_STORE_NAME,
    MIN_PBKDF2_ITERATIONS,
    SECRET_FILE_FORMAT_VERSION,
)
from sevn.security.secrets.errors import SecretsStoreCorruptError

KDF_RAW_KEY = 0
KDF_PBKDF2_SHA256 = 1

_MAGIC = b"SEVNSECR"
_NONCE_LEN = 12
_SALT_LEN = 16
_KEY_LEN = 32


def _u32_be(n: int) -> bytes:
    """Encode a 32-bit unsigned integer as big-endian bytes.

    Args:
        n (int): Non-negative integer fitting in 32 bits.

    Returns:
        bytes: 4-byte big-endian encoding.

    Examples:
        >>> _u32_be(1)
        b'\\x00\\x00\\x00\\x01'
    """
    return int.to_bytes(n, 4, byteorder="big", signed=False)


def _read_u32_be(b: bytes, off: int) -> tuple[int, int]:
    """Read a 32-bit big-endian unsigned int starting at ``off``.

    Args:
        b (bytes): Buffer to read from.
        off (int): Byte offset where the integer begins.

    Returns:
        tuple[int, int]: Decoded value and new offset (``off + 4``).

    Examples:
        >>> _read_u32_be(b'\\x00\\x00\\x00\\x05extra', 0)
        (5, 4)
    """
    return int.from_bytes(b[off : off + 4], "big", signed=False), off + 4


def default_encrypted_store_path(content_root: Path) -> Path:
    """Default ``<content_root>/.sevn/secrets/store.enc`` (§3.1).

    Args:
        content_root (Path): Workspace content root.

    Returns:
        Path: Resolved default path for the encrypted secret store.

    Examples:
        >>> default_encrypted_store_path(Path("/tmp")).name
        'store.enc'
    """
    return content_root / ".sevn" / "secrets" / DEFAULT_ENCRYPTED_SECRET_STORE_NAME


class EncryptedFileBackend:
    """AES-256-GCM encrypted JSON map at ``file_path``."""

    def __init__(
        self,
        file_path: Path,
        *,
        passphrase: str | None = None,
        master_key: bytes | None = None,
    ) -> None:
        """Configure the backend with a target path and key material.

        Args:
            file_path (Path): Absolute path to the encrypted store file.
            passphrase (str | None): Optional passphrase (PBKDF2 derives the AEAD key).
            master_key (bytes | None): Optional raw 32-byte AEAD key.

        Raises:
            ValueError: If ``master_key`` is provided with length != 32.

        Examples:
            >>> b = EncryptedFileBackend(Path("/tmp/sevn-doctest.enc"))
            >>> b.__class__.__name__
            'EncryptedFileBackend'
        """
        self._path = file_path
        self._passphrase = passphrase
        self._master_key = master_key
        if master_key is not None and len(master_key) != _KEY_LEN:
            msg = "master_key must be 32 bytes for EncryptedFileBackend"
            raise ValueError(msg)

    def _derive_key_pbkdf2(self, salt: bytes) -> bytes:
        """Derive an AEAD key from ``passphrase`` using PBKDF2-HMAC-SHA256.

        Args:
            salt (bytes): KDF salt (typically 16 random bytes).

        Returns:
            bytes: 32-byte derived key.

        Raises:
            SecretsStoreCorruptError: If no passphrase is configured.

        Examples:
            >>> import inspect
            >>> "salt" in inspect.signature(
            ...     EncryptedFileBackend._derive_key_pbkdf2
            ... ).parameters
            True
        """
        if not self._passphrase:
            raise SecretsStoreCorruptError("missing passphrase for encrypted store")
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=_KEY_LEN,
            salt=salt,
            iterations=MIN_PBKDF2_ITERATIONS,
        )
        return kdf.derive(self._passphrase.encode("utf-8"))

    def _material_key(self, *, kdf_id: int, salt: bytes) -> bytes:
        """Return the AEAD key for the configured KDF id.

        Args:
            kdf_id (int): KDF identifier (``KDF_RAW_KEY`` or ``KDF_PBKDF2_SHA256``).
            salt (bytes): KDF salt (empty for raw-key mode).

        Returns:
            bytes: 32-byte AEAD key.

        Raises:
            SecretsStoreCorruptError: If required key material is missing or KDF id
                is unsupported.

        Examples:
            >>> import inspect
            >>> sorted(
            ...     inspect.signature(EncryptedFileBackend._material_key).parameters
            ... )
            ['kdf_id', 'salt', 'self']
        """
        if kdf_id == KDF_RAW_KEY:
            if self._master_key is None:
                raise SecretsStoreCorruptError("encrypted store needs static master_key to decrypt")
            return self._master_key
        if kdf_id == KDF_PBKDF2_SHA256:
            # The blob's recorded ``kdf_id`` is authoritative. A PBKDF2 blob's AEAD key is
            # ``PBKDF2(passphrase, salt)``; a raw ``master_key`` (used only for KDF_RAW_KEY
            # blobs) is unrelated key material. Letting a stray ``master_key`` short-circuit
            # here derives the wrong key and corrupts decryption of passphrase-sealed stores
            # whenever both ``SEVN_SECRETS_PASSPHRASE`` and ``SEVN_SECRETS_MASTER_KEY`` are set.
            if self._passphrase is None:
                raise SecretsStoreCorruptError("encrypted store needs passphrase to decrypt")
            return self._derive_key_pbkdf2(salt)
        raise SecretsStoreCorruptError(f"unsupported KDF id {kdf_id}")

    def _encrypt_blob(self, plain: bytes) -> bytes:
        """Encrypt ``plain`` into the on-disk blob with header + AEAD ciphertext.

        Args:
            plain (bytes): JSON plaintext to encrypt.

        Returns:
            bytes: Header + nonce + AEAD ciphertext for atomic write to disk.

        Raises:
            ValueError: If neither passphrase nor master_key is configured.

        Examples:
            >>> import inspect
            >>> inspect.signature(EncryptedFileBackend._encrypt_blob).return_annotation
            'bytes'
        """
        kdf_id: int
        salt: bytes
        key: bytes
        if self._master_key is not None:
            kdf_id, salt, key = KDF_RAW_KEY, b"", self._master_key
        elif self._passphrase is not None:
            salt = os.urandom(_SALT_LEN)
            kdf_id = KDF_PBKDF2_SHA256
            key = self._derive_key_pbkdf2(salt)
        else:
            msg = "EncryptedFileBackend requires master_key or passphrase for writes"
            raise ValueError(msg)

        ver = SECRET_FILE_FORMAT_VERSION
        header = _MAGIC + _u32_be(ver) + _u32_be(kdf_id)
        if kdf_id == KDF_PBKDF2_SHA256:
            header += salt
        elif kdf_id != KDF_RAW_KEY:
            msg = f"unexpected kdf_id for encryption: {kdf_id}"
            raise ValueError(msg)

        nonce = os.urandom(_NONCE_LEN)
        aes = AESGCM(key)
        aad = header
        ct = aes.encrypt(nonce, plain, aad)
        return header + nonce + ct

    def _decrypt_blob(self, blob: bytes) -> bytes:
        """Decrypt and authenticate an on-disk blob into JSON plaintext.

        Args:
            blob (bytes): Raw file contents previously produced by ``_encrypt_blob``.

        Returns:
            bytes: Decrypted JSON plaintext.

        Raises:
            SecretsStoreCorruptError: If header is malformed or AEAD authentication fails.

        Examples:
            >>> import inspect
            >>> inspect.signature(EncryptedFileBackend._decrypt_blob).return_annotation
            'bytes'
        """
        if len(blob) < len(_MAGIC) + 8 + _NONCE_LEN + 16:
            raise SecretsStoreCorruptError("encrypted store file too small")
        if not blob.startswith(_MAGIC):
            raise SecretsStoreCorruptError("encrypted store bad magic")
        off = len(_MAGIC)
        ver, off = _read_u32_be(blob, off)
        if ver != SECRET_FILE_FORMAT_VERSION:
            raise SecretsStoreCorruptError(f"unsupported format version {ver}")
        kdf_id, off = _read_u32_be(blob, off)
        salt = b""
        if kdf_id == KDF_PBKDF2_SHA256:
            salt = blob[off : off + _SALT_LEN]
            off += _SALT_LEN
        nonce_start = off
        nonce = blob[off : off + _NONCE_LEN]
        off += _NONCE_LEN
        ct = blob[off:]
        header = blob[:nonce_start]
        key = self._material_key(kdf_id=kdf_id, salt=salt)
        aes = AESGCM(key)
        try:
            return aes.decrypt(nonce, ct, header)
        except InvalidTag as exc:
            raise SecretsStoreCorruptError("AEAD decrypt failed (corrupt or wrong key)") from exc

    def _load_map_sync(self) -> dict[str, str]:
        """Load and decrypt the on-disk map (blocking).

        Returns:
            dict[str, str]: Logical-key to plaintext map (empty if file missing).

        Raises:
            SecretsStoreCorruptError: If the file exists but cannot be parsed or
                authenticated.

        Examples:
            >>> import inspect
            >>> inspect.signature(EncryptedFileBackend._load_map_sync).return_annotation
            'dict[str, str]'
        """
        if not self._path.exists():
            return {}
        blob = self._path.read_bytes()
        raw = self._decrypt_blob(blob)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecretsStoreCorruptError("encrypted store plaintext is not valid JSON") from exc
        if not isinstance(data, dict):
            raise SecretsStoreCorruptError("encrypted store root must be a JSON object")
        out: dict[str, str] = {}
        for k, v in data.items():
            if not isinstance(k, str) or not isinstance(v, str):
                msg = "encrypted store map must be string keys and string values"
                raise SecretsStoreCorruptError(msg)
            out[k] = v
        return out

    def _save_map_sync(self, data: dict[str, str]) -> None:
        """Persist ``data`` to disk via encrypt + atomic replace (blocking).

        Args:
            data (dict[str, str]): Logical-key to plaintext map to persist.

        Examples:
            >>> import inspect
            >>> "data" in inspect.signature(
            ...     EncryptedFileBackend._save_map_sync
            ... ).parameters
            True
        """
        plain = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8",
        )
        blob = self._encrypt_blob(plain)
        self._path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        tmp = Path(tmp_path)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        finally:
            if tmp.exists():
                with contextlib.suppress(OSError):
                    tmp.unlink()

    async def get(self, key: str) -> str | None:
        """Return plaintext for ``key`` from the encrypted store.

        Args:
            key (str): Logical secret id.

        Returns:
            str | None: Plaintext if present, ``None`` if key is missing.

        Raises:
            SecretsStoreCorruptError: If the store file exists but cannot be decrypted
                or parsed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EncryptedFileBackend.get)
            True
        """
        try:
            m = await asyncio.to_thread(self._load_map_sync)
        except SecretsStoreCorruptError:
            raise
        return m.get(key)

    async def load_decrypted_map(self) -> dict[str, str]:
        """Decrypt and return the full logical-key map (operator tooling).

        Values remain confidential — callers must not log raw secrets.

        Returns:
            dict[str, str]: Decrypted map (empty dict when file absent).

        Raises:
            SecretsStoreCorruptError: When ciphertext cannot be authenticated.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EncryptedFileBackend.load_decrypted_map)
            True
        """
        try:
            return await asyncio.to_thread(self._load_map_sync)
        except SecretsStoreCorruptError:
            raise

    async def set(self, key: str, value: str) -> None:
        """Persist ``value`` for ``key`` (replace semantics).

        Args:
            key (str): Logical secret id.
            value (str): UTF-8 plaintext to store.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EncryptedFileBackend.set)
            True
        """

        def _do() -> None:
            m = self._load_map_sync()
            m[key] = value
            self._save_map_sync(m)

        await asyncio.to_thread(_do)

    async def delete(self, key: str) -> None:
        """Remove ``key`` from the store if present; remove file when empty.

        Args:
            key (str): Logical secret id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EncryptedFileBackend.delete)
            True
        """

        def _do() -> None:
            if not self._path.exists():
                return
            m = self._load_map_sync()
            m.pop(key, None)
            if not m:
                self._path.unlink(missing_ok=True)
                return
            self._save_map_sync(m)

        await asyncio.to_thread(_do)
