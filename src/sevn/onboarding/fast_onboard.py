"""Non-interactive ``sevn onboard --config`` pipeline (`specs/22-onboarding.md` §4.3, §4.9).

Module: sevn.onboarding.fast_onboard
Depends: asyncio, sys, pathlib, pydantic, typer, sevn.cli.*, sevn.onboarding.*,
    sevn.config.workspace_config, sevn.workspace.layout

Exports:
    FastOnboardError — base fast onboard failure with exit code.
    FastOnboardResult — promote + handoff summary.
    FastOnboardValidationError — schema/credentials/live failures (exit 2).
    FastOnboardPreconditionError — service restart failures (exit 4).
    merge_config_layers — defaults → profile → config merge.
    run_fast_onboard — full fast onboarding async entrypoint.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from sevn.config.errors import UnsupportedSchemaVersionError
from sevn.config.workspace_config import (
    effective_encrypted_file_key_source,
    parse_workspace_config,
)
from sevn.onboarding.dashboard_url import apply_web_ui_url_for_dashboard
from sevn.onboarding.draft_store import write_draft
from sevn.onboarding.live_validate import (
    ValidationReport,
    handoff_credential_keys_for_doc,
    run_live_validation,
)
from sevn.onboarding.merge import merge_layers
from sevn.onboarding.profiles import load_profile_fragment
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.seed import resolve_agent_display_name, seed_narrative_templates
from sevn.onboarding.validate import validate_workspace_document
from sevn.onboarding.web_app import (
    apply_model_slot_policy,
    normalize_secrets_backend_section,
)
from sevn.onboarding.wizard_credentials import credentials_status
from sevn.pdf.native_libs import maybe_install_pdf_native_libs_after_promote
from sevn.workspace.layout import WorkspaceLayout

_DEFAULT_AGENT_NAME = "Sevn"


class FastOnboardError(Exception):
    """Base failure for fast onboarding (carries CLI exit code).

    Args:
        message (str): Operator-facing error text.
    """

    exit_code: int = 2

    def __init__(self, message: str) -> None:
        """Store ``message`` for CLI stderr and exit-code mapping.

        Args:
            message (str): Operator-facing error text.

        Examples:
            >>> err = FastOnboardValidationError("bad config")
            >>> err.message
            'bad config'
        """
        super().__init__(message)
        self.message = message


class FastOnboardValidationError(FastOnboardError):
    """Schema, credentials, or live validation blocked promote."""

    exit_code = 2


class FastOnboardPreconditionError(FastOnboardError):
    """Post-promote service handoff failed."""

    exit_code = 4


@dataclass(frozen=True)
class FastOnboardResult:
    """Outcome of a successful ``run_fast_onboard``."""

    sevn_json_path: Path
    seeded_paths: tuple[Path, ...]
    daemon_install_line: str | None
    pdf_native_install_line: str | None
    services_restart: dict[str, Any] | None


def merge_config_layers(
    config_doc: dict[str, Any],
    *,
    profile_id: str | None,
) -> dict[str, Any]:
    """Merge shipped defaults, optional profile, and ``--config`` document.

    Args:
        config_doc (dict[str, Any]): Parsed config file root object.
        profile_id (str | None): Optional preset fragment id.

    Returns:
        dict[str, Any]: Deep-merged workspace document.

    Examples:
        >>> merged = merge_config_layers(
        ...     {"schema_version": 1, "workspace_root": "."},
        ...     profile_id=None,
        ... )
        >>> merged["schema_version"]
        1
    """
    layers: list[dict[str, Any]] = [{"schema_version": 1, "workspace_root": "."}]
    if profile_id is not None:
        layers.append(load_profile_fragment(profile_id))
    layers.append(config_doc)
    return merge_layers(*layers)


def _format_validation_exception(exc: Exception) -> str:
    """Build operator-facing text for schema validation failures.

    Args:
        exc (Exception): ``ValidationError`` or other config error.

    Returns:
        str: Redacted, multi-line summary.

    Examples:
        >>> _format_validation_exception(ValueError("bad gateway.port"))
        'bad gateway.port'
    """
    if isinstance(exc, ValidationError):
        parts: list[str] = []
        for err in exc.errors():
            loc_parts = [str(p) for p in err.get("loc", ()) if p != "__root__"]
            loc = ".".join(loc_parts) or "(root)"
            parts.append(f"{loc}: {err.get('msg', '')}")
        return "; ".join(parts[:8]) or "validation failed"
    return str(exc)


def _apply_bot_name(
    merged: dict[str, Any],
    *,
    bot_name: str | None,
    prompt_for_bot_name: bool,
) -> None:
    """Set ``agent.display_name`` from flag, TTY prompt, or existing config.

    Args:
        merged (dict[str, Any]): Merged workspace document (mutated in place).
        bot_name (str | None): Explicit ``--bot-name`` override.
        prompt_for_bot_name (bool): When True on a TTY, prompt before promote.

    Raises:
        FastOnboardValidationError: When no non-empty name is available.

    Examples:
        >>> doc: dict[str, Any] = {"agent": {"display_name": "Nova"}}
        >>> _apply_bot_name(doc, bot_name="Luluu", prompt_for_bot_name=False)
        >>> doc["agent"]["display_name"]
        'Luluu'
    """
    if bot_name is not None:
        chosen = bot_name.strip()
        if not chosen:
            msg = "agent.display_name cannot be empty (--bot-name)"
            raise FastOnboardValidationError(msg)
        merged.setdefault("agent", {})["display_name"] = chosen
        return

    interactive = prompt_for_bot_name and sys.stdin.isatty() and sys.stdout.isatty()
    if interactive:
        default = resolve_agent_display_name(merged)
        if default == _DEFAULT_AGENT_NAME:
            default = "sevn"
        chosen = typer.prompt("Bot name", default=default).strip()
        if not chosen:
            msg = "agent.display_name is required"
            raise FastOnboardValidationError(msg)
        merged.setdefault("agent", {})["display_name"] = chosen
        return

    agent = merged.get("agent")
    if isinstance(agent, dict):
        raw = agent.get("display_name")
        if isinstance(raw, str) and raw.strip():
            return
    msg = (
        "agent.display_name is required in the config file "
        "(set agent.display_name or pass --bot-name)"
    )
    raise FastOnboardValidationError(msg)


def _format_live_validation_errors(report: ValidationReport) -> str:
    """Summarize failed error-severity live checks for stderr.

    Args:
        report (ValidationReport): Probe report from ``run_live_validation``.

    Returns:
        str: Multi-line operator message.

    Examples:
        >>> from sevn.onboarding.live_validate import ValidationCheck
        >>> rep = ValidationReport(
        ...     checks=[
        ...         ValidationCheck("x", False, "error", "failed", hint="fix it"),
        ...     ]
        ... )
        >>> "x" in _format_live_validation_errors(rep)
        True
    """
    lines: list[str] = []
    for check in report.checks:
        if check.ok or check.severity != "error":
            continue
        line = f"{check.check_id}: {check.detail}"
        if check.hint:
            line = f"{line} ({check.hint})"
        lines.append(line)
    return "\n".join(lines) if lines else "live validation failed"


async def run_fast_onboard(
    *,
    config_doc: dict[str, Any],
    profile_id: str | None,
    bot_name: str | None = None,
    prompt_for_bot_name: bool = True,
    install_daemon: bool = True,
    start_services: bool = True,
    seed_secrets: dict[str, str] | None = None,
) -> FastOnboardResult:
    """Validate, promote, seed, install daemons, and start gateway/proxy (`--config`).

    Args:
        config_doc (dict[str, Any]): Parsed ``--config`` file body.
        profile_id (str | None): Optional ``--profile`` fragment applied before config.
        bot_name (str | None): ``--bot-name`` override for ``agent.display_name``.
        prompt_for_bot_name (bool): When True on a TTY, prompt for bot name.
        install_daemon (bool): Run post-promote daemon install when allowed.
        start_services (bool): Call ``restart_services_after_promote`` after promote.
        seed_secrets (dict[str, str] | None): Logical alias to plaintext map written into
            the workspace store before the credential gate (used by ``onboard fast``).

    Returns:
        FastOnboardResult: Paths and handoff metadata.

    Raises:
        FastOnboardValidationError: Schema, credentials, or live validation failure.
        FastOnboardPreconditionError: Service restart failure after promote.

    Examples:
        >>> run_fast_onboard.__name__
        'run_fast_onboard'
    """
    # Imported lazily: ``sevn.cli`` eagerly loads ``sevn.cli.app``, which imports this
    # module back — a module-level import here makes ``import sevn.onboarding.fast_onboard``
    # fail with a circular import when it is imported before ``sevn.cli.app``.
    from sevn.cli.install_gate import maybe_install_daemon_after_promote
    from sevn.cli.operator_lock import operator_lock
    from sevn.cli.workspace import bound_sevn_json_path, bound_workspace_dir, sevn_home_dir

    sevn_path = bound_sevn_json_path()
    bound_workspace_dir().mkdir(parents=True, exist_ok=True)

    merged = merge_config_layers(config_doc, profile_id=profile_id)
    _apply_bot_name(merged, bot_name=bot_name, prompt_for_bot_name=prompt_for_bot_name)
    apply_model_slot_policy(merged)
    normalize_secrets_backend_section(merged)
    from sevn.config.provider_secrets import apply_provider_credential_bindings

    apply_provider_credential_bindings(merged)

    try:
        validate_workspace_document(merged)
    except (ValidationError, UnsupportedSchemaVersionError, ValueError) as exc:
        raise FastOnboardValidationError(_format_validation_exception(exc)) from exc

    cfg = parse_workspace_config(merged)
    layout = WorkspaceLayout.from_config(sevn_path, cfg)
    if seed_secrets:
        await _seed_secrets_into_store(cfg, content_root=layout.content_root, secrets=seed_secrets)
    await _async_check_credentials(merged, content_root=layout.content_root)

    report = await run_live_validation(
        workspace_root=bound_workspace_dir(),
        merged_preview=merged,
        profile_id=profile_id,
    )
    if report.has_error():
        detail = _format_live_validation_errors(report)
        raise FastOnboardValidationError(detail)

    apply_web_ui_url_for_dashboard(merged)
    with operator_lock(sevn_home_dir()):
        write_draft(sevn_path, merged)
        promote_draft(sevn_path, backup_previous=sevn_path.is_file())
    seeded = tuple(seed_narrative_templates(sevn_path, merged))

    pdf_native_line = maybe_install_pdf_native_libs_after_promote()

    daemon_line = maybe_install_daemon_after_promote(
        install_daemon_flag=install_daemon,
        reuse=False,
    )

    services_restart: dict[str, Any] | None = None
    if start_services:
        from sevn.onboarding.service_restart import restart_services_after_promote

        try:
            services_restart = await asyncio.to_thread(
                restart_services_after_promote,
                sevn_json_path=sevn_path,
            )
        except Exception as exc:
            msg = (
                f"promoted config to {sevn_path} but service handoff failed: {exc} "
                "(see logs/gateway.log and logs/proxy.log)"
            )
            raise FastOnboardPreconditionError(msg) from exc

    return FastOnboardResult(
        sevn_json_path=sevn_path,
        seeded_paths=seeded,
        daemon_install_line=daemon_line,
        pdf_native_install_line=pdf_native_line,
        services_restart=services_restart,
    )


async def _async_check_credentials(
    merged: dict[str, Any],
    *,
    content_root: Path,
) -> None:
    """Async credentials gate used by ``run_fast_onboard``.

    Args:
        merged (dict[str, Any]): Merged workspace document.
        content_root (Path): Workspace content root.

    Raises:
        FastOnboardValidationError: When required keys or keystore unlock fail.

    Examples:
        >>> _async_check_credentials.__name__
        '_async_check_credentials'
    """
    cfg = parse_workspace_config(merged)
    key_source = effective_encrypted_file_key_source(cfg.secrets_backend)
    if key_source == "master_key":
        from sevn.security.secrets.factory import parse_optional_master_key_hex

        if parse_optional_master_key_hex() is None:
            msg = (
                "encrypted secrets store key_source=master_key requires a 64-hex "
                "SEVN_SECRETS_MASTER_KEY before onboarding"
            )
            raise FastOnboardValidationError(msg)
    status = await credentials_status(content_root, section=cfg.secrets_backend)
    if key_source != "master_key" and status.get("needs_passphrase"):
        msg = (
            "encrypted secrets store requires SEVN_SECRETS_PASSPHRASE "
            "(or unlock the keystore before onboarding)"
        )
        raise FastOnboardValidationError(msg)
    required = handoff_credential_keys_for_doc(merged)
    if not required:
        return
    present = status.get("present")
    present_map = present if isinstance(present, dict) else {}
    missing = sorted(k for k in required if not present_map.get(k))
    if missing:
        msg = "missing required credentials in environment or secrets chain: " + ", ".join(missing)
        raise FastOnboardValidationError(msg)


async def _seed_secrets_into_store(
    cfg: Any,
    *,
    content_root: Path,
    secrets: dict[str, str],
) -> None:
    """Write exported secrets into the workspace encrypted store before the credential gate.

    Primes the unlock env var from the bundle (passphrase mode) so the store seals under the
    declared mechanism, mirrors that unlock secret into the macOS Keychain for daemon
    self-unlock, and exports ``SEVN_*`` aliases into the process env so live validation and
    the credential gate resolve them.

    Args:
        cfg (Any): Parsed ``WorkspaceConfig`` for the target workspace.
        content_root (Path): Resolved workspace content root.
        secrets (dict[str, str]): Logical alias to plaintext map to persist.

    Raises:
        FastOnboardValidationError: When the encrypted store cannot be opened for writes.

    Examples:
        >>> _seed_secrets_into_store.__name__
        '_seed_secrets_into_store'
    """
    from sevn.config.workspace_config import effective_encrypted_file_key_source
    from sevn.secrets.migrate import encrypted_file_backend_for_workspace
    from sevn.security.secrets.passphrase_prime import unlock_env_var_for

    if not secrets:
        return
    key_source = effective_encrypted_file_key_source(cfg.secrets_backend)
    unlock_var = unlock_env_var_for(key_source)
    if not os.environ.get(unlock_var, "").strip():
        bundled = secrets.get(unlock_var, "").strip()
        if bundled:
            os.environ[unlock_var] = bundled
    try:
        backend = encrypted_file_backend_for_workspace(content_root, cfg)
    except ValueError as exc:
        raise FastOnboardValidationError(str(exc)) from exc
    for alias in sorted(secrets):
        await backend.set(alias, secrets[alias])
    for alias, value in secrets.items():
        if alias.startswith("SEVN_") and value.strip():
            os.environ.setdefault(alias, value.strip())
    unlock_value = os.environ.get(unlock_var, "").strip()
    if sys.platform == "darwin" and unlock_value:
        from sevn.security.secrets.backends.macos_keychain import MacOSKeychainBackend

        with contextlib.suppress(Exception):
            await MacOSKeychainBackend().set(unlock_var, unlock_value, allow_any_app=True)


__all__ = [
    "FastOnboardError",
    "FastOnboardPreconditionError",
    "FastOnboardResult",
    "FastOnboardValidationError",
    "merge_config_layers",
    "run_fast_onboard",
]
