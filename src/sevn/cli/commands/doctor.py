"""``sevn doctor`` (`specs/23-cli.md` §3).

Module: sevn.cli.commands.doctor
Depends: json, shutil, sqlite3, subprocess, typing, httpx, typer, sevn.cli.*

Exports:
    register — attach ``doctor`` command to the root Typer app.
"""

from __future__ import annotations

import json
import shutil  # noqa: F401 — tests monkeypatch sevn.cli.commands.doctor.shutil
import subprocess  # noqa: F401  # nosec B404 — tests monkeypatch sevn.cli.commands.doctor.subprocess
from typing import Any

import typer

from sevn.cli.asyncio_util import run_sync_coro  # noqa: F401
from sevn.cli.doctor import (
    CheckResult,
    DoctorCheck,
    DoctorRunOptions,
    render_doctor_report,
    render_fix_lines,
    run_doctor_probes,
)
from sevn.cli.doctor.agent import AgentRunReport, run_doctor_with_agent
from sevn.cli.doctor.fix import FixContext, FixReport, apply_safe_fixes
from sevn.cli.doctor.sections import section_for, title_for
from sevn.cli.doctor.solutions import SolutionsCatalog, load_solutions_catalog
from sevn.cli.errors import CliPreconditionError
from sevn.cli.gateway_client import (  # noqa: F401
    gateway_get,
    gateway_listen_conflict_detail,
    probe_gateway_listen_state,
    proxy_healthz_get,
    resolve_proxy_base_url,
)
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.render import check_warn, configure_render, plain_echo, section
from sevn.cli.workspace import load_bound_workspace, load_doctor_workspace
from sevn.onboarding.live_validate import (  # noqa: F401
    probe_llm_reachability,
    probe_secrets_backend,
    probe_webapp_https,
)
from sevn.secrets.migrate import (
    legacy_plaintext_entries,
    non_legacy_files_present,
    promote_legacy_plaintext_to_encrypted_store_sync,
    secrets_dir_under_content_root,
)
from sevn.security.secrets.errors import SecretsStoreCorruptError


def register(app: typer.Typer) -> None:
    """Attach ``sevn doctor`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command("doctor")
    def doctor(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write the doctor report as a JSON envelope on stdout instead of human-readable lines.",
        ),
        strict: bool = typer.Option(False, "--strict", help="Treat warnings as failures."),
        check_extensions: bool = typer.Option(
            False,
            "--check-extensions",
            help="Validate setuptools plugin entry points for hooks, channels, and dashboard badges.",
        ),
        with_telegram_probe: bool = typer.Option(
            False,
            "--with-telegram-probe",
            help="Run an optional Telegram Bot API probe (off by default; not implemented in v1).",
        ),
        retry: bool = typer.Option(
            False,
            "--retry",
            help="Reserved for wider gateway GET retries when that behavior is implemented.",
        ),
        migrate_secrets: bool = typer.Option(
            False,
            "--migrate-secrets",
            help="Promote legacy plaintext files under `.sevn/secrets/` into encrypted `store.enc`.",
        ),
        migrate_yes: bool = typer.Option(
            False,
            "--yes",
            "-y",
            help="Non-interactive consent for `--migrate-secrets` and `--fix` mutations.",
        ),
        do_fix: bool = typer.Option(
            False,
            "--fix",
            help="Apply safe auto-fixes from the solutions catalog (requires `--yes` when non-interactive).",
        ),
        with_agent: bool = typer.Option(
            False,
            "--with-agent",
            help="Run the tier-B diagnostic agent on failing checks; apply fixes after confirmation.",
        ),
        diagnostics_model: str | None = typer.Option(
            None,
            "--model",
            help="Override ``agent.diagnostics`` model slot for ``--with-agent``.",
        ),
        user_model: bool = typer.Option(
            False,
            "--user-model",
            help="Print an inferred Honcho user-model profile snapshot for the bound workspace.",
        ),
        code_orientation: bool = typer.Option(
            False,
            "--code-orientation",
            help="Report code-understanding readiness (SEVN_REPO_ROOT, Graphify, MYCODE) and refresh scan cache.",
        ),
    ) -> None:
        """Run local + gateway health probes for this workspace."""
        _ = retry
        if user_model:

            def user_model_doctor() -> None:
                command = "sevn doctor --user-model"
                try:
                    bw_um = load_bound_workspace()
                except CliPreconditionError as exc:
                    if json_out:
                        emit_json_failure(
                            command=command,
                            error_code="WORKSPACE_PRECONDITION",
                            message=str(exc),
                            exit_code=4,
                        )
                    else:
                        typer.secho(str(exc), err=True)
                    raise typer.Exit(4) from exc

                from sevn.memory.user_model.queue import USER_MODEL_PROMPT_REV
                from sevn.memory.user_model.store import UserModelStore

                root = bw_um.layout.content_root
                um_cfg = (
                    bw_um.config.memory.user_model
                    if bw_um.config.memory and bw_um.config.memory.user_model
                    else None
                )
                enabled = bool(um_cfg and um_cfg.enabled)
                prof = UserModelStore().load(str(root))
                active = [f for f in prof.facts if f.superseded_by_id is None]
                payload: dict[str, Any] = {
                    "enabled": enabled,
                    "prompt_rev": USER_MODEL_PROMPT_REV,
                    "profile_path": str(root / ".sevn" / "user_model.json"),
                    "fact_count": len(prof.facts),
                    "active_fact_count": len(active),
                    "deny_topics": list(um_cfg.deny_topics) if um_cfg else [],
                    "updated_at": prof.updated_at.isoformat(),
                }
                if json_out:
                    emit_json_success(command=command, data=payload)
                else:
                    typer.echo(json.dumps(payload, indent=2, sort_keys=True))
                raise typer.Exit(0)

            user_model_doctor()

        if code_orientation:

            def code_orientation_doctor() -> None:
                from sevn.code_understanding.bootstrap import (
                    code_orientation_doctor_checks,
                    mycode_needs_refresh,
                    refresh_mycode_scan_cache,
                )
                from sevn.config.sevn_repo import resolve_sevn_checkout_for_workspace

                command = "sevn doctor --code-orientation"
                try:
                    bw_co = load_bound_workspace()
                except CliPreconditionError as exc:
                    if json_out:
                        emit_json_failure(
                            command=command,
                            error_code="WORKSPACE_PRECONDITION",
                            message=str(exc),
                            exit_code=4,
                        )
                    else:
                        typer.secho(str(exc), err=True)
                    raise typer.Exit(4) from exc

                checkout = resolve_sevn_checkout_for_workspace(
                    bw_co.config,
                    content_root=bw_co.layout.content_root,
                )
                warn_lines = code_orientation_doctor_checks(bw_co.config, checkout)
                refreshed = False
                if checkout is not None and mycode_needs_refresh(checkout):
                    refresh_mycode_scan_cache(checkout)
                    refreshed = True
                payload = {
                    "checkout": str(checkout) if checkout is not None else None,
                    "warnings": warn_lines,
                    "mycode_scan_refreshed": refreshed,
                }
                if json_out:
                    emit_json_success(command=command, data=payload)
                else:
                    if checkout is not None:
                        plain_echo(f"code_orientation: checkout={checkout}")
                    if warn_lines:
                        section("Code orientation")
                        for line in warn_lines:
                            check_warn(line)
                    if refreshed:
                        plain_echo("code_orientation: refreshed .sevn/mycode-scan.cache.json")
                    if not warn_lines:
                        plain_echo("code_orientation: ready")
                raise typer.Exit(0)

            code_orientation_doctor()

        if migrate_secrets:

            def migrate_plaintext_cli() -> None:
                command = "sevn doctor --migrate-secrets"
                try:
                    bw_m = load_bound_workspace()
                except CliPreconditionError as exc:
                    if json_out:
                        emit_json_failure(
                            command=command,
                            error_code="WORKSPACE_PRECONDITION",
                            message=str(exc),
                            exit_code=4,
                        )
                    else:
                        typer.secho(str(exc), err=True)
                    raise typer.Exit(4) from exc

                secrets_dir = secrets_dir_under_content_root(bw_m.layout.content_root)
                suspicious = non_legacy_files_present(secrets_dir)
                if suspicious and not migrate_yes:
                    msg = (
                        f"refusing migrate: unexpected files under {secrets_dir}: "
                        f"{', '.join(suspicious)}. Move or remove them, or re-run with --yes "
                        "after operator review."
                    )
                    if json_out:
                        emit_json_failure(
                            command=command,
                            error_code="MIGRATE_REVIEW_REQUIRED",
                            message=msg,
                            exit_code=4,
                            details={"unexpected_files": suspicious},
                        )
                    else:
                        typer.secho(msg, err=True)
                    raise typer.Exit(4)

                try:
                    legacy = legacy_plaintext_entries(secrets_dir)
                except ValueError as exc:
                    if json_out:
                        emit_json_failure(
                            command=command,
                            error_code="LEGACY_LAYOUT_INVALID",
                            message=str(exc),
                            exit_code=4,
                        )
                    else:
                        typer.secho(str(exc), err=True)
                    raise typer.Exit(4) from exc

                if not legacy:
                    detail = f"no legacy plaintext material under {secrets_dir}"
                    if json_out:
                        emit_json_success(
                            command=command,
                            data={
                                "keys_written": 0,
                                "removed_legacy_files": [],
                                "detail": detail,
                            },
                        )
                    else:
                        typer.echo(detail)
                    raise typer.Exit(0)

                count = len(legacy)
                if not migrate_yes:
                    proceed = typer.confirm(
                        f"Migrate {count} logical secret(s) from legacy plaintext under "
                        f"{secrets_dir} into the encrypted store (legacy artifacts removed "
                        "after success)?",
                    )
                    if not proceed:
                        typer.secho("migrate aborted", err=True)
                        raise typer.Exit(4)

                try:
                    result = promote_legacy_plaintext_to_encrypted_store_sync(
                        content_root=bw_m.layout.content_root,
                        workspace_config=bw_m.config,
                        legacy_overwrites_encrypted=True,
                        delete_legacy_after=True,
                    )
                except ValueError as exc:
                    if json_out:
                        emit_json_failure(
                            command=command,
                            error_code="SECRETS_PRECONDITION",
                            message=str(exc),
                            exit_code=4,
                        )
                    else:
                        typer.secho(str(exc), err=True)
                    raise typer.Exit(4) from exc
                except SecretsStoreCorruptError as exc:
                    if json_out:
                        emit_json_failure(
                            command=command,
                            error_code="SECRETS_STORE_CORRUPT",
                            message=str(exc),
                            exit_code=4,
                        )
                    else:
                        typer.secho(str(exc), err=True)
                    raise typer.Exit(4) from exc

                payload = {
                    "keys_written": result.keys_written,
                    "keys_skipped_existing": result.keys_skipped_existing,
                    "removed_legacy_files": result.removed_legacy_files,
                }
                if json_out:
                    emit_json_success(command=command, data=payload)
                else:
                    typer.echo(
                        f"migrate-secrets: wrote {result.keys_written} key(s); "
                        f"removed legacy files {result.removed_legacy_files}",
                    )
                raise typer.Exit(0)

            migrate_plaintext_cli()

        from sevn.branding import maybe_play_logo_splash

        if not json_out:
            maybe_play_logo_splash()

        configure_render(json_mode=json_out)
        command = "sevn doctor" + (" --with-agent" if with_agent else "")
        result = CheckResult()

        try:
            bw = load_doctor_workspace()
        except CliPreconditionError as exc:
            detail = str(exc)
            result.add(
                DoctorCheck(
                    id="sevn_json",
                    section=section_for("sevn_json"),
                    title=title_for("sevn_json"),
                    ok=False,
                    severity="error",
                    detail=detail,
                ),
            )
            result.errors.append(detail)
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="WORKSPACE_PRECONDITION",
                    message=detail,
                    exit_code=4,
                    details={"checks": result.to_json_checks(), "warnings": result.warnings},
                )
            else:
                typer.secho(detail, err=True)
            raise typer.Exit(4) from exc

        run_doctor_probes(
            bw,
            result,
            options=DoctorRunOptions(
                check_extensions=check_extensions,
                with_telegram_probe=with_telegram_probe,
            ),
        )

        catalog: SolutionsCatalog = load_solutions_catalog()
        fix_report: FixReport | None = None
        agent_report: AgentRunReport | None = None
        probe_options = DoctorRunOptions(
            check_extensions=check_extensions,
            with_telegram_probe=with_telegram_probe,
        )
        if do_fix:
            fix_report = apply_safe_fixes(
                FixContext(bw=bw, yes=migrate_yes, interactive=not json_out),
                result,
                catalog=catalog,
            )
            if fix_report.fixed:
                result = CheckResult()
                run_doctor_probes(
                    bw,
                    result,
                    options=probe_options,
                )
            if not json_out:
                render_fix_lines(fix_report)

        if with_agent:
            result, agent_report = run_doctor_with_agent(
                bw=bw,
                result=result,
                catalog=catalog,
                model_override=diagnostics_model,
                yes=migrate_yes,
                interactive=not json_out,
                probe_options=probe_options,
            )

        def _json_checks() -> list[dict[str, Any]]:
            return result.to_json_checks(include_solutions=json_out, catalog=catalog)

        def _json_data() -> dict[str, Any]:
            payload: dict[str, Any] = {
                "checks": _json_checks(),
                "warnings": result.warnings,
            }
            if fix_report is not None:
                payload["fixed"] = fix_report.fixed
                payload["manual"] = fix_report.manual
            if agent_report is not None:
                payload.update(agent_report.to_json())
            return payload

        warn_fail = strict and result.warnings
        if result.errors or warn_fail:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="DOCTOR_FAILED",
                    message="; ".join(result.errors) or "strict mode: warnings elevated",
                    exit_code=4,
                    details=_json_data(),
                )
            else:
                render_doctor_report(result, success=False, catalog=catalog)
            raise typer.Exit(4)

        if json_out:
            emit_json_success(command=command, data=_json_data())
        else:
            render_doctor_report(result, success=True, catalog=catalog)
        raise typer.Exit(0)
