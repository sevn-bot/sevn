"""Persist wizard-collected secrets outside ``sevn.json`` (onboarding only).

Module: sevn.onboarding.wizard_credentials
Depends: sevn.security.secrets.factory, sevn.config.workspace_config

Exports:
    store_wizard_credentials — write operator tokens into workspace secrets chain.
    credentials_status — which required wizard secrets are present.
    get_wizard_credential — read one wizard secret using the configured backend chain.
    probe_host_github_token — read GitHub token from host env/keychain/gh CLI only.
    delete_wizard_credential — remove one secret from the workspace chain.
    secrets_section_from_sevn_json — parse ``secrets_backend`` from promoted config.
    default_wizard_secrets_section — wizard default encrypted-file backend section.
    resolve_wizard_secrets_section — promoted section or encrypted-file default.
    unlock_wizard_keystore — verify passphrase and unlock encrypted store.
    verify_wizard_passphrase — verify passphrase before wizard proceeds.
    read_wizard_credential_values — read wizard secrets after unlock for prefill.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from sevn.config.provider_secrets import (
    assigned_provider_names_from_doc,
    handoff_provider_secret_keys,
    provider_secret_alias,
)
from sevn.config.workspace_config import (
    EncryptedFileBackendEntry,
    SecretsBackendSectionConfig,
    effective_encrypted_file_key_source,
    parse_workspace_config,
)
from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend
from sevn.security.secrets.backends.macos_keychain import MacOSKeychainBackend
from sevn.security.secrets.chain import SecretsChain
from sevn.security.secrets.errors import SecretsStoreCorruptError
from sevn.security.secrets.factory import (
    resolve_primary_encrypted_store_path,
    secrets_chain_from_workspace,
)

# Keep in sync with ``sevn.gateway.runtime.gateway_token.GATEWAY_TOKEN_LOGICAL_KEY``.
_GATEWAY_TOKEN_LOGICAL_KEY = "sevn.gateway.token"  # nosec B105
_GITHUB_TOKEN_LOGICAL_KEY = "integration.github.token"  # nosec B105

WIZARD_SECRET_KEYS = (
    _GATEWAY_TOKEN_LOGICAL_KEY,
    _GITHUB_TOKEN_LOGICAL_KEY,
    "SEVN_TELEGRAM_BOT_TOKEN",
    "SEVN_TELEGRAM_API_ID",
    "SEVN_TELEGRAM_API_HASH",
    "SEVN_TELEGRAM_PHONE",
    "SEVN_SECRETS_PASSPHRASE",
)

REQUIRED_FOR_HANDOFF = (
    _GATEWAY_TOKEN_LOGICAL_KEY,
    "SEVN_TELEGRAM_BOT_TOKEN",
)

READABLE_WIZARD_KEYS = (
    _GATEWAY_TOKEN_LOGICAL_KEY,
    "SEVN_TELEGRAM_BOT_TOKEN",
    "SEVN_TELEGRAM_API_ID",
    "SEVN_TELEGRAM_API_HASH",
    "SEVN_TELEGRAM_PHONE",
    "SEVN_SECRETS_PASSPHRASE",
)


def default_wizard_secrets_section() -> SecretsBackendSectionConfig:
    """Return the wizard's default ``encrypted_file``-only secrets backend.

    Matches ``normalize_secrets_backend_section`` / web wizard defaults so early credential
    saves land in ``store.enc`` instead of the macOS host-default Keychain-first chain.

    Returns:
        SecretsBackendSectionConfig: Encrypted-file-only backend section.

    Examples:
        >>> sec = default_wizard_secrets_section()
        >>> sec.chain[0].type
        'encrypted_file'
    """
    return SecretsBackendSectionConfig(
        chain=[EncryptedFileBackendEntry(path=".sevn/secrets/store.enc")],
    )


def resolve_wizard_secrets_section(
    section: SecretsBackendSectionConfig | None,
) -> SecretsBackendSectionConfig:
    """Return ``section`` when set, else the wizard encrypted-file default.

    Args:
        section (SecretsBackendSectionConfig | None): Promoted or draft backend section.

    Returns:
        SecretsBackendSectionConfig: Section used for wizard credential writes.

    Examples:
        >>> resolve_wizard_secrets_section(None).chain[0].type
        'encrypted_file'
    """
    return section if section is not None else default_wizard_secrets_section()


def _sections_for_read(
    section: SecretsBackendSectionConfig | None,
    *,
    workspace_only: bool = False,
) -> list[SecretsBackendSectionConfig | None]:
    """Return backend sections to probe when loading wizard secrets for prefill.

    Args:
        section (SecretsBackendSectionConfig | None): Promoted ``secrets_backend``.
        workspace_only (bool): When True, never fall back to the host-default chain
            (macOS Keychain / host env outside the workspace encrypted store).

    Returns:
        list[SecretsBackendSectionConfig | None]: Configured section first, then host default.

    Examples:
        >>> _sections_for_read(None)
        [None]
        >>> len(_sections_for_read(None, workspace_only=True))
        1
    """
    if workspace_only:
        return [resolve_wizard_secrets_section(section)]
    if section is None:
        return [None]
    return [section, None]


async def get_wizard_credential(
    content_root: Path,
    key: str,
    *,
    section: SecretsBackendSectionConfig | None = None,
    workspace_only: bool = False,
) -> str | None:
    """Read one wizard credential the same way ``credentials_status`` does.

    Args:
        content_root (Path): Workspace content root.
        key (str): Logical secret id (for example ``SEVN_TELEGRAM_BOT_TOKEN``).
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.
        workspace_only (bool): When True, read only from this workspace's configured
            backend chain (never the host-default macOS Keychain fallback).

    Returns:
        str | None: Trimmed plaintext when present in env or any probed backend.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(get_wizard_credential(Path("."), "MISSING_KEY")) is None
        True
    """
    for sec in _sections_for_read(section, workspace_only=workspace_only):
        chain = _secrets_chain(content_root, sec)
        val = await _get_key_resilient(chain, key)
        if val:
            return val
    return None


async def probe_host_github_token() -> tuple[str | None, str | None]:
    """Read a GitHub token from host-level stores (not the workspace encrypted file).

    Returns:
        tuple[str | None, str | None]: ``(token, source)`` where ``source`` is one of
            ``env``, ``keychain``, ``gh_cli``, or ``None`` when nothing is found.

    Examples:
        >>> import asyncio
        >>> tok, src = asyncio.run(probe_host_github_token())
        >>> tok is None or isinstance(tok, str)
        True
    """
    env_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if env_token:
        return env_token, "env"
    if sys.platform == "darwin" and not os.environ.get("SEVN_DISABLE_KEYCHAIN", "").strip():
        keychain_val = await MacOSKeychainBackend().get(_GITHUB_TOKEN_LOGICAL_KEY)
        if keychain_val:
            return keychain_val, "keychain"
    gh_token = await _gh_auth_token()
    if gh_token:
        return gh_token, "gh_cli"
    return None, None


async def _gh_auth_token() -> str | None:
    """Return the active GitHub CLI OAuth token when ``gh`` is installed and logged in.

    Returns:
        str | None: Token string or ``None`` when ``gh auth token`` is unavailable.

    Examples:
        >>> import asyncio
        >>> asyncio.run(_gh_auth_token()) is None or isinstance(asyncio.run(_gh_auth_token()), str)
        True
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "auth",
            "token",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        return None
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    text = stdout.decode("utf-8", errors="replace").strip()
    return text or None


async def delete_wizard_credential(
    content_root: Path,
    key: str,
    *,
    section: SecretsBackendSectionConfig | None = None,
) -> bool:
    """Remove one wizard credential from the workspace secrets chain only.

    Args:
        content_root (Path): Workspace content root.
        key (str): Logical secret id.
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.

    Returns:
        bool: True when a delete was attempted on the workspace chain.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(
        ...     delete_wizard_credential(Path("/nonexistent"), "integration.github.token")
        ... ) in (True, False)
        True
    """
    chain = _secrets_chain(content_root, resolve_wizard_secrets_section(section))
    try:
        await chain.delete(key)
    except Exception:
        return False
    return True


def secrets_section_from_sevn_json(sevn_json: Path) -> SecretsBackendSectionConfig | None:
    """Parse ``secrets_backend`` from promoted ``sevn.json`` when present.

    Args:
        sevn_json (Path): Promoted config path.

    Returns:
        SecretsBackendSectionConfig | None: Parsed section, or ``None`` when missing.

    Examples:
        >>> secrets_section_from_sevn_json(Path("/nonexistent/sevn.json")) is None
        True
    """
    if not sevn_json.is_file():
        return None
    try:
        raw = json.loads(sevn_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return parse_workspace_config(raw).secrets_backend
    except (ValueError, TypeError):
        return None


def _is_missing_passphrase_error(exc: SecretsStoreCorruptError) -> bool:
    """Return True when the encrypted store exists but no passphrase is configured.

    Args:
        exc (SecretsStoreCorruptError): Raised while opening the store.

    Returns:
        bool: True for missing-passphrase errors only.

    Examples:
        >>> from sevn.security.secrets.errors import is_encrypted_store_unlock_error
        >>> _is_missing_passphrase_error(
        ...     SecretsStoreCorruptError("encrypted store needs passphrase or master_key")
        ... )
        True
    """
    msg = str(exc).lower()
    return "needs passphrase" in msg or "missing passphrase" in msg


def _is_wrong_passphrase_error(exc: SecretsStoreCorruptError) -> bool:
    """Return True when decryption failed due to a bad passphrase/key.

    Args:
        exc (SecretsStoreCorruptError): Raised while decrypting the store.

    Returns:
        bool: True for AEAD authentication failures.

    Examples:
        >>> _is_wrong_passphrase_error(
        ...     SecretsStoreCorruptError("AEAD decrypt failed (corrupt or wrong key)")
        ... )
        True
    """
    msg = str(exc).lower()
    return "aead decrypt failed" in msg or "wrong key" in msg


def _clear_stale_secrets_unlock_env() -> None:
    """Drop stale unlock env vars so the wizard can prompt for a fresh passphrase.

    Examples:
        >>> _clear_stale_secrets_unlock_env() is None
        True
    """
    os.environ.pop("SEVN_SECRETS_PASSPHRASE", None)
    os.environ.pop("SEVN_SECRETS_MASTER_KEY", None)


async def _get_key_resilient(chain: SecretsChain, key: str) -> str | None:
    """Read one logical key, skipping backends that need an unlock passphrase.

    Args:
        chain (SecretsChain): Workspace secrets chain.
        key (str): Logical secret id.

    Returns:
        str | None: Plaintext when found in env or any backend.

    Examples:
        >>> import asyncio
        >>> from sevn.onboarding.wizard_credentials import _get_key_resilient, _secrets_chain
        >>> from pathlib import Path
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> asyncio.run(_get_key_resilient(_secrets_chain(td), "___doctest_missing_wizard_key___")) is None
        True
    """
    try:
        return await chain.get_resilient(key)
    except SecretsStoreCorruptError as exc:
        if _is_wrong_passphrase_error(exc) or _is_missing_passphrase_error(exc):
            _clear_stale_secrets_unlock_env()
            return None
        raise


def _present_from_env() -> dict[str, bool]:
    """Return which wizard keys are currently primed in ``os.environ``.

    Returns:
        dict[str, bool]: Key → present map for ``WIZARD_SECRET_KEYS``.

    Examples:
        >>> isinstance(_present_from_env(), dict)
        True
    """
    return {key: bool(os.environ.get(key, "").strip()) for key in WIZARD_SECRET_KEYS}


def _encrypted_store_file_if_present(
    content_root: Path,
    section: SecretsBackendSectionConfig | None,
) -> Path | None:
    """Return the encrypted store path when the file exists on disk.

    Args:
        content_root (Path): Workspace content root.
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.

    Returns:
        Path | None: Store path when present, else ``None``.

    Examples:
        >>> _encrypted_store_file_if_present(Path('/nonexistent'), None) is None
        True
    """
    store = resolve_primary_encrypted_store_path(content_root.resolve(), section)
    return store if store.is_file() else None


async def _encrypted_store_needs_passphrase(
    content_root: Path,
    section: SecretsBackendSectionConfig | None,
) -> bool:
    """Return True when an on-disk encrypted store exists but cannot be opened yet.

    Args:
        content_root (Path): Workspace content root.
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.

    Returns:
        bool: True when the operator must supply ``SEVN_SECRETS_PASSPHRASE``.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(_encrypted_store_needs_passphrase(Path('.'), None)) in (True, False)
        True
    """
    if os.environ.get("SEVN_SECRETS_PASSPHRASE", "").strip():
        chain = _secrets_chain(content_root, section)
        for backend in chain.backends:
            if isinstance(backend, EncryptedFileBackend):
                try:
                    await backend.get("__wizard_lock_probe__")
                    return False
                except SecretsStoreCorruptError as exc:
                    if _is_wrong_passphrase_error(exc) or _is_missing_passphrase_error(exc):
                        _clear_stale_secrets_unlock_env()
                        return True
                    raise
                return False
    store = await asyncio.to_thread(_encrypted_store_file_if_present, content_root, section)
    if store is None:
        return False
    chain = _secrets_chain(content_root, section)
    for backend in chain.backends:
        if isinstance(backend, EncryptedFileBackend):
            try:
                await backend.get("__wizard_lock_probe__")
            except SecretsStoreCorruptError as exc:
                if _is_missing_passphrase_error(exc) or _is_wrong_passphrase_error(exc):
                    return True
                raise
            return False
    return False


def _secrets_chain(
    content_root: Path,
    section: SecretsBackendSectionConfig | None = None,
) -> SecretsChain:
    """Build the workspace secrets chain for onboarding writes.

    Args:
        content_root (Path): Resolved workspace content root.
        section (SecretsBackendSectionConfig | None): Operator-chosen backend
            section (from the wizard's draft); ``None`` falls back to the
            host-default chain (macOS keychain → encrypted_file).

    Returns:
        SecretsChain: Chain configured per the chosen section.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.onboarding.wizard_credentials import _secrets_chain
        >>> _secrets_chain(Path(".")).__class__.__name__
        'SecretsChain'
    """
    return secrets_chain_from_workspace(content_root.resolve(), section)


def _ensure_credential_dirs(content_root: Path) -> None:
    """Create workspace and ``.sevn`` directories (sync helper for ``to_thread``).

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        None: Directories exist after return.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.wizard_credentials import _ensure_credential_dirs
        >>> root = Path(tempfile.mkdtemp()) / "w"
        >>> _ensure_credential_dirs(root)
        >>> (root / ".sevn").is_dir()
        True
    """
    content_root.mkdir(parents=True, exist_ok=True)
    (content_root / ".sevn").mkdir(parents=True, exist_ok=True)


async def store_wizard_credentials(
    content_root: Path,
    *,
    gateway_token: str | None = None,
    github_token: str | None = None,
    openwiki_llm_api_key: str | None = None,
    bot_token: str | None = None,
    provider_api_keys: dict[str, str] | None = None,
    telegram_api_id: str | None = None,
    telegram_api_hash: str | None = None,
    telegram_phone: str | None = None,
    secrets_passphrase: str | None = None,
    master_key_hex: str | None = None,
    section: SecretsBackendSectionConfig | None = None,
) -> dict[str, bool]:
    """Store non-empty credential strings in the workspace secrets chain.

    The encrypted-file store is sealed in the mode the ``section`` declares (``key_source``):
    ``passphrase`` (default) primes ``SEVN_SECRETS_PASSPHRASE``; ``master_key`` primes
    ``SEVN_SECRETS_MASTER_KEY`` from ``master_key_hex``. Exactly one unlock credential is primed
    so the store seals under the declared mechanism.

    Args:
        content_root (Path): Resolved workspace content root.
        gateway_token (str | None): Gateway bearer token (stored as ``sevn.gateway.token``).
        github_token (str | None): GitHub OAuth/PAT (``integration.github.token``).
        openwiki_llm_api_key (str | None): OpenWiki LLM API key
            (``integration.openwiki.llm_api_key``).
        bot_token (str | None): Telegram bot token from BotFather.
        provider_api_keys (dict[str, str] | None): Per-provider plaintext keys stored as
            ``SEVN_SECRET_{PROVIDER}`` for each assigned registry name.
        telegram_api_id (str | None): my.telegram.org API id.
        telegram_api_hash (str | None): my.telegram.org API hash.
        telegram_phone (str | None): Phone used for user API.
        secrets_passphrase (str | None): Passphrase for the encrypted_file
            backend; persisted as ``SEVN_SECRETS_PASSPHRASE`` and primed in
            ``os.environ`` so the same process can encrypt/decrypt (passphrase mode).
        master_key_hex (str | None): 64-hex raw key primed as ``SEVN_SECRETS_MASTER_KEY``
            when the section's ``key_source`` is ``master_key``.
        section (SecretsBackendSectionConfig | None): Operator-chosen
            ``secrets_backend`` block from the wizard draft. When provided,
            credentials route through this chain instead of the host default
            (so a user who picks ``encrypted_file`` actually lands secrets in
            that file rather than the OS keychain).

    Raises:
        ValueError: When ``key_source`` is ``master_key`` but no ``master_key_hex`` is given.

    Returns:
        dict[str, bool]: Key → whether value was written this call.

    Examples:
        >>> import asyncio
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import (
        ...     EncryptedFileBackendEntry,
        ...     SecretsBackendSectionConfig,
        ... )
        >>> from sevn.onboarding.wizard_credentials import store_wizard_credentials
        >>> td = Path(tempfile.mkdtemp())
        >>> section = SecretsBackendSectionConfig(
        ...     chain=[EncryptedFileBackendEntry(path=".sevn/secrets/store.enc")],
        ... )
        >>> out = asyncio.run(
        ...     store_wizard_credentials(
        ...         td,
        ...         bot_token="tok",
        ...         provider_api_keys={"minimax": "key"},
        ...         secrets_passphrase="doctest-pass",
        ...         section=section,
        ...     ),
        ... )
        >>> out["SEVN_TELEGRAM_BOT_TOKEN"] and out["SEVN_SECRET_MINIMAX"]
        True
    """
    await asyncio.to_thread(_ensure_credential_dirs, content_root)
    # Prime the unlock credential for the declared key_source in env BEFORE building the chain
    # so the encrypted_file backend seals on first write under the right mechanism.
    key_source = effective_encrypted_file_key_source(section)
    if key_source == "master_key":
        mk = (master_key_hex or "").strip()
        if not mk:
            msg = (
                "secrets_backend.encrypted_file.key_source=master_key requires a 64-hex "
                "SEVN_SECRETS_MASTER_KEY value (master_key_hex)"
            )
            raise ValueError(msg)
        os.environ["SEVN_SECRETS_MASTER_KEY"] = mk
    elif secrets_passphrase and str(secrets_passphrase).strip():
        os.environ["SEVN_SECRETS_PASSPHRASE"] = str(secrets_passphrase).strip()
    chain = _secrets_chain(content_root, section)
    written: dict[str, bool] = {}
    gw_tok = (gateway_token or "").strip()
    if gw_tok:
        await chain.set(_GATEWAY_TOKEN_LOGICAL_KEY, gw_tok)
        written[_GATEWAY_TOKEN_LOGICAL_KEY] = True
    gh_tok = (github_token or "").strip()
    if gh_tok:
        await chain.set(_GITHUB_TOKEN_LOGICAL_KEY, gh_tok)
        written[_GITHUB_TOKEN_LOGICAL_KEY] = True
    ow_key = (openwiki_llm_api_key or "").strip()
    if ow_key:
        from sevn.skills.openwiki_secrets import OPENWIKI_LLM_API_KEY_SECRET

        await chain.set(OPENWIKI_LLM_API_KEY_SECRET, ow_key)
        written[OPENWIKI_LLM_API_KEY_SECRET] = True
    pairs: list[tuple[str, str | None]] = [
        ("SEVN_TELEGRAM_BOT_TOKEN", bot_token),
        ("SEVN_TELEGRAM_API_ID", telegram_api_id),
        ("SEVN_TELEGRAM_API_HASH", telegram_api_hash),
        ("SEVN_TELEGRAM_PHONE", telegram_phone),
    ]
    if provider_api_keys:
        for name, val in provider_api_keys.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if val is None or not str(val).strip():
                continue
            pairs.append((provider_secret_alias(name.strip()), str(val).strip()))
    # Persist the passphrase inside the store only in passphrase mode (raw-key stores have no
    # passphrase to keep, and storing the master key inside its own store is pointless).
    if key_source != "master_key":
        pairs.append(("SEVN_SECRETS_PASSPHRASE", secrets_passphrase))
    for logical_key, plain in pairs:
        if plain is None or not str(plain).strip():
            continue
        text = str(plain).strip()
        await chain.set(logical_key, text)
        written[logical_key] = True
        if logical_key in (
            "SEVN_TELEGRAM_BOT_TOKEN",
            "SEVN_SECRETS_PASSPHRASE",
        ):
            os.environ[logical_key] = text
    await _mirror_unlock_secret_to_keychain(
        key_source=key_source,
        secrets_passphrase=secrets_passphrase,
        master_key_hex=master_key_hex,
    )
    return written


async def _mirror_unlock_secret_to_keychain(
    *,
    key_source: str,
    secrets_passphrase: str | None,
    master_key_hex: str | None,
) -> None:
    """Best-effort: write the active unlock secret into the macOS Keychain for daemon self-unlock.

    Stored with ``-A`` (any app may read, no GUI prompt) so the per-user LaunchAgent can open the
    encrypted store at every login without ``launchctl setenv`` — which is wiped on logout. The
    login Keychain itself stays the lock boundary. No-op off macOS; failures are logged, never fatal
    (onboarding must still complete).

    Args:
        key_source (str): ``"passphrase"`` or ``"master_key"``.
        secrets_passphrase (str | None): Passphrase value (passphrase mode).
        master_key_hex (str | None): Master key hex (master_key mode).

    Examples:
        >>> import asyncio
        >>> asyncio.run(
        ...     _mirror_unlock_secret_to_keychain(
        ...         key_source="passphrase", secrets_passphrase=None, master_key_hex=None
        ...     )
        ... ) is None
        True
    """
    if sys.platform != "darwin":
        return
    if key_source == "master_key":
        var, value = "SEVN_SECRETS_MASTER_KEY", (master_key_hex or "").strip()
    else:
        var, value = "SEVN_SECRETS_PASSPHRASE", (secrets_passphrase or "").strip()
    if not value:
        return
    try:
        await MacOSKeychainBackend().set(var, value, allow_any_app=True)
        logger.info("onboarding_mirrored_unlock_secret_to_keychain var={}", var)
    except Exception as exc:
        logger.warning(
            "onboarding_keychain_unlock_mirror_failed var={} err={} — daemon self-unlock after "
            "reboot will need `sevn secrets store-passphrase` or an exported {}.",
            var,
            exc,
            var,
        )


async def credentials_status(
    content_root: Path,
    *,
    section: SecretsBackendSectionConfig | None = None,
    config_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Report which wizard secrets exist in the chain or process env.

    Args:
        content_root (Path): Workspace content root.
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend``
            block from promoted ``sevn.json``; ``None`` uses host defaults.
        config_doc (dict[str, Any] | None): When set, ``ready_for_handoff`` also
            requires Telegram token (if enabled) and assigned provider secrets.

    Returns:
        dict[str, Any]: ``present`` map, ``ready_for_handoff``, and lock flags.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.onboarding.wizard_credentials import credentials_status
        >>> asyncio.run(credentials_status(Path(".")))["ready_for_handoff"] in (True, False)
        True
    """
    present: dict[str, bool] = {}
    for key in WIZARD_SECRET_KEYS:
        found = False
        key_workspace_only = key == _GITHUB_TOKEN_LOGICAL_KEY
        for sec in _sections_for_read(section, workspace_only=key_workspace_only):
            chain = _secrets_chain(content_root, sec)
            val = await _get_key_resilient(chain, key)
            if val:
                present[key] = True
                found = True
                break
        if not found:
            present[key] = bool(os.environ.get(key, "").strip())

    if config_doc is not None:
        channels = config_doc.get("channels")
        tg_enabled = (
            isinstance(channels, dict)
            and isinstance(channels.get("telegram"), dict)
            and bool(channels["telegram"].get("enabled"))
        )
        if tg_enabled:
            tg_ok = present.get("SEVN_TELEGRAM_BOT_TOKEN", False)
            present["SEVN_TELEGRAM_BOT_TOKEN"] = tg_ok
        for alias in handoff_provider_secret_keys(config_doc):
            found = False
            for sec in _sections_for_read(section):
                chain = _secrets_chain(content_root, sec)
                val = await _get_key_resilient(chain, alias)
                if val:
                    present[alias] = True
                    found = True
                    break
            if not found:
                present[alias] = bool(os.environ.get(alias, "").strip())

    locked = await _encrypted_store_needs_passphrase(content_root, section)
    ready_keys: list[str] = list(REQUIRED_FOR_HANDOFF)
    if config_doc is not None:
        channels = config_doc.get("channels")
        if (
            isinstance(channels, dict)
            and isinstance(channels.get("telegram"), dict)
            and bool(channels["telegram"].get("enabled"))
        ):
            ready_keys.append("SEVN_TELEGRAM_BOT_TOKEN")
        ready_keys.extend(sorted(handoff_provider_secret_keys(config_doc)))
    ready = all(present.get(k) for k in ready_keys)
    return {
        "present": present,
        "ready_for_handoff": ready,
        "keystore_locked": locked,
        "needs_passphrase": locked,
    }


async def read_wizard_credential_values(
    content_root: Path,
    *,
    section: SecretsBackendSectionConfig | None = None,
    provider_names: frozenset[str] | None = None,
) -> dict[str, str]:
    """Read wizard credential plaintext from the unlocked secrets chain.

    Args:
        content_root (Path): Workspace content root.
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.
        provider_names (frozenset[str] | None): When set, also read
            ``SEVN_SECRET_{PROVIDER}`` values for prefill.

    Returns:
        dict[str, str]: Env-key → plaintext for readable wizard keys.

    Examples:
        >>> import asyncio
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.wizard_credentials import read_wizard_credential_values
        >>> isinstance(asyncio.run(read_wizard_credential_values(Path(tempfile.mkdtemp()))), dict)
        True
    """
    out: dict[str, str] = {}
    for sec in _sections_for_read(section):
        chain = _secrets_chain(content_root, sec)
        for key in READABLE_WIZARD_KEYS:
            if key in out:
                continue
            val = await _get_key_resilient(chain, key)
            if val:
                out[key] = val
        if provider_names:
            for name in provider_names:
                alias = provider_secret_alias(name)
                if alias in out:
                    continue
                val = await _get_key_resilient(chain, alias)
                if val:
                    out[alias] = val
    return out


async def unlock_wizard_keystore(
    content_root: Path,
    passphrase: str,
    *,
    section: SecretsBackendSectionConfig | None = None,
) -> dict[str, Any]:
    """Prime ``SEVN_SECRETS_PASSPHRASE`` and verify the encrypted store opens.

    Args:
        content_root (Path): Workspace content root.
        passphrase (str): Operator-supplied passphrase for ``encrypted_file``.
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.

    Returns:
        dict[str, Any]: ``ok`` flag plus ``credentials_status`` fields on success.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.onboarding.wizard_credentials import unlock_wizard_keystore
        >>> asyncio.run(unlock_wizard_keystore(Path("."), "test"))["ok"] in (True, False)
        True
    """
    text = str(passphrase).strip()
    if not text:
        return {"ok": False, "detail": "passphrase is required"}
    os.environ["SEVN_SECRETS_PASSPHRASE"] = text
    try:
        status = await credentials_status(content_root, section=section)
    except SecretsStoreCorruptError as exc:
        _clear_stale_secrets_unlock_env()
        if _is_wrong_passphrase_error(exc) or _is_missing_passphrase_error(exc):
            return {"ok": False, "detail": "Incorrect passphrase"}
        raise
    if status.get("needs_passphrase"):
        _clear_stale_secrets_unlock_env()
        return {"ok": False, "detail": "Incorrect passphrase"}
    return {"ok": True, **status}


async def verify_wizard_passphrase(
    content_root: Path,
    passphrase: str,
    *,
    section: SecretsBackendSectionConfig | None = None,
) -> dict[str, Any]:
    """Verify an encrypted-file passphrase before the wizard proceeds.

    When ``store.enc`` already exists, the passphrase must decrypt it. For a fresh
    install with no store yet, a non-empty passphrase is accepted.

    Args:
        content_root (Path): Workspace content root.
        passphrase (str): Operator-supplied passphrase.
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.

    Returns:
        dict[str, Any]: ``ok`` flag and optional ``detail`` on failure.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.onboarding.wizard_credentials import verify_wizard_passphrase
        >>> asyncio.run(verify_wizard_passphrase(Path("."), ""))["ok"] is False
        True
    """
    text = str(passphrase).strip()
    if not text:
        return {"ok": False, "detail": "passphrase is required"}
    cfg = section if section is not None else SecretsBackendSectionConfig()
    store_path = resolve_primary_encrypted_store_path(content_root, cfg)
    if store_path.is_file():
        return await unlock_wizard_keystore(content_root, text, section=section)
    os.environ["SEVN_SECRETS_PASSPHRASE"] = text
    return {"ok": True}


__all__ = [
    "READABLE_WIZARD_KEYS",
    "REQUIRED_FOR_HANDOFF",
    "WIZARD_SECRET_KEYS",
    "assigned_provider_names_from_doc",
    "credentials_status",
    "default_wizard_secrets_section",
    "delete_wizard_credential",
    "get_wizard_credential",
    "probe_host_github_token",
    "provider_secret_alias",
    "read_wizard_credential_values",
    "resolve_wizard_secrets_section",
    "secrets_section_from_sevn_json",
    "store_wizard_credentials",
    "unlock_wizard_keystore",
    "verify_wizard_passphrase",
]
