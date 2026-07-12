"""Live validation probes after schema gate (`specs/22-onboarding.md` §2.2, §4.7).

Onboarding logs under ``<workspace>/logs/onboard-*.log`` must **redact** bearer tokens,
Telegram bot tokens, and webhook secrets before write — mirror ``--log-file`` hygiene from
``prd/06-setup-and-operations.md`` §5.11 (CLI) so operators can paste logs safely.

Module: sevn.onboarding.live_validate
Depends: httpx, pathlib, typing, sevn.config.workspace_config, sevn.workspace.layout

Exports:
    ValidationCheck — one probe row.
    ValidationReport — ordered probe results.
    InstallStatusRow — one capability install readiness row.
    telegram_channel_enabled — True when Telegram channel is enabled in preview.
    llm_provider_configured — True when providers configure model slots.
    handoff_credential_keys_for_doc — required credential env keys for preview.
    run_live_validation — async probe runner.
    probe_capability_install_status — dry-run install readiness for selected capabilities.
    install_status_to_dict — serialize install status rows for JSON APIs.
    asyncio_subprocess_run — asyncio subprocess wrapper returning exit code.
    probe_secrets_backend — secrets sentinel get probe.
    section_uses_encrypted_file — True when ``secrets_backend.chain`` includes encrypted_file.
    probe_llm_reachability — 1-token proxy ping probe.
    probe_mcp_reachability — stdio MCP initialize probe.
    probe_webapp_https — Web App button HTTPS requirement notice.
    probe_pdf_weasyprint — WeasyPrint native-lib readiness (mirrors ``sevn doctor``).
    github_hub_enabled — True when self-improve GitHub hub is enabled.
    probe_github_hub — ``GET /user`` when GitHub hub is on.
    openai_oauth_mode_active — True when an assigned slot uses OpenAI Codex OAuth (D1).
    probe_openai_oauth_credential — warn when ``oauth.openai`` is missing or expired (W5).
    emit_openai_oauth_warnings — print non-fatal oauth credential guidance for validate CLI.

Examples:
    >>> ValidationReport().has_error()
    False
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

from sevn.agent.providers.resolve import resolve_model
from sevn.agent.providers.wire import adapt_request_for_transport
from sevn.code_understanding.graphify_mcp import merge_gateway_mcp_servers
from sevn.config.model_resolution import resolve_transport_for_model_id
from sevn.config.workspace_config import (
    SecretsBackendSectionConfig,
    effective_encrypted_file_key_source,
    parse_workspace_config,
)
from sevn.onboarding.github_oauth import GITHUB_TOKEN_LOGICAL_KEY, fetch_github_user
from sevn.onboarding.wizard_credentials import credentials_status, get_wizard_credential
from sevn.security.secrets import resolve_backend
from sevn.security.secrets.errors import (
    SecretsStoreCorruptError,
    is_encrypted_store_decrypt_failure,
)
from sevn.skills.errors import SkillExecutionError
from sevn.workspace.layout import WorkspaceLayout

Severity = Literal["info", "warn", "error"]

SENTINEL_PROBE_KEY = "_sevn_probe"
_LLM_PING_TIMEOUT_S = 15.0
_MCP_HANDSHAKE_TIMEOUT_S = 8.0


def telegram_channel_enabled(merged_preview: dict[str, Any]) -> bool:
    """Return True when ``channels.telegram.enabled`` is set in the merged document.

    Args:
        merged_preview (dict[str, Any]): Post-merge workspace JSON.

    Returns:
        bool: Whether Telegram live probes are required.

    Examples:
        >>> telegram_channel_enabled({"channels": {"telegram": {"enabled": True}}})
        True
        >>> telegram_channel_enabled({"channels": {"telegram": {"enabled": False}}})
        False
    """
    channels = merged_preview.get("channels")
    if not isinstance(channels, dict):
        return False
    tg = channels.get("telegram")
    if not isinstance(tg, dict):
        return False
    return bool(tg.get("enabled"))


def llm_provider_configured(merged_preview: dict[str, Any]) -> bool:
    """Return True when the document configures at least one model slot.

    Args:
        merged_preview (dict[str, Any]): Post-merge workspace JSON.

    Returns:
        bool: Whether LLM reachability probes are required.

    Examples:
        >>> llm_provider_configured(
        ...     {"providers": {"tier_default": {"triager": "minimax/M2"}}}
        ... )
        True
        >>> llm_provider_configured({"providers": {}})
        False
        >>> llm_provider_configured({"llm": {"main_model": "openai/gpt-test"}})
        True
    """
    llm = merged_preview.get("llm")
    if isinstance(llm, dict):
        main = llm.get("main_model")
        if isinstance(main, str) and main.strip():
            return True
    providers = merged_preview.get("providers")
    if not isinstance(providers, dict):
        return False
    tier = providers.get("tier_default")
    if isinstance(tier, dict):
        triager = tier.get("triager")
        if isinstance(triager, str) and triager.strip():
            return True
        for key, val in tier.items():
            if key == "triager":
                continue
            if isinstance(val, str) and val.strip():
                return True
    models = providers.get("models")
    return isinstance(models, dict) and bool(models)


def handoff_credential_keys_for_doc(merged_preview: dict[str, Any]) -> frozenset[str]:
    """Return wizard credential env keys required for the given merged config.

    Args:
        merged_preview (dict[str, Any]): Post-merge workspace JSON.

    Returns:
        frozenset[str]: Subset of handoff keys (Telegram token, per-provider secrets).

    Examples:
        >>> handoff_credential_keys_for_doc({"channels": {"telegram": {"enabled": True}}})
        frozenset({'SEVN_TELEGRAM_BOT_TOKEN'})
        >>> keys = handoff_credential_keys_for_doc(
        ...     {
        ...         "schema_version": 1,
        ...         "gateway": {"token": "t"},
        ...         "providers": {"tier_default": {"triager": "minimax/M2"}},
        ...     }
        ... )
        >>> "SEVN_SECRET_MINIMAX" in keys
        True
    """
    from sevn.config.provider_secrets import (
        assigned_provider_names_from_doc,
        resolve_handoff_secret_alias,
    )

    keys: set[str] = set()
    if telegram_channel_enabled(merged_preview):
        keys.add("SEVN_TELEGRAM_BOT_TOKEN")
    if llm_provider_configured(merged_preview):
        for name in assigned_provider_names_from_doc(merged_preview):
            keys.add(resolve_handoff_secret_alias(merged_preview, name))
    return frozenset(keys)


@dataclass(frozen=True)
class ValidationCheck:
    """Single live validation probe outcome (`specs/22-onboarding.md` §4.7)."""

    check_id: str
    ok: bool
    severity: Severity
    detail: str
    hint: str | None = None


@dataclass(frozen=True)
class InstallStatusRow:
    """Capability install readiness row for Validate step dry-run (D2 phase a)."""

    capability_id: str
    action_id: str
    ok: bool
    severity: Severity
    detail: str
    satisfied: bool
    fatal: bool
    hint: str | None = None


@dataclass
class ValidationReport:
    """Structured report returned by ``run_live_validation``."""

    checks: list[ValidationCheck] = field(default_factory=list)
    install_status: list[InstallStatusRow] = field(default_factory=list)

    def has_error(self) -> bool:
        """Return True when any probe is a failed error-severity check.

        Returns:
            bool: ``True`` when at least one failed ``error`` row exists.

        Examples:
            >>> ValidationReport(
            ...     checks=[ValidationCheck("x", False, "error", "e")]
            ... ).has_error()
            True
        """
        return any(not c.ok and c.severity == "error" for c in self.checks)


def openai_oauth_mode_active(doc: dict[str, Any]) -> bool:
    """Return True when an assigned model slot requires Codex OAuth for OpenAI (D1).

    Args:
        doc (dict[str, Any]): Workspace JSON document.

    Returns:
        bool: Whether ``providers.openai.auth_mode=oauth`` applies to an assigned slot.

    Examples:
        >>> openai_oauth_mode_active(
        ...     {
        ...         "schema_version": 1,
        ...         "gateway": {"token": "t"},
        ...         "providers": {
        ...             "tier_default": {"triager": "openai/gpt-4o"},
        ...             "openai": {"auth_mode": "oauth"},
        ...         },
        ...     },
        ... )
        True
        >>> openai_oauth_mode_active({"providers": {"openai": {"auth_mode": "oauth"}}})
        False
    """
    from sevn.config.provider_secrets import assigned_provider_names_from_doc
    from sevn.config.sections.providers import resolve_auth_mode

    if "openai" not in assigned_provider_names_from_doc(doc):
        return False
    providers = doc.get("providers")
    if not isinstance(providers, dict):
        return False
    return resolve_auth_mode(providers, "openai") == "oauth"


def probe_openai_oauth_credential(
    doc: dict[str, Any],
    *,
    secrets_chain: Any | None = None,
    credential: Any | None = None,
) -> ValidationCheck:
    """Probe ``oauth.openai`` when ``providers.openai.auth_mode=oauth`` (W5, non-fatal).

    Args:
        doc (dict[str, Any]): Workspace JSON document.
        secrets_chain (Any | None): Optional secrets chain for loading ``oauth.openai``.
        credential (CodexOAuthCredential | None): Pre-loaded credential (tests).

    Returns:
        ValidationCheck: Warn row when credential is missing or expired.

    Examples:
        >>> probe_openai_oauth_credential({"providers": {}}).ok
        True
    """
    from sevn.proxy.oauth_lifecycle import is_oauth_credential_fresh
    from sevn.security.oauth.credential import CodexOAuthCredential
    from sevn.security.oauth.storage import load_codex_oauth_credential

    check_id = "openai_oauth_credential"
    if not openai_oauth_mode_active(doc):
        return ValidationCheck(
            check_id=check_id,
            ok=True,
            severity="info",
            detail="openai oauth credential not required",
        )

    resolved: CodexOAuthCredential | None = credential
    if resolved is None and secrets_chain is not None:
        from sevn.cli.asyncio_util import run_sync_coro

        try:
            resolved = run_sync_coro(load_codex_oauth_credential(secrets_chain))
        except SecretsStoreCorruptError as exc:
            if is_encrypted_store_decrypt_failure(exc):
                return ValidationCheck(
                    check_id=check_id,
                    ok=False,
                    severity="error",
                    detail=f"encrypted store fails to decrypt: {exc}",
                    hint=(
                        "wrong key material — verify SEVN_SECRETS_PASSPHRASE and remove any stale "
                        "SEVN_SECRETS_MASTER_KEY (`launchctl unsetenv SEVN_SECRETS_MASTER_KEY`)"
                    ),
                )
            return ValidationCheck(
                check_id=check_id,
                ok=False,
                severity="warn",
                detail=f"encrypted store locked: {exc}",
                hint="run `sevn secrets store-passphrase` or export SEVN_SECRETS_PASSPHRASE",
            )

    if resolved is None:
        return ValidationCheck(
            check_id=check_id,
            ok=False,
            severity="warn",
            detail=(
                "oauth.openai credential missing for providers.openai auth_mode=oauth "
                "(assigned OpenAI model slot)"
            ),
            hint="run `sevn providers oauth login --provider openai`",
        )

    if not is_oauth_credential_fresh(resolved):
        return ValidationCheck(
            check_id=check_id,
            ok=False,
            severity="warn",
            detail="oauth.openai access token expired or near expiry — reauth required",
            hint="run `sevn providers oauth login --provider openai` or `sevn doctor --fix`",
        )

    return ValidationCheck(
        check_id=check_id,
        ok=True,
        severity="info",
        detail=f"oauth.openai credential present (account_id={resolved.account_id})",
    )


def emit_openai_oauth_warnings(
    doc: dict[str, Any],
    *,
    echo: Any | None = None,
    secrets_chain: Any | None = None,
) -> None:
    """Print non-fatal OpenAI OAuth credential warnings for ``sevn config validate``.

    Args:
        doc (dict[str, Any]): Workspace JSON document.
        echo (Any | None): Callable accepting one message string; defaults to ``print``.
        secrets_chain (Any | None): Optional secrets chain for credential lookup.

    Returns:
        None

    Examples:
        >>> emit_openai_oauth_warnings({"providers": {}}, echo=lambda _msg: None) is None
        True
    """
    if not openai_oauth_mode_active(doc):
        return
    check = probe_openai_oauth_credential(doc, secrets_chain=secrets_chain)
    if check.ok:
        return
    writer = echo if echo is not None else print
    writer(f"warning: {check.detail}")
    if check.hint:
        writer(f"hint: {check.hint}")


def github_hub_enabled(merged_preview: dict[str, Any]) -> bool:
    """Return True when self-improve GitHub hub mode is enabled in the preview.

    Args:
        merged_preview (dict[str, Any]): Post-merge workspace JSON.

    Returns:
        bool: Whether a GitHub token probe is required.

    Examples:
        >>> github_hub_enabled({"self_improve": {"enabled": True, "hub": {"use_github": True}}})
        True
        >>> github_hub_enabled({"self_improve": {"enabled": True, "hub": {"use_github": False}}})
        False
    """
    si = merged_preview.get("self_improve")
    if not isinstance(si, dict) or not si.get("enabled"):
        return False
    hub = si.get("hub")
    if not isinstance(hub, dict):
        return False
    return bool(hub.get("use_github"))


async def probe_github_hub(
    *,
    content_root: Path,
    section: SecretsBackendSectionConfig | None,
) -> ValidationCheck:
    """Probe ``GET /user`` when the operator enabled the self-improve GitHub hub.

    Args:
        content_root (Path): Workspace content root.
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.

    Returns:
        ValidationCheck: Pass/fail row for ``github_hub_user``.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(
        ...     probe_github_hub(content_root=Path("/tmp"), section=None)
        ... ).check_id
        'github_hub_user'
    """
    token = await _resolve_wizard_secret(
        content_root,
        GITHUB_TOKEN_LOGICAL_KEY,
        section=section,
    )
    if not token:
        return ValidationCheck(
            check_id="github_hub_user",
            ok=False,
            severity="error",
            detail=f"{GITHUB_TOKEN_LOGICAL_KEY} missing from secrets chain",
            hint="connect GitHub on the My Sevn.bot step (OAuth or PAT)",
        )
    try:
        user = await fetch_github_user(token)
    except OSError as exc:
        return ValidationCheck(
            check_id="github_hub_user",
            ok=False,
            severity="error",
            detail=str(exc),
            hint="network blocked",
        )
    except Exception as exc:
        return ValidationCheck(
            check_id="github_hub_user",
            ok=False,
            severity="error",
            detail=str(exc),
            hint="check GitHub token scopes (repo, read:user)",
        )
    login = user.get("login")
    detail = (
        f"authenticated as {login}" if isinstance(login, str) and login.strip() else "get user ok"
    )
    return ValidationCheck(
        check_id="github_hub_user",
        ok=True,
        severity="info",
        detail=detail,
        hint=None,
    )


def _sevn_json_path(workspace_root: Path) -> Path:
    """Resolve ``sevn.json`` under the workspace directory.

    Args:
        workspace_root (Path): Workspace directory path.

    Returns:
        Path: Canonical ``sevn.json`` path.

    Examples:
        >>> from pathlib import Path
        >>> _sevn_json_path(Path("/tmp/ws")).name
        'sevn.json'
    """
    return (workspace_root / "sevn.json").resolve()


def _proxy_url_from_preview(
    merged_preview: dict[str, Any],
    cfg_proxy: dict[str, object] | None,
) -> str:
    """Resolve egress proxy origin from env or merged preview.

    Args:
        merged_preview (dict[str, Any]): Post-merge candidate document.
        cfg_proxy (dict[str, object] | None): Parsed ``WorkspaceConfig.proxy`` mapping.

    Returns:
        str: Stripped origin URL, or empty when unset.

    Examples:
        >>> _proxy_url_from_preview({}, None)
        ''
    """
    env = os.environ.get("SEVN_PROXY_URL", "").strip()
    if env:
        return env.rstrip("/")
    if isinstance(cfg_proxy, dict):
        base = str(cfg_proxy.get("url") or cfg_proxy.get("origin") or "").strip()
        return base.rstrip("/")
    raw = merged_preview.get("proxy")
    if isinstance(raw, dict):
        base = str(raw.get("url") or raw.get("origin") or "").strip()
        return base.rstrip("/")
    return ""


def _llm_model_for_ping(merged_preview: dict[str, Any]) -> str | None:
    """Pick a model id for the minimal LLM reachability ping.

    Args:
        merged_preview (dict[str, Any]): Post-merge candidate document.

    Returns:
        str | None: Model id when configured.

    Examples:
        >>> _llm_model_for_ping({"llm": {"main_model": " openai/gpt-4o "}})
        'openai/gpt-4o'
    """
    llm = merged_preview.get("llm")
    if isinstance(llm, dict):
        main = llm.get("main_model")
        if isinstance(main, str) and main.strip():
            return main.strip()
    providers = merged_preview.get("providers")
    if isinstance(providers, dict):
        tier = providers.get("tier_default")
        if isinstance(tier, dict):
            for key in ("B", "triager", "C"):
                entry = tier.get(key)
                if isinstance(entry, str) and entry.strip():
                    return entry.strip()
                if isinstance(entry, dict):
                    primary = entry.get("primary")
                    if isinstance(primary, str) and primary.strip():
                        return primary.strip()
    return None


def _declared_mcp_servers(merged_preview: dict[str, Any]) -> list[tuple[str, str, list[str]]]:
    """Return ``(server_id, command, args)`` rows from ``mcp_servers``.

    Args:
        merged_preview (dict[str, Any]): Post-merge candidate document.

    Returns:
        list[tuple[str, str, list[str]]]: Declared stdio servers.

    Examples:
        >>> _declared_mcp_servers({"mcp_servers": {"a": {"command": "echo", "args": ["hi"]}}})
        [('a', 'echo', ['hi'])]
    """
    raw = merged_preview.get("mcp_servers")
    if not isinstance(raw, dict):
        return []
    out: list[tuple[str, str, list[str]]] = []
    for server_id, spec in raw.items():
        if not isinstance(server_id, str) or not isinstance(spec, dict):
            continue
        command = spec.get("command")
        if not isinstance(command, str) or not command.strip():
            continue
        args_raw = spec.get("args")
        if args_raw is None:
            args_list: list[str] = []
        elif isinstance(args_raw, list):
            args_list = [str(a) for a in args_raw]
        else:
            continue
        out.append((server_id, command.strip(), args_list))
    return out


def section_uses_encrypted_file(section: SecretsBackendSectionConfig | None) -> bool:
    """Return True when the secrets section chain includes ``encrypted_file``.

    Args:
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.

    Returns:
        bool: ``True`` when an ``encrypted_file`` chain entry exists.

    Examples:
        >>> section_uses_encrypted_file(None)
        False
    """
    if section is None or not section.chain:
        return False
    return any(entry.type == "encrypted_file" for entry in section.chain)


async def _resolve_wizard_secret(
    content_root: Path,
    key: str,
    *,
    section: SecretsBackendSectionConfig | None = None,
) -> str | None:
    """Read a wizard credential from env or the workspace secrets chain.

    Args:
        content_root (Path): Workspace content root.
        key (str): Logical secret key (for example ``SEVN_TELEGRAM_BOT_TOKEN``).
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.

    Returns:
        str | None: Trimmed value when present.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(_resolve_wizard_secret(Path("/tmp"), "MISSING_KEY")) is None
        True
    """
    return await get_wizard_credential(content_root, key, section=section)


def _stray_unlock_env_var(section: SecretsBackendSectionConfig | None) -> str | None:
    """Return the inactive unlock env var name when it is set for an encrypted_file store.

    Under ``key_source=passphrase`` a set ``SEVN_SECRETS_MASTER_KEY`` is stray (and vice versa).
    A stray value is ignored by the backend but is the exact stale-env condition that used to
    silently break decryption, so callers surface it as a warning.

    Args:
        section (SecretsBackendSectionConfig | None): Parsed ``secrets_backend`` block.

    Returns:
        str | None: The stray env var name, or ``None`` when none is set / not encrypted_file.

    Examples:
        >>> _stray_unlock_env_var(None) is None
        True
    """
    if not section_uses_encrypted_file(section):
        return None
    inactive = (
        "SEVN_SECRETS_MASTER_KEY"
        if effective_encrypted_file_key_source(section) == "passphrase"
        else "SEVN_SECRETS_PASSPHRASE"
    )
    return inactive if os.environ.get(inactive, "").strip() else None


async def probe_secrets_backend(
    *,
    content_root: Path,
    section: SecretsBackendSectionConfig | None,
    strict_encrypted_file: bool = False,
) -> ValidationCheck:
    """Probe secrets backends via sentinel ``_sevn_probe`` get.

    Args:
        content_root (Path): Workspace content root.
        section (SecretsBackendSectionConfig | None): ``secrets_backend`` config block.
        strict_encrypted_file (bool): When ``True``, backend failures are ``error`` severity.

    Returns:
        ValidationCheck: ``secrets_backend`` row.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(probe_secrets_backend(
        ...     content_root=Path("/tmp"),
        ...     section=None,
        ... )).check_id
        'secrets_backend'
    """
    try:
        chain = resolve_backend(content_root, section)
        value = await chain.get(SENTINEL_PROBE_KEY)
    except SecretsStoreCorruptError as exc:
        if is_encrypted_store_decrypt_failure(exc):
            # Wrong key material (e.g. a stale SEVN_SECRETS_MASTER_KEY shadowing the
            # passphrase) or a corrupt store: always a hard error, never a warn — this is the
            # exact failure that silently breaks gateway secret resolution.
            return ValidationCheck(
                check_id="secrets_backend",
                ok=False,
                severity="error",
                detail=f"encrypted store fails to decrypt: {exc}",
                hint=(
                    "wrong key material — verify SEVN_SECRETS_PASSPHRASE and remove any stale "
                    "SEVN_SECRETS_MASTER_KEY (`launchctl unsetenv SEVN_SECRETS_MASTER_KEY`)"
                ),
            )
        severity_locked: Severity = "error" if strict_encrypted_file else "warn"
        return ValidationCheck(
            check_id="secrets_backend",
            ok=False,
            severity=severity_locked,
            detail=f"encrypted store locked: {exc}",
            hint="provide SEVN_SECRETS_PASSPHRASE or SEVN_SECRETS_MASTER_KEY (`specs/06-secrets.md`)",
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        severity: Severity = "error" if strict_encrypted_file else "warn"
        return ValidationCheck(
            check_id="secrets_backend",
            ok=False,
            severity=severity,
            detail=f"backend error: {exc}",
            hint="check secrets_backend chain (`specs/06-secrets.md`)",
        )
    stray = _stray_unlock_env_var(section)
    if stray is not None:
        # The store opens, but the env carries the *other* unlock credential. It is ignored under
        # the configured key_source — surface it so a stale value (the original footgun) is caught
        # before it can confuse a future operator.
        return ValidationCheck(
            check_id="secrets_backend",
            ok=True,
            severity="warn",
            detail=f"{stray} is set but key_source does not use it; the value is ignored",
            hint=(
                f"remove the stray {stray} (e.g. `launchctl unsetenv {stray}`) or set "
                "secrets_backend.encrypted_file.key_source to match (`specs/06-secrets.md`)"
            ),
        )
    if value is not None:
        return ValidationCheck(
            check_id="secrets_backend",
            ok=True,
            severity="info",
            detail="sentinel _sevn_probe read ok",
            hint=None,
        )
    return ValidationCheck(
        check_id="secrets_backend",
        ok=True,
        severity="warn",
        detail="sentinel _sevn_probe not set (backend reachable)",
        hint="store a probe value with `sevn secrets put` (`specs/06-secrets.md`)",
    )


async def probe_llm_reachability(
    *,
    merged_preview: dict[str, Any],
    cfg_proxy: dict[str, object] | None,
    fail_on_proxy_503: bool = False,
) -> ValidationCheck:
    """Ping the egress proxy with a 1-token chat completion.

    Args:
        merged_preview (dict[str, Any]): Post-merge candidate document.
        cfg_proxy (dict[str, object] | None): Parsed proxy subtree.
        fail_on_proxy_503 (bool): When True, treat proxy LLM 503 as an error (doctor path).

    Returns:
        ValidationCheck: ``llm_reachability`` row (info skip when unconfigured).

    Examples:
        >>> import asyncio
        >>> asyncio.run(probe_llm_reachability(merged_preview={}, cfg_proxy=None)).check_id
        'llm_reachability'
    """
    proxy_url = _proxy_url_from_preview(merged_preview, cfg_proxy)
    model_id = _llm_model_for_ping(merged_preview)
    if not proxy_url:
        return ValidationCheck(
            check_id="llm_reachability",
            ok=True,
            severity="info",
            detail="skipped (no SEVN_PROXY_URL / proxy.url)",
            hint=None,
        )
    if not model_id:
        return ValidationCheck(
            check_id="llm_reachability",
            ok=True,
            severity="info",
            detail="skipped (no llm.main_model / providers.tier_default)",
            hint=None,
        )
    providers_obj = merged_preview.get("providers")
    if not isinstance(providers_obj, dict):
        providers_obj = {}
    transport_name = resolve_transport_for_model_id(providers_obj, model_id)
    _, transport = resolve_model(
        model_id=model_id,
        transport_name=transport_name,
        proxy_base_url=proxy_url,
    )
    request: dict[str, object] = {
        "model": model_id,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }
    try:
        await asyncio.wait_for(
            transport.complete(adapt_request_for_transport(transport, request)),
            timeout=_LLM_PING_TIMEOUT_S,
        )
    except TimeoutError:
        return ValidationCheck(
            check_id="llm_reachability",
            ok=False,
            severity="warn",
            detail=f"proxy ping timed out after {_LLM_PING_TIMEOUT_S:.0f}s",
            hint="check proxy process and provider keys (`specs/05-llm-transports.md`)",
        )
    except httpx.HTTPStatusError as exc:
        if fail_on_proxy_503 and exc.response.status_code == 503:
            return ValidationCheck(
                check_id="llm_reachability",
                ok=False,
                severity="error",
                detail="proxy LLM route returned 503 (provider credentials not loaded on proxy)",
                hint="restart proxy after saving provider credentials",
            )
        return ValidationCheck(
            check_id="llm_reachability",
            ok=False,
            severity="warn",
            detail=str(exc),
            hint="check proxy /healthz and model id (`specs/05-llm-transports.md`)",
        )
    except (
        OSError,
        NotImplementedError,
        RuntimeError,
        TypeError,
        ValueError,
        httpx.RequestError,
    ) as exc:
        return ValidationCheck(
            check_id="llm_reachability",
            ok=False,
            severity="warn",
            detail=str(exc),
            hint="check proxy /healthz and model id (`specs/05-llm-transports.md`)",
        )
    return ValidationCheck(
        check_id="llm_reachability",
        ok=True,
        severity="info",
        detail=f"proxy ping ok model={model_id}",
        hint=None,
    )


async def _mcp_stdio_initialize(command: str, args: list[str]) -> None:
    """Run MCP ``initialize`` over stdio (raises on failure).

    Args:
        command (str): Executable for the MCP server.
        args (list[str]): argv tail.

    Raises:
        OSError: Subprocess or transport failure.
        TimeoutError: Handshake exceeded ``_MCP_HANDSHAKE_TIMEOUT_S``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_mcp_stdio_initialize)
        True
    """
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(command=command, args=args)
    async with asyncio.timeout(_MCP_HANDSHAKE_TIMEOUT_S):
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()


def probe_webapp_https(*, merged_preview: dict[str, Any]) -> ValidationCheck:
    """Report when Telegram Web App buttons are disabled due to a non-HTTPS base.

    Args:
        merged_preview (dict[str, Any]): Post-merge workspace JSON.

    Returns:
        ValidationCheck: ``severity=info`` when HTTPS; ``warn`` when HTTP-only base.

    Examples:
        >>> chk = probe_webapp_https(merged_preview={
        ...     "schema_version": 1,
        ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ... })
        >>> chk.check_id == "webapp_https"
        True
    """
    from sevn.gateway.webapp_qa import (
        resolve_webapp_public_base,
        webapp_https_disabled_notice,
    )

    cfg = parse_workspace_config(merged_preview)
    base = resolve_webapp_public_base(cfg)
    notice = webapp_https_disabled_notice(base)
    if notice is None:
        return ValidationCheck(
            check_id="webapp_https",
            ok=True,
            severity="info",
            detail=f"gateway base is HTTPS ({base})",
            hint=None,
        )
    return ValidationCheck(
        check_id="webapp_https",
        ok=True,
        severity="warn",
        detail=notice,
        hint="use an HTTPS tunnel or reverse proxy for Share/Feedback Web App buttons",
    )


def probe_pdf_weasyprint() -> ValidationCheck:
    """Probe WeasyPrint PDF rendering readiness (same row as ``sevn doctor``).

    Returns:
        ValidationCheck: ``pdf_weasyprint`` row with install hint when degraded.

    Examples:
        >>> chk = probe_pdf_weasyprint()
        >>> chk.check_id == "pdf_weasyprint"
        True
    """
    from sevn.pdf.doctor_check import probe_weasyprint_render

    row = probe_weasyprint_render()
    return ValidationCheck(
        check_id=row.check_id,
        ok=row.ok,
        severity="info" if row.ok else "warn",
        detail=row.detail,
        hint=row.hint,
    )


async def probe_mcp_reachability(*, merged_preview: dict[str, Any]) -> ValidationCheck:
    """Handshake each declared ``mcp_servers`` entry over stdio.

    Args:
        merged_preview (dict[str, Any]): Post-merge candidate document.

    Returns:
        ValidationCheck: ``mcp_reachability`` row.

    Examples:
        >>> import asyncio
        >>> asyncio.run(probe_mcp_reachability(merged_preview={})).detail.startswith("skipped")
        True
    """
    servers = _declared_mcp_servers(merged_preview)
    if not servers:
        return ValidationCheck(
            check_id="mcp_reachability",
            ok=True,
            severity="info",
            detail="skipped (no mcp_servers declared)",
            hint=None,
        )
    parts: list[str] = []
    any_fail = False
    for server_id, command, args in servers:
        try:
            await _mcp_stdio_initialize(command, args)
            parts.append(f"{server_id}:ok")
        except (OSError, TimeoutError, RuntimeError, TypeError, ValueError) as exc:
            any_fail = True
            parts.append(f"{server_id}:error ({exc})")
    detail = "; ".join(parts)
    return ValidationCheck(
        check_id="mcp_reachability",
        ok=not any_fail,
        severity="warn" if any_fail else "info",
        detail=detail,
        hint=None
        if not any_fail
        else "fix MCP command/args or install server binary (`specs/11-tools-registry.md`)",
    )


async def run_live_validation(
    *,
    workspace_root: Path,
    merged_preview: dict[str, Any],
    profile_id: str | None,
) -> ValidationReport:
    """Run ordered live probes on ``merged_preview`` (subset in v1).

    Args:
        workspace_root (Path): Directory containing ``sevn.json`` (not the file itself).
        merged_preview (dict[str, Any]): Post-merge candidate document.
        profile_id (str | None): Active preset id for logging/diagnostics only.

    Returns:
        ValidationReport: Ordered ``ValidationCheck`` rows (warn/error semantics §6).

    Examples:
        >>> import asyncio
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> async def _run():
        ...     return await run_live_validation(
        ...         workspace_root=td,
        ...         merged_preview={
        ...             "schema_version": 1,
        ...             "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...         },
        ...         profile_id=None,
        ...     )
        >>> isinstance(asyncio.run(_run()), ValidationReport)
        True
    """
    _ = profile_id
    report = ValidationReport()
    root = Path(workspace_root)
    cfg = parse_workspace_config(merged_preview)
    sevn_json = _sevn_json_path(root)
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    try:
        merge_gateway_mcp_servers(
            merged_preview,
            workspace=cfg,
            content_root=layout.content_root,
        )
    except SkillExecutionError as exc:
        report.checks.append(
            ValidationCheck(
                check_id="mcp_merge",
                ok=False,
                severity="warn",
                detail=str(exc),
                hint="Install skill binaries or disable opt-in skills before promoting",
            )
        )

    # 1) Workspace paths
    paths_ok = True
    detail_parts: list[str] = []
    for label, path in (
        ("content_root", layout.content_root),
        (".sevn", layout.dot_sevn),
        ("logs", layout.logs_dir),
    ):
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".sevn_write_probe"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
        except OSError as exc:
            paths_ok = False
            detail_parts.append(f"{label}:{path} ({exc})")
    report.checks.append(
        ValidationCheck(
            check_id="workspace_paths",
            ok=paths_ok,
            severity="error" if not paths_ok else "info",
            detail="writable" if paths_ok else "; ".join(detail_parts),
            hint=None
            if paths_ok
            else "fix permissions or pick another workspace_root (`specs/02-config-and-workspace.md` §2.6)",
        )
    )

    # 2) Strict parse (redundant after caller; cheap double-check)
    report.checks.append(
        ValidationCheck(
            check_id="strict_parse",
            ok=True,
            severity="info",
            detail="WorkspaceConfig parse succeeded",
            hint=None,
        )
    )

    # 3) SQLite head — stub/skip when storage paths not wired in preview
    report.checks.append(
        ValidationCheck(
            check_id="sqlite_migrations",
            ok=True,
            severity="info",
            detail="skipped (no storage.sqlite_path in preview — `specs/03-storage.md` coordination)",
            hint=None,
        )
    )

    # 4) Secrets backend sentinel
    strict_encrypted = section_uses_encrypted_file(cfg.secrets_backend)
    report.checks.append(
        await probe_secrets_backend(
            content_root=layout.content_root,
            section=cfg.secrets_backend,
            strict_encrypted_file=strict_encrypted,
        )
    )

    cred_status = await credentials_status(layout.content_root, section=cfg.secrets_backend)
    cred_present = cred_status.get("present")
    present: dict[str, bool] = cred_present if isinstance(cred_present, dict) else {}

    # 5) Sandbox driver runtime (docker + optional Deno for pyodide_deno)
    docker_ok = False
    docker_detail = "docker CLI not checked"
    try:
        proc = await asyncio_subprocess_run(["docker", "info"])
        docker_ok = proc == 0
        docker_detail = "docker info exited 0" if docker_ok else "docker info non-zero"
    except FileNotFoundError:
        docker_detail = "docker binary not found"
    report.checks.append(
        ValidationCheck(
            check_id="sandbox_runtime",
            ok=docker_ok,
            severity="warn",
            detail=docker_detail,
            hint="Install Docker or confirm subprocess sandbox policy (`specs/08-sandbox.md`)",
        )
    )
    sandbox_mode = ""
    sandbox_section = merged_preview.get("sandbox")
    if isinstance(sandbox_section, dict):
        sandbox_mode = (
            str(
                sandbox_section.get("mode")
                or sandbox_section.get("driver")
                or sandbox_section.get("runtime")
                or "",
            )
            .strip()
            .lower()
        )
    if sandbox_mode == "pyodide_deno":
        from sevn.agent.runtimes.pyodide_deno import deno_binary_on_path

        deno = deno_binary_on_path()
        if deno:
            report.checks.append(
                ValidationCheck(
                    check_id="pyodide_deno",
                    ok=True,
                    severity="info",
                    detail=f"deno at {deno} (sandbox.mode=pyodide_deno)",
                    hint=None,
                )
            )
        else:
            hint = "Install Deno: curl -fsSL https://deno.land/install.sh | sh"
            if docker_ok:
                hint += " — or choose sandbox.mode=docker in the wizard"
            report.checks.append(
                ValidationCheck(
                    check_id="pyodide_deno",
                    ok=False,
                    severity="warn",
                    detail=(
                        "sandbox.mode=pyodide_deno but deno not on PATH; "
                        "sandbox_exec will stay pending until Deno is installed"
                    ),
                    hint=hint,
                )
            )

    # 6) Egress proxy healthz
    proxy_url = _proxy_url_from_preview(
        merged_preview,
        cfg.proxy if isinstance(cfg.proxy, dict) else None,
    )
    if proxy_url:
        origin = proxy_url.rstrip("/")
        url = f"{origin}/healthz"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
            ok = resp.status_code == 200
            report.checks.append(
                ValidationCheck(
                    check_id="egress_proxy",
                    ok=ok,
                    severity="warn",
                    detail=f"GET {url} -> {resp.status_code}",
                    hint=None if ok else "check proxy process (`specs/07-egress-proxy.md`)",
                )
            )
        except (
            OSError,
            httpx.RequestError,
        ) as exc:
            report.checks.append(
                ValidationCheck(
                    check_id="egress_proxy",
                    ok=False,
                    severity="warn",
                    detail=str(exc),
                    hint="proxy unreachable — start gateway/proxy or validate without live proxy",
                )
            )
    else:
        report.checks.append(
            ValidationCheck(
                check_id="egress_proxy",
                ok=True,
                severity="info",
                detail="skipped (no SEVN_PROXY_URL / proxy.url)",
                hint=None,
            )
        )

    # 7) LLM reachability — required when providers configure model slots
    cfg_proxy = cfg.proxy if isinstance(cfg.proxy, dict) else None
    llm_required = llm_provider_configured(merged_preview)
    if not llm_required:
        report.checks.append(
            ValidationCheck(
                check_id="llm_reachability",
                ok=True,
                severity="info",
                detail="skipped (no model slots in providers)",
                hint=None,
            )
        )
    elif llm_required:
        from sevn.config.provider_secrets import (
            assigned_provider_names_from_doc,
            resolve_handoff_secret_alias,
        )

        missing_providers: list[str] = []
        for name in sorted(assigned_provider_names_from_doc(merged_preview)):
            alias = resolve_handoff_secret_alias(merged_preview, name)
            if not present.get(alias):
                missing_providers.append(f"{name} ({alias})")
        if missing_providers:
            report.checks.append(
                ValidationCheck(
                    check_id="llm_reachability",
                    ok=False,
                    severity="error",
                    detail="missing provider credentials: " + ", ".join(missing_providers),
                    hint="enter API keys for each assigned provider on the wizard model step",
                )
            )
        else:
            report.checks.append(
                await probe_llm_reachability(merged_preview=merged_preview, cfg_proxy=cfg_proxy)
            )

    # 8) Telegram getMe — required when Telegram channel is enabled
    tg_required = telegram_channel_enabled(merged_preview)
    if not tg_required:
        report.checks.append(
            ValidationCheck(
                check_id="telegram_get_me",
                ok=True,
                severity="info",
                detail="skipped (channels.telegram.enabled is false)",
                hint=None,
            )
        )
    elif not present.get("SEVN_TELEGRAM_BOT_TOKEN"):
        report.checks.append(
            ValidationCheck(
                check_id="telegram_get_me",
                ok=False,
                severity="error",
                detail="SEVN_TELEGRAM_BOT_TOKEN missing from secrets chain",
                hint="enter bot token on the wizard channels step (`specs/18-channel-telegram.md`)",
            )
        )
    else:
        token = await _resolve_wizard_secret(
            layout.content_root,
            "SEVN_TELEGRAM_BOT_TOKEN",
            section=cfg.secrets_backend,
        )
        if not token:
            report.checks.append(
                ValidationCheck(
                    check_id="telegram_get_me",
                    ok=False,
                    severity="error",
                    detail="SEVN_TELEGRAM_BOT_TOKEN missing from secrets chain",
                    hint="enter bot token on the wizard channels step",
                )
            )
        else:
            url = f"https://api.telegram.org/bot{token}/getMe"
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(url)
                payload = resp.json()
                ok = bool(payload.get("ok"))
                if ok:
                    detail = "getMe ok"
                else:
                    desc = payload.get("description")
                    detail = (
                        str(desc).strip()
                        if isinstance(desc, str) and desc.strip()
                        else f"telegram API http={resp.status_code}"
                    )
                report.checks.append(
                    ValidationCheck(
                        check_id="telegram_get_me",
                        ok=ok,
                        severity="error" if not ok else "info",
                        detail=detail,
                        hint=None if ok else "check bot token (`specs/18-channel-telegram.md`)",
                    )
                )
            except (
                OSError,
                httpx.RequestError,
            ) as exc:
                report.checks.append(
                    ValidationCheck(
                        check_id="telegram_get_me",
                        ok=False,
                        severity="error",
                        detail=str(exc),
                        hint="network blocked",
                    )
                )

    # 8b) GitHub hub token — required when self-improve uses GitHub
    gh_required = github_hub_enabled(merged_preview)
    if not gh_required:
        report.checks.append(
            ValidationCheck(
                check_id="github_hub_user",
                ok=True,
                severity="info",
                detail="skipped (self_improve.hub.use_github is false)",
                hint=None,
            )
        )
    else:
        report.checks.append(
            await probe_github_hub(
                content_root=layout.content_root,
                section=cfg.secrets_backend,
            )
        )

    # 9) .llmignore directory POSIX-safe
    ignore_dir = layout.content_root / ".llmignore"
    mode_ok = True
    mode_detail = "absent or ok"
    if ignore_dir.is_dir():
        st = ignore_dir.stat()
        mode_ok = not stat.S_ISLNK(st.st_mode)
        mode_detail = "symlink — unsafe" if not mode_ok else "directory present"
    report.checks.append(
        ValidationCheck(
            check_id="llmignore_dir",
            ok=mode_ok,
            severity="warn" if not mode_ok else "info",
            detail=mode_detail,
            hint=None
            if mode_ok
            else "replace symlink with real directory (`specs/09-security-scanner.md`)",
        )
    )

    # 10) MCP reachability
    report.checks.append(await probe_mcp_reachability(merged_preview=merged_preview))

    # 11) Telegram Web App HTTPS base
    report.checks.append(probe_webapp_https(merged_preview=merged_preview))

    # 12) PDF / WeasyPrint native libs (warn-only; macOS onboarding installs post-promote)
    report.checks.append(probe_pdf_weasyprint())

    # 13) Selected capability install readiness (D2 pre-validate dry-run)
    from sevn.onboarding.install_orchestrator import resolve_install_root

    install_root = resolve_install_root(merged_preview, content_root=layout.content_root)
    install_rows = await probe_capability_install_status(
        merged_preview,
        install_root=install_root,
        content_root=layout.content_root,
    )
    report.install_status = install_rows
    for row in install_rows:
        report.checks.append(
            ValidationCheck(
                check_id=f"capability.{row.capability_id}",
                ok=row.ok,
                severity=row.severity,
                detail=row.detail,
                hint=row.hint,
            )
        )

    return report


_UV_EXTRA_IMPORT_PROBE: dict[str, str] = {
    "browser": "import playwright",
    "browser-cdp": "import websockets",
    "web-fetch": "import brotli",
    "web-extract": "import readability",
    "pdf": "import pypdf",
    "yt-dlp": "import yt_dlp",
    "graphify": "import graphify",
    "code-review-graph": "import code_review_graph",
    "code-graph-rag": "import code_graph_rag",
    "bedrock": "import aiobotocore",
    "skillspector": "import skillspector",
}

_CAPABILITY_CLI_PROBE: dict[str, list[str]] = {
    "cli.roam_code": ["roam-code", "--help"],
    "cli.cgr": ["cgr", "--help"],
    "cli.gh": ["gh", "--version"],
    "cli.deno": ["deno", "--version"],
    "cli.docker": ["docker", "info"],
    "cli.whisper_cpp": ["whisper", "--help"],
    "cli.edge_tts": ["edge-tts", "--help"],
}


def install_status_to_dict(row: InstallStatusRow) -> dict[str, Any]:
    """Serialize one install status row for JSON APIs.

    Args:
        row (InstallStatusRow): Capability install readiness row.

    Returns:
        dict[str, Any]: JSON-serializable mapping.

    Examples:
        >>> install_status_to_dict(
        ...     InstallStatusRow("extra.browser", "extra.browser.cmd", True, "info", "ok", True, True)
        ... )["capability_id"]
        'extra.browser'
    """
    return {
        "capability_id": row.capability_id,
        "action_id": row.action_id,
        "ok": row.ok,
        "severity": row.severity,
        "detail": row.detail,
        "satisfied": row.satisfied,
        "fatal": row.fatal,
        "hint": row.hint,
    }


async def _run_probe_command(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Run a short probe command and return success plus a detail line.

    Args:
        argv (list[str]): Probe argv.
        cwd (Path): Working directory.
        env (dict[str, str] | None): Extra environment variables.

    Returns:
        tuple[bool, str]: Whether the probe succeeded and a status detail.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> ok, _ = asyncio.run(_run_probe_command(["true"], cwd=Path(".")))
        >>> ok
        True
    """
    if not argv:
        return False, "empty probe argv"
    run_env = {**os.environ, **(env or {})}
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            env=run_env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        code = await asyncio.wait_for(proc.wait(), timeout=10.0)
    except FileNotFoundError:
        return False, f"{argv[0]} not found on PATH"
    except TimeoutError:
        return False, f"probe timed out: {' '.join(argv)}"
    if code == 0:
        return True, f"probe ok: {' '.join(argv)}"
    return False, f"probe exit {code}: {' '.join(argv)}"


async def _probe_install_action(
    *,
    capability_id: str,
    action: Any,
    install_root: Path,
    merged_preview: dict[str, Any],
    content_root: Path | None = None,
) -> InstallStatusRow:
    """Evaluate one manifest install action for dry-run readiness.

    Args:
        capability_id (str): Owning capability id.
        action (Any): Manifest ``InstallAction`` row.
        install_root (Path): sevn.bot checkout root.
        merged_preview (dict[str, Any]): Merged workspace document.
        content_root (Path | None): Workspace content root for content-relative probes.

    Returns:
        InstallStatusRow: Readiness row for ``install_status[]``.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.onboarding.capabilities_manifest import InstallAction
        >>> noop = InstallAction(id="t.n", kind="noop", argv=[], fatal=False)
        >>> row = asyncio.run(
        ...     _probe_install_action(
        ...         capability_id="t",
        ...         action=noop,
        ...         install_root=Path("."),
        ...         merged_preview={},
        ...     )
        ... )
        >>> row.action_id
        't.n'
    """
    from sevn.onboarding.install_actions.executors import idempotent_check_satisfied

    hint = "Run installs on the Validate step before promoting" if action.fatal else None

    if action.idempotent_check:
        satisfied = await idempotent_check_satisfied(
            action.idempotent_check,
            cwd=install_root,
            env=action.env,
        )
        detail = (
            f"{action.idempotent_check} satisfied"
            if satisfied
            else f"{action.idempotent_check} not satisfied — install pending"
        )
        return InstallStatusRow(
            capability_id=capability_id,
            action_id=action.id,
            ok=satisfied or not action.fatal,
            severity="info" if satisfied else "warn",
            detail=detail,
            satisfied=satisfied,
            fatal=action.fatal,
            hint=None if satisfied else hint,
        )

    if action.kind == "noop":
        from sevn.onboarding.install_actions import special as install_special

        noop_validators = {
            "skill.computer_use.noop": install_special.run_computer_use_validate,
            "skill.cua_agent.noop": install_special.run_cua_agent_validate,
            "skill.lume.noop": install_special.run_lume_validate,
            "skill.openwiki.noop": install_special.run_openwiki_validate,
        }
        validator = noop_validators.get(action.id)
        if validator is not None:
            code, detail = validator(
                merged_config=merged_preview,
                content_root=content_root,
            )
            satisfied = code == 0
            return InstallStatusRow(
                capability_id=capability_id,
                action_id=action.id,
                ok=satisfied or not action.fatal,
                severity="info" if satisfied else "warn",
                detail=detail,
                satisfied=satisfied,
                fatal=action.fatal,
                hint=None if satisfied else hint,
            )
        cli_argv = _CAPABILITY_CLI_PROBE.get(capability_id)
        if cli_argv:
            satisfied, detail = await _run_probe_command(cli_argv, cwd=install_root, env=action.env)
            return InstallStatusRow(
                capability_id=capability_id,
                action_id=action.id,
                ok=satisfied or not action.fatal,
                severity="info" if satisfied else "warn",
                detail=detail,
                satisfied=satisfied,
                fatal=action.fatal,
                hint=None if satisfied else (action.note or hint),
            )
        note = action.note or "manual verification"
        return InstallStatusRow(
            capability_id=capability_id,
            action_id=action.id,
            ok=True,
            severity="info",
            detail=note,
            satisfied=True,
            fatal=action.fatal,
            hint=None,
        )

    if action.kind == "uv_extra" and action.argv:
        extra = str(action.argv[0])
        import_probe = _UV_EXTRA_IMPORT_PROBE.get(extra)
        if import_probe:
            satisfied = await idempotent_check_satisfied(import_probe, cwd=install_root)
            detail = (
                f"extra {extra!r} import satisfied"
                if satisfied
                else f"extra {extra!r} not installed — run uv sync --extra {extra}"
            )
            return InstallStatusRow(
                capability_id=capability_id,
                action_id=action.id,
                ok=satisfied or not action.fatal,
                severity="info" if satisfied else "warn",
                detail=detail,
                satisfied=satisfied,
                fatal=action.fatal,
                hint=None if satisfied else hint,
            )

    if action.kind in ("subprocess", "make_target") and action.argv:
        install_like = any(token in action.argv for token in ("install", "sync", "pdf-native-libs"))
        if install_like and action.kind == "subprocess":
            satisfied, detail = await _run_probe_command(
                [action.argv[0], "--version"],
                cwd=install_root,
                env=action.env,
            )
            if not satisfied:
                satisfied, detail = await _run_probe_command(
                    [action.argv[0], "--help"],
                    cwd=install_root,
                    env=action.env,
                )
        else:
            satisfied, detail = await _run_probe_command(
                list(action.argv),
                cwd=install_root,
                env=action.env,
            )
        return InstallStatusRow(
            capability_id=capability_id,
            action_id=action.id,
            ok=satisfied or not action.fatal,
            severity="info" if satisfied else "warn",
            detail=detail,
            satisfied=satisfied,
            fatal=action.fatal,
            hint=None if satisfied else hint,
        )

    if action.kind == "secret_required":
        return InstallStatusRow(
            capability_id=capability_id,
            action_id=action.id,
            ok=True,
            severity="info",
            detail="secret check deferred to live validation",
            satisfied=False,
            fatal=action.fatal,
            hint=None,
        )

    return InstallStatusRow(
        capability_id=capability_id,
        action_id=action.id,
        ok=not action.fatal,
        severity="warn",
        detail=f"unsupported install kind: {action.kind}",
        satisfied=False,
        fatal=action.fatal,
        hint=hint,
    )


async def probe_capability_install_status(
    merged_preview: dict[str, Any],
    *,
    install_root: Path | None = None,
    content_root: Path | None = None,
) -> list[InstallStatusRow]:
    """Dry-run install readiness for selected capabilities (D2 phase a).

    Args:
        merged_preview (dict[str, Any]): Merged workspace document.
        install_root (Path | None): sevn.bot checkout; resolved when omitted.
        content_root (Path | None): Workspace content root for secret probes.

    Returns:
        list[InstallStatusRow]: One row per planned install action.

    Examples:
        >>> import asyncio
        >>> rows = asyncio.run(probe_capability_install_status({}))
        >>> isinstance(rows, list)
        True
    """
    from sevn.onboarding.install_orchestrator import build_install_plan, resolve_install_root

    root = install_root or resolve_install_root(merged_preview)
    plan = build_install_plan(merged_preview)
    rows: list[InstallStatusRow] = []
    for step in plan.steps:
        rows.append(
            await _probe_install_action(
                capability_id=step.capability_id,
                action=step.action,
                install_root=root,
                merged_preview=merged_preview,
                content_root=content_root,
            )
        )
    return rows


async def asyncio_subprocess_run(argv: list[str], *, timeout_s: float = 10.0) -> int:
    """Run subprocess without blocking the event loop (minimal wrapper).

    A ``timeout_s`` guards against probes that hang indefinitely — most notably
    ``docker info`` against an unresponsive Docker daemon, which would otherwise
    freeze onboarding's live validation forever. On timeout the child is killed
    and ``124`` is returned (mirroring ``timeout(1)``), so callers treat it like
    any other non-zero (unavailable) exit.

    Args:
        argv (list[str]): argv0..n.
        timeout_s (float): Seconds to wait before killing the child and returning
            ``124``.

    Returns:
        int: Exit code, or ``124`` when the process exceeded ``timeout_s``.

    Examples:
        >>> import asyncio
        >>> asyncio.run(asyncio_subprocess_run(["true"])) == 0
        True
        >>> asyncio.run(asyncio_subprocess_run(["sleep", "5"], timeout_s=0.1))
        124
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        return int(await asyncio.wait_for(proc.wait(), timeout=timeout_s))
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        return 124
