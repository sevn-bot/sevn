"""Concrete secret backends (``specs/06-secrets.md`` §4.1).

This package uses optional native dependencies where required; unsupported
environments surface as missing keys rather than crashing on import.
"""

from __future__ import annotations

from sevn.security.secrets.backends.bitwarden import BitwardenCliBackend
from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend
from sevn.security.secrets.backends.linux_secret_service import LinuxSecretServiceBackend
from sevn.security.secrets.backends.macos_keychain import MacOSKeychainBackend
from sevn.security.secrets.backends.one_password import OnePasswordCliBackend
from sevn.security.secrets.backends.openbao import OpenBaoBackend
from sevn.security.secrets.backends.proton_pass import ProtonPassCliBackend

__all__ = [
    "BitwardenCliBackend",
    "EncryptedFileBackend",
    "LinuxSecretServiceBackend",
    "MacOSKeychainBackend",
    "OnePasswordCliBackend",
    "OpenBaoBackend",
    "ProtonPassCliBackend",
]
