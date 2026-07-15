"""Safe auto-fix whitelist for ``sevn doctor --fix`` (`specs/23-cli.md` §3).

Module: sevn.cli.doctor.fix
Depends: pathlib, shutil, sqlite3, typing, typer, sevn.cli.doctor.solutions,
    sevn.cli.operator_lock, sevn.security.llmignore, sevn.secrets.migrate

Exports:
    FixContext — workspace + consent flags for fix handlers.
    FixOutcome — one applied or manual fix row.
    FixReport — ``fixed`` / ``manual`` lists for ``--json``.
    apply_safe_fixes — run whitelisted fixes for failing/warn checks.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import typer

from sevn.cli.doctor.checks import CheckResult, DoctorCheck
from sevn.cli.doctor.solutions import SolutionsCatalog, load_solutions_catalog, lookup_solution
from sevn.cli.operator_lock import (
    _lock_held_by_dead_process,
    lock_file_appears_stale,
    operator_lock_path,
)
from sevn.cli.workspace import sevn_home_dir
from sevn.config.defaults import DEFAULT_LLMIGNORE_REL_PATH
from sevn.runtime.operator_path import operator_path_prefixes
from sevn.secrets.migrate import (
    legacy_plaintext_entries,
    non_legacy_files_present,
    promote_legacy_plaintext_to_encrypted_store_sync,
    secrets_dir_under_content_root,
)
from sevn.security.llmignore import ensure_llmignore_layout
from sevn.security.secrets.errors import SecretsStoreCorruptError
from sevn.storage.sqlite import open_sevn_sqlite

WAL_CHECKPOINT_THRESHOLD_BYTES: int = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FixContext:
    """Inputs for one doctor auto-fix pass."""

    bw: Any
    yes: bool
    interactive: bool


@dataclass(frozen=True, slots=True)
class FixOutcome:
    """One fix attempt result for human or JSON output."""

    check_id: str
    status: Literal["fixed", "manual", "skipped"]
    detail: str


@dataclass
class FixReport:
    """Aggregated ``--fix`` results."""

    fixed: list[dict[str, str]] = field(default_factory=list)
    manual: list[dict[str, str]] = field(default_factory=list)

    def add(self, outcome: FixOutcome) -> None:
        """Record one outcome in ``fixed`` or ``manual``.

        Args:
            outcome (FixOutcome): Row to append.

        Returns:
            None

        Examples:
            >>> r = FixReport()
            >>> r.add(FixOutcome("operator_lock", "fixed", "removed stale lock"))
            >>> r.fixed[0]["check_id"]
            'operator_lock'
        """
        row = {"check_id": outcome.check_id, "detail": outcome.detail}
        if outcome.status == "fixed":
            self.fixed.append(row)
        elif outcome.status == "manual":
            self.manual.append(row)


def _needs_confirm(ctx: FixContext, prompt: str) -> bool:
    """Return True when mutation may proceed (``--yes`` or interactive confirm).

    Args:
        ctx (FixContext): Consent flags.
        prompt (str): Typer confirm message.

    Returns:
        bool: Whether to apply the fix.

    Examples:
        >>> _needs_confirm(FixContext(None, yes=True, interactive=False), "x?")
        True
    """
    if ctx.yes:
        return True
    if ctx.interactive:
        return typer.confirm(prompt, default=False)
    return False


def _fix_operator_lock(ctx: FixContext) -> FixOutcome | None:
    """Remove a stale operator lock file when safe.

    Args:
        ctx (FixContext): Fix pass inputs.

    Returns:
        FixOutcome | None: Applied outcome or ``None`` when not applicable.

    Examples:
        >>> _fix_operator_lock(FixContext(None, yes=True, interactive=False))  # doctest: +SKIP
    """
    lock_path = operator_lock_path(sevn_home_dir())
    if not lock_path.is_file():
        return None
    stale = lock_file_appears_stale(lock_path) or _lock_held_by_dead_process(lock_path)
    if not stale:
        return FixOutcome(
            "operator_lock",
            "manual",
            "lock held by a live process — stop the other `sevn` command first",
        )
    if not _needs_confirm(ctx, f"Remove stale operator lock at {lock_path}?"):
        return FixOutcome("operator_lock", "manual", "stale lock left in place (re-run with --yes)")
    lock_path.unlink(missing_ok=True)
    return FixOutcome("operator_lock", "fixed", f"removed stale lock {lock_path}")


def _fix_llmignore(ctx: FixContext) -> FixOutcome | None:
    """Ensure ``.llmignore/`` layout exists and is not a symlink.

    Args:
        ctx (FixContext): Fix pass inputs.

    Returns:
        FixOutcome | None: Applied outcome or ``None`` when not applicable.

    Examples:
        >>> _fix_llmignore(FixContext(None, yes=True, interactive=False))  # doctest: +SKIP
    """
    root = ctx.bw.layout.content_root
    llm_path = root / DEFAULT_LLMIGNORE_REL_PATH
    if llm_path.is_dir() and not llm_path.is_symlink():
        return None
    if llm_path.is_symlink():
        if not _needs_confirm(ctx, f"Replace symlink {llm_path} with a real directory?"):
            return FixOutcome("llmignore", "manual", "symlink left in place (re-run with --yes)")
        llm_path.unlink(missing_ok=True)
    elif not llm_path.exists():
        if not _needs_confirm(ctx, f"Create {llm_path} layout?"):
            return FixOutcome(
                "llmignore", "manual", "missing layout left unchanged (re-run with --yes)"
            )
    created = ensure_llmignore_layout(root, ctx.bw.config)
    return FixOutcome("llmignore", "fixed", f"ensured .llmignore layout at {created}")


def _fix_second_brain_vault_layout(ctx: FixContext) -> FixOutcome | None:
    """Bootstrap missing Second Brain vault layout when enabled.

    Args:
        ctx (FixContext): Fix pass inputs.

    Returns:
        FixOutcome | None: Applied outcome or ``None`` when not applicable.

    Examples:
        >>> _fix_second_brain_vault_layout(FixContext(None, yes=True, interactive=False))  # doctest: +SKIP
    """
    from sevn.second_brain.layout_probe import (
        fix_second_brain_layout,
        probe_second_brain_vault_layout,
    )

    probe = probe_second_brain_vault_layout(
        config=ctx.bw.config,
        content_root=ctx.bw.layout.content_root,
        raw_doc=ctx.bw.raw,
    )
    if probe is None or probe.ok:
        return None
    sb_cfg = ctx.bw.config.second_brain
    check_id = (
        "second_brain_vault_layout_para"
        if sb_cfg is not None and sb_cfg.layout == "para"
        else "second_brain_vault_layout"
    )
    if not _needs_confirm(ctx, f"Bootstrap Second Brain layout at {probe.scope_root_relative}?"):
        return FixOutcome(
            check_id,
            "manual",
            "layout left incomplete (re-run with --yes)",
        )
    created = fix_second_brain_layout(
        config=ctx.bw.config,
        content_root=ctx.bw.layout.content_root,
    )
    detail = f"created {', '.join(created)}" if created else "layout already complete"
    return FixOutcome(check_id, "fixed", detail)


def _fix_sqlite_wal(ctx: FixContext) -> FixOutcome | None:
    """Checkpoint a large SQLite WAL file.

    Args:
        ctx (FixContext): Fix pass inputs.

    Returns:
        FixOutcome | None: Applied outcome or ``None`` when not applicable.

    Examples:
        >>> _fix_sqlite_wal(FixContext(None, yes=True, interactive=False))  # doctest: +SKIP
    """
    db_dir = ctx.bw.layout.dot_sevn
    wal_path = db_dir / "sevn.db-wal"
    if not wal_path.is_file() or wal_path.stat().st_size < WAL_CHECKPOINT_THRESHOLD_BYTES:
        return None
    size_mb = wal_path.stat().st_size // (1024 * 1024)
    if not _needs_confirm(ctx, f"Checkpoint SQLite WAL ({size_mb} MiB at {wal_path})?"):
        return FixOutcome("sqlite", "manual", "large WAL left unchanged (re-run with --yes)")
    conn = open_sevn_sqlite(db_dir)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()
    return FixOutcome("sqlite", "fixed", f"checkpointed WAL at {wal_path}")


def _fix_secrets_backend(ctx: FixContext) -> FixOutcome | None:
    """Promote legacy plaintext secrets into the encrypted store.

    Args:
        ctx (FixContext): Fix pass inputs.

    Returns:
        FixOutcome | None: Applied outcome or ``None`` when not applicable.

    Examples:
        >>> _fix_secrets_backend(FixContext(None, yes=True, interactive=False))  # doctest: +SKIP
    """
    secrets_dir = secrets_dir_under_content_root(ctx.bw.layout.content_root)
    try:
        legacy = legacy_plaintext_entries(secrets_dir)
    except ValueError as exc:
        return FixOutcome("secrets_backend", "manual", str(exc))
    if not legacy:
        return None
    suspicious = non_legacy_files_present(secrets_dir)
    if suspicious and not ctx.yes:
        return FixOutcome(
            "secrets_backend",
            "manual",
            f"unexpected files under {secrets_dir}: {', '.join(suspicious)} — review then re-run with --yes",
        )
    if not _needs_confirm(
        ctx,
        f"Migrate {len(legacy)} legacy plaintext secret(s) into encrypted store?",
    ):
        return FixOutcome(
            "secrets_backend", "manual", "legacy plaintext left in place (re-run with --yes)"
        )
    try:
        result = promote_legacy_plaintext_to_encrypted_store_sync(
            content_root=ctx.bw.layout.content_root,
            workspace_config=ctx.bw.config,
            legacy_overwrites_encrypted=True,
            delete_legacy_after=True,
        )
    except (ValueError, SecretsStoreCorruptError) as exc:
        return FixOutcome("secrets_backend", "manual", str(exc))
    return FixOutcome(
        "secrets_backend",
        "fixed",
        f"migrated {result.keys_written} key(s); removed {result.removed_legacy_files}",
    )


def _broken_sevn_symlinks() -> list[Path]:
    """Return broken ``sevn`` symlinks on the operator PATH.

    Returns:
        list[Path]: Symlink paths whose targets are missing.

    Examples:
        >>> isinstance(_broken_sevn_symlinks(), list)
        True
    """
    seen: set[Path] = set()
    broken: list[Path] = []
    which = shutil.which("sevn")
    if which:
        candidate = Path(which)
        if candidate not in seen:
            seen.add(candidate)
            if candidate.is_symlink() and not candidate.exists():
                broken.append(candidate)
    for prefix in operator_path_prefixes():
        candidate = prefix / "sevn"
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_symlink() and not candidate.exists():
            broken.append(candidate)
    return broken


def _fix_provider_credentials(ctx: FixContext) -> FixOutcome | None:
    """Prompt for and store missing per-provider API keys (D7).

    Args:
        ctx (FixContext): Fix pass inputs.

    Returns:
        FixOutcome | None: Applied outcome or ``None`` when not applicable.

    Examples:
        >>> _fix_provider_credentials(FixContext(None, yes=True, interactive=False))  # doctest: +SKIP
    """
    import asyncio
    import copy

    from sevn.config.provider_credential_validate import collect_missing_provider_credentials
    from sevn.config.provider_registry import provider_credential_ref
    from sevn.config.provider_secrets import (
        apply_provider_credential_bindings,
        migrate_legacy_provider_api_key,
        provider_credential_ref_for_name,
    )
    from sevn.onboarding.draft_store import write_draft
    from sevn.onboarding.promote import promote_draft
    from sevn.onboarding.validate import validate_workspace_document
    from sevn.onboarding.wizard_credentials import store_wizard_credentials

    migrated = asyncio.run(
        migrate_legacy_provider_api_key(
            ctx.bw.layout.content_root,
            ctx.bw.raw,
            section=ctx.bw.config.secrets_backend,
        )
    )
    if migrated:
        updated = copy.deepcopy(ctx.bw.raw)
        apply_provider_credential_bindings(updated)
        try:
            validate_workspace_document(updated)
        except ValueError as exc:
            return FixOutcome("provider_credentials", "manual", str(exc))
        write_draft(ctx.bw.sevn_json_path, updated)
        promote_draft(ctx.bw.sevn_json_path, backup_previous=ctx.bw.sevn_json_path.is_file())
        aliases = ", ".join(sorted(migrated))
        return FixOutcome(
            "provider_credentials",
            "fixed",
            f"migrated SEVN_PROVIDER_API_KEY to {aliases}",
        )

    missing = collect_missing_provider_credentials(ctx.bw.config)
    if not missing:
        return None
    provider_keys: dict[str, str] = {}
    for row in missing:
        if provider_credential_ref(ctx.bw.config, row.provider_name):
            continue
        prompt = f"API key for provider {row.provider_name!r} (slot {row.slot} uses {row.model_id})"
        if (ctx.interactive and not ctx.yes) and not typer.confirm(
            f"Prompt to store credential for {row.provider_name!r}?"
        ):
            continue
        key = typer.prompt(prompt, hide_input=True) if ctx.interactive or ctx.yes else ""
        if ctx.yes and not key:
            key = typer.prompt(prompt, hide_input=True)
        text = str(key).strip()
        if not text:
            return FixOutcome(
                "provider_credentials",
                "manual",
                f"empty key for {row.provider_name!r} — left unchanged",
            )
        provider_keys[row.provider_name] = text
    if not provider_keys:
        return FixOutcome(
            "provider_credentials",
            "manual",
            "missing credentials remain — re-run with --yes in an interactive shell",
        )
    if not _needs_confirm(
        ctx,
        f"Store provider API key(s) for {', '.join(sorted(provider_keys))}?",
    ):
        return FixOutcome(
            "provider_credentials",
            "manual",
            "provider keys left unchanged (re-run with --yes)",
        )
    asyncio.run(
        store_wizard_credentials(
            ctx.bw.layout.content_root,
            provider_api_keys=provider_keys,
            section=ctx.bw.config.secrets_backend,
        ),
    )
    updated = copy.deepcopy(ctx.bw.raw)
    apply_provider_credential_bindings(updated)
    providers = updated.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        updated["providers"] = providers
    for name in provider_keys:
        entry = providers.get(name)
        if not isinstance(entry, dict):
            entry = {}
            providers[name] = entry
        entry["api_key"] = provider_credential_ref_for_name(name)
    try:
        validate_workspace_document(updated)
    except ValueError as exc:
        return FixOutcome("provider_credentials", "manual", str(exc))
    write_draft(ctx.bw.sevn_json_path, updated)
    promote_draft(ctx.bw.sevn_json_path, backup_previous=ctx.bw.sevn_json_path.is_file())
    names = ", ".join(sorted(provider_keys))
    return FixOutcome("provider_credentials", "fixed", f"stored provider credentials for {names}")


def _fix_openai_oauth_credential(ctx: FixContext) -> FixOutcome | None:
    """Prompt for Codex OAuth reauth when ``oauth.openai`` is missing or expired (W5).

    Args:
        ctx (FixContext): Fix pass inputs.

    Returns:
        FixOutcome | None: Applied outcome or ``None`` when not applicable.

    Examples:
        >>> _fix_openai_oauth_credential(FixContext(None, yes=True, interactive=False))  # doctest: +SKIP
    """
    from sevn.cli.asyncio_util import run_sync_coro
    from sevn.config.workspace_config import effective_encrypted_file_key_source
    from sevn.onboarding.live_validate import (
        openai_oauth_mode_active,
        probe_openai_oauth_credential,
    )
    from sevn.security.oauth.authorize import build_authorization_flow
    from sevn.security.oauth.login_flow import complete_codex_oauth_login
    from sevn.security.secrets.factory import secrets_chain_from_workspace
    from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain

    if not openai_oauth_mode_active(ctx.bw.raw):
        return None

    chain = secrets_chain_from_workspace(ctx.bw.layout.content_root, ctx.bw.config.secrets_backend)
    check = probe_openai_oauth_credential(ctx.bw.raw, secrets_chain=chain)
    if check.ok:
        return None

    if not _needs_confirm(
        ctx,
        "Sign in with ChatGPT (Codex OAuth) to store oauth.openai?",
    ):
        return FixOutcome(
            "openai_oauth_credential",
            "manual",
            "oauth.openai left unchanged — re-run with --yes in an interactive shell",
        )

    if not ctx.interactive and not ctx.yes:
        return FixOutcome(
            "openai_oauth_credential",
            "manual",
            "run `sevn providers oauth login --provider openai` in an interactive shell",
        )

    key_source = effective_encrypted_file_key_source(ctx.bw.config.secrets_backend)
    run_sync_coro(reconcile_unlock_env_with_keychain(key_source=key_source))
    flow = build_authorization_flow()
    typer.echo(flow.authorize_url)
    if not ctx.yes:
        typer.echo("Complete authorization in your browser, then return here.")
    try:
        credential = run_sync_coro(
            complete_codex_oauth_login(
                flow,
                chain,
                headless=not ctx.interactive,
            ),
        )
    except ValueError as exc:
        return FixOutcome("openai_oauth_credential", "manual", str(exc))

    return FixOutcome(
        "openai_oauth_credential",
        "fixed",
        f"stored oauth.openai for account_id={credential.account_id}",
    )


def _fix_sevn_cli(ctx: FixContext) -> FixOutcome | None:
    """Remove a broken ``sevn`` CLI symlink.

    Args:
        ctx (FixContext): Fix pass inputs.

    Returns:
        FixOutcome | None: Applied outcome or ``None`` when not applicable.

    Examples:
        >>> _fix_sevn_cli(FixContext(None, yes=True, interactive=False))  # doctest: +SKIP
    """
    broken = _broken_sevn_symlinks()
    if not broken:
        return None
    target = broken[0]
    if not _needs_confirm(ctx, f"Remove broken `sevn` symlink at {target}?"):
        return FixOutcome(
            "sevn_cli", "manual", f"broken symlink left at {target} (re-run with --yes)"
        )
    target.unlink(missing_ok=True)
    return FixOutcome(
        "sevn_cli",
        "fixed",
        f"removed broken symlink {target} — run `make install-cli` to reinstall",
    )


_FIX_HANDLERS: dict[str, Any] = {
    "operator_lock": _fix_operator_lock,
    "llmignore": _fix_llmignore,
    "second_brain_vault_layout": _fix_second_brain_vault_layout,
    "second_brain_vault_layout_para": _fix_second_brain_vault_layout,
    "sqlite": _fix_sqlite_wal,
    "secrets_backend": _fix_secrets_backend,
    "provider_credentials": _fix_provider_credentials,
    "openai_oauth_credential": _fix_openai_oauth_credential,
    "sevn_cli": _fix_sevn_cli,
}


def _is_actionable(check: DoctorCheck) -> bool:
    """Return True when a check row is eligible for ``--fix``.

    Args:
        check (DoctorCheck): Probe row to evaluate.

    Returns:
        bool: Whether the row failed or warned.

    Examples:
        >>> _is_actionable(DoctorCheck("x", "Workspace", "x", False, severity="warn"))
        True
    """
    if not check.ok:
        return True
    return check.severity == "warn"


def apply_safe_fixes(
    ctx: FixContext,
    result: CheckResult,
    *,
    catalog: SolutionsCatalog | None = None,
) -> FixReport:
    """Apply whitelisted auto-fixes for failing/warn checks with ``auto_fixable`` catalog rows.

    Args:
        ctx (FixContext): Workspace + consent flags.
        result (CheckResult): Current probe results.
        catalog (SolutionsCatalog | None): Optional pre-loaded catalog.

    Returns:
        FixReport: ``fixed`` and ``manual`` rows for rendering and ``--json``.

    Examples:
        >>> apply_safe_fixes(
        ...     FixContext(None, yes=True, interactive=False),
        ...     CheckResult(),
        ... ).fixed
        []
    """
    doc = catalog or load_solutions_catalog()
    report = FixReport()
    seen: set[str] = set()
    for check in result.checks:
        if not _is_actionable(check):
            continue
        solution = lookup_solution(check.id, doc)
        if solution is None or not solution.auto_fixable:
            continue
        handler = _FIX_HANDLERS.get(check.id)
        if handler is None:
            continue
        if check.id in seen:
            continue
        seen.add(check.id)
        outcome = handler(ctx)
        if outcome is None:
            continue
        report.add(outcome)

    _CUA_MANUAL_FIX_IDS = frozenset(
        {
            "cua_cli_binary",
            "cua_driver_binary",
            "cua_tcc_accessibility",
            "cua_tcc_automation",
            "cua_tcc_screen_recording",
            "lume_binary",
        },
    )
    for check in result.checks:
        if check.ok or check.id not in _CUA_MANUAL_FIX_IDS or check.id in seen:
            continue
        solution = lookup_solution(check.id, doc)
        if solution is None:
            continue
        seen.add(check.id)
        hint = solution.fix_command or (
            solution.remediation[0] if solution.remediation else solution.explanation
        )
        report.add(FixOutcome(check.id, "manual", hint))
    return report


__all__ = [
    "WAL_CHECKPOINT_THRESHOLD_BYTES",
    "FixContext",
    "FixOutcome",
    "FixReport",
    "apply_safe_fixes",
]
