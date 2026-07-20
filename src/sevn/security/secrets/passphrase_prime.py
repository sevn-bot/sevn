"""Self-unlock: prime the encrypted-store key var from the OS keychain at daemon boot.

Module: sevn.security.secrets.passphrase_prime
Depends: os, sevn.security.secrets.backends.macos_keychain

Exports:
    unlock_env_var_for — the env var name a key_source unlocks with.
    fetch_unlock_secret_from_keychain — read unlock secret from login Keychain.
    keychain_has_unlock_secret — whether the keychain holds the active unlock var.
    prime_unlock_env_from_keychain — set the unlock var from Keychain when unset.
    reconcile_unlock_env_with_keychain — prefer Keychain over stale session env.
    log_unlock_env_conflict — log genuine unlock-env conflicts at WARNING (D13).

Rationale (`specs/06-secrets.md`): the gateway/proxy run as a per-user LaunchAgent whose plist
embeds no unlock secret. ``propagate_daemon_secret_env`` mirrors the shell passphrase into the
launchd session via ``launchctl setenv``, but that is wiped on logout — so after reboot the daemon
boots with no key and the encrypted store stays locked. Reading the passphrase from the macOS login
Keychain (unlocked by the OS at login) lets the LaunchAgent self-unlock every session without any
session env. We read the item **directly from a Keychain backend**, not the configured secrets
chain, because the store may be ``encrypted_file``-only and you cannot unlock that file with a key
stored inside it.
"""

from __future__ import annotations

import os
import sys

from loguru import logger

from sevn.security.secrets.backends.macos_keychain import MacOSKeychainBackend


def unlock_env_var_for(key_source: str) -> str:
    """Return the env var that unlocks the encrypted store for ``key_source``.

    Args:
        key_source (str): ``"master_key"`` or ``"passphrase"`` (anything else → passphrase).

    Returns:
        str: ``"SEVN_SECRETS_MASTER_KEY"`` for master_key mode, else ``"SEVN_SECRETS_PASSPHRASE"``.

    Examples:
        >>> unlock_env_var_for("master_key")
        'SEVN_SECRETS_MASTER_KEY'
        >>> unlock_env_var_for("passphrase")
        'SEVN_SECRETS_PASSPHRASE'
    """
    return "SEVN_SECRETS_MASTER_KEY" if key_source == "master_key" else "SEVN_SECRETS_PASSPHRASE"


async def keychain_has_unlock_secret(*, key_source: str, service: str | None = None) -> bool:
    """Return whether the macOS Keychain holds the active unlock var for ``key_source``.

    Args:
        key_source (str): ``"master_key"`` or ``"passphrase"``.
        service (str | None): Keychain service name; ``None`` uses the backend default.

    Returns:
        bool: True when the item is present (always False off-Darwin).

    Examples:
        >>> import asyncio
        >>> asyncio.run(keychain_has_unlock_secret(key_source="passphrase")) in (True, False)
        True
    """
    var = unlock_env_var_for(key_source)
    value = await MacOSKeychainBackend(service=service).get(var)
    return bool(value and value.strip())


async def fetch_unlock_secret_from_keychain(
    *,
    key_source: str,
    service: str | None = None,
) -> str | None:
    """Return the unlock secret stored in the macOS login Keychain, if any.

    Args:
        key_source (str): ``"master_key"`` or ``"passphrase"``.
        service (str | None): Keychain service name; ``None`` uses the backend default.

    Returns:
        str | None: Trimmed unlock secret, or ``None`` off-Darwin / when absent.

    Examples:
        >>> import asyncio
        >>> asyncio.run(fetch_unlock_secret_from_keychain(key_source="passphrase")) is None or isinstance(
        ...     asyncio.run(fetch_unlock_secret_from_keychain(key_source="passphrase")), str
        ... )
        True
    """
    if sys.platform != "darwin":
        return None
    var = unlock_env_var_for(key_source)
    value = await MacOSKeychainBackend(service=service).get(var)
    if value and value.strip():
        return value.strip()
    return None


def log_unlock_env_conflict(
    *,
    var: str,
    env_value: str,
    keychain_value: str,
    reason: str,
) -> None:
    """Log a genuine unlock-env conflict at WARNING (D13).

    Routine stale-shell replacement uses INFO via
    :func:`reconcile_unlock_env_with_keychain`; call this only for unexpected
    conflicts where both sources are set and disagree in a non-routine way.

    Args:
        var (str): Env var name (``SEVN_SECRETS_PASSPHRASE`` or ``SEVN_SECRETS_MASTER_KEY``).
        env_value (str): Value currently in the process environment.
        keychain_value (str): Value read from Keychain.
        reason (str): Short classifier (e.g. ``unexpected_conflict``).

    Examples:
        >>> log_unlock_env_conflict(
        ...     var="SEVN_SECRETS_PASSPHRASE",
        ...     env_value="a",
        ...     keychain_value="b",
        ...     reason="unexpected_conflict",
        ... )
    """
    logger.warning(
        "secrets_unlock_env_conflict var={} reason={} env_len={} keychain_len={}",
        var,
        reason,
        len(env_value),
        len(keychain_value),
    )


async def reconcile_unlock_env_with_keychain(
    *, key_source: str, service: str | None = None
) -> bool:
    """Prefer the Keychain unlock secret over a stale process/session env value.

    Onboarding mirrors the wizard passphrase into the login Keychain with ``-A`` so LaunchAgents
    can self-unlock after logout. A stale ``launchctl setenv`` or shell export can still leave the
    wrong ``SEVN_SECRETS_*`` value in the daemon session and trip ``AEAD decrypt failed`` on first
    boot even after a clean onboard — this helper replaces a mismatched env value with the
    Keychain copy before the secrets chain is opened.

    Args:
        key_source (str): ``"master_key"`` or ``"passphrase"``.
        service (str | None): Keychain service name; ``None`` uses the backend default.

    Returns:
        bool: True when ``os.environ`` was updated from Keychain.

    Examples:
        >>> import asyncio
        >>> asyncio.run(reconcile_unlock_env_with_keychain(key_source="passphrase")) in (True, False)
        True
    """
    kc_val = await fetch_unlock_secret_from_keychain(key_source=key_source, service=service)
    if not kc_val:
        return await prime_unlock_env_from_keychain(key_source=key_source, service=service)
    var = unlock_env_var_for(key_source)
    env_val = os.environ.get(var, "").strip()
    if env_val == kc_val:
        return False
    if env_val:
        logger.info(
            "secrets_unlock_env_stale_replaced var={} — shell/session value differed from "
            "keychain; using keychain unlock secret written during onboard",
            var,
        )
    os.environ[var] = kc_val
    return True


async def prime_unlock_env_from_keychain(*, key_source: str, service: str | None = None) -> bool:
    """Prime the active unlock env var from the macOS login Keychain when it is unset.

    Reads the item directly from a Keychain backend (independent of the configured secrets chain)
    so it works even when the store is ``encrypted_file``-only. No-op when the var is already set,
    when the keychain has no value, or off-Darwin.

    Args:
        key_source (str): ``"master_key"`` or ``"passphrase"`` (default).
        service (str | None): Keychain service name; ``None`` uses the backend default.

    Returns:
        bool: True when a value was fetched and primed into ``os.environ``.

    Examples:
        >>> import asyncio
        >>> os.environ["SEVN_SECRETS_PASSPHRASE"] = "already-set"
        >>> asyncio.run(prime_unlock_env_from_keychain(key_source="passphrase"))
        False
        >>> _ = os.environ.pop("SEVN_SECRETS_PASSPHRASE", None)
    """
    var = unlock_env_var_for(key_source)
    if os.environ.get(var, "").strip():
        return False
    value = await MacOSKeychainBackend(service=service).get(var)
    if value and value.strip():
        os.environ[var] = value.strip()
        return True
    return False


__all__ = [
    "fetch_unlock_secret_from_keychain",
    "keychain_has_unlock_secret",
    "log_unlock_env_conflict",
    "prime_unlock_env_from_keychain",
    "reconcile_unlock_env_with_keychain",
    "unlock_env_var_for",
]
