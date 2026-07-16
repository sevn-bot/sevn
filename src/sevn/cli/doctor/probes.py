"""Doctor probe runners registered as ``DoctorCheck`` rows (`specs/23-cli.md` §3).

Module: sevn.cli.doctor.probes
Depends: json, os, shutil, sqlite3, subprocess, sys, typing, sevn.cli.doctor.*

Exports:
    DoctorRunOptions — flags that affect which probes run.
    run_doctor_probes — execute all probes into a ``CheckResult``.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from sevn.cli.doctor.checks import CheckResult, DoctorCheck, Severity
from sevn.cli.doctor.fix import WAL_CHECKPOINT_THRESHOLD_BYTES
from sevn.cli.doctor.sections import section_for, title_for
from sevn.cli.errors import CliAuthError, CliPreconditionError
from sevn.cli.operator_lock import (
    STALE_LOCK_TTL_SECONDS,
    lock_file_age_seconds,
    lock_file_appears_stale,
    operator_lock_path,
)
from sevn.cli.workspace import sevn_home_dir
from sevn.config.defaults import (
    DEFAULT_LLMIGNORE_REL_PATH,
    DEFAULT_SELF_IMPROVE_ENABLED,
    DEFAULT_SELF_IMPROVE_HUB_USE_GITHUB,
)
from sevn.config.my_sevn import effective_my_sevn, effective_my_sevn_sync
from sevn.config.settings import ProcessSettings
from sevn.onboarding.live_validate import section_uses_encrypted_file
from sevn.runtime.operator_path import operator_path_prefixes
from sevn.secrets.migrate import legacy_plaintext_entries, secrets_dir_under_content_root
from sevn.storage.sqlite import open_sevn_sqlite


def _doctor_cmd() -> Any:
    """Return the ``commands.doctor`` module (lazy for test monkeypatch targets).

    Returns:
        ModuleType: ``sevn.cli.commands.doctor``.

    Examples:
        >>> mod = _doctor_cmd()
        >>> hasattr(mod, "gateway_get")
        True
    """
    from sevn.cli.commands import doctor as doctor_cmd

    return doctor_cmd


@dataclass(frozen=True)
class DoctorRunOptions:
    """Flags that control optional doctor probes."""

    check_extensions: bool = False
    with_telegram_probe: bool = False


def run_doctor_probes(
    bw: Any,
    result: CheckResult,
    *,
    options: DoctorRunOptions,
) -> None:
    """Run all standard doctor probes into ``result`` (registration order preserved).

    Args:
        bw (Any): Bound doctor workspace from ``load_doctor_workspace()``.
        result (CheckResult): Collector for checks, warnings, and errors.
        options (DoctorRunOptions): Optional probe flags.

    Returns:
        None

    Examples:
        >>> from unittest.mock import MagicMock
        >>> from sevn.cli.doctor.checks import CheckResult
        >>> run_doctor_probes(MagicMock(), CheckResult(), options=DoctorRunOptions())  # doctest: +SKIP
    """
    doc = _doctor_cmd()

    result.add(
        DoctorCheck(
            id="sevn_json",
            section=section_for("sevn_json"),
            title=title_for("sevn_json"),
            ok=True,
            detail=str(bw.sevn_json_path),
        ),
    )

    from sevn.cli.gateway_client import resolve_gateway_token
    from sevn.gateway.runtime.gateway_token import GATEWAY_TOKEN_LOGICAL_KEY
    from sevn.secrets.fingerprint import fingerprint_sha256_hex

    def _raw_gateway_token_ref(raw_doc: dict[str, Any]) -> str:
        gateway_section = raw_doc.get("gateway")
        if not isinstance(gateway_section, dict):
            return ""
        return str(gateway_section.get("token") or "").strip()

    gw_ref = _raw_gateway_token_ref(bw.raw)
    resolved_gw: str | None = None
    if gw_ref:
        try:
            resolved_gw = resolve_gateway_token(
                workspace=bw.config,
                content_root=bw.layout.content_root,
            )
        except Exception as exc:
            resolved_gw = None
            gt_resolve_note = str(exc)
        else:
            gt_resolve_note = ""
    else:
        gt_resolve_note = ""
    if not gw_ref:
        gt_detail = "gateway.token missing in sevn.json"
        gt_ok = False
        gt_hint = "run `sevn gateway set-gateway-token` (auto-generate) or pass --set-value"
        gt_severity: Severity = "error"
    elif not resolved_gw:
        gt_detail = f"gateway.token ref present but {GATEWAY_TOKEN_LOGICAL_KEY!r} unresolved"
        if gt_resolve_note:
            gt_detail = f"{gt_detail} ({gt_resolve_note})"
        gt_ok = False
        gt_severity = "error"
        if gt_resolve_note:
            gt_hint = (
                "unlock the secrets store (`sevn secrets store-passphrase --stdin` on macOS, "
                "or `sevn secrets check-unlock`); then run `sevn gateway set-gateway-token`"
            )
        else:
            gt_hint = (
                "run `sevn gateway set-gateway-token` to store "
                f"{GATEWAY_TOKEN_LOGICAL_KEY!r} in the secrets chain"
            )
    else:
        gt_ok = True
        gt_detail = f"ref={gw_ref!r}; fingerprint={fingerprint_sha256_hex(resolved_gw)}"
        gt_hint = ""
        gt_severity = None
    gt_check = DoctorCheck(
        id="gateway_token_configured",
        section=section_for("gateway_token_configured"),
        title=title_for("gateway_token_configured"),
        ok=gt_ok,
        severity=gt_severity,
        detail=gt_detail,
        hint=gt_hint or None,
    )
    result.checks.append(gt_check)
    if not gt_ok:
        result.errors.append(f"gateway token: {gt_detail} — {gt_hint}")

    from sevn.config.provider_credential_validate import (
        collect_missing_provider_credentials,
        collect_unused_declared_providers,
        format_unused_provider_warning,
    )

    missing_providers = collect_missing_provider_credentials(bw.config)
    unused_providers = collect_unused_declared_providers(bw.config)
    if missing_providers:
        missing_detail = "; ".join(
            f"{row.slot} ({row.model_id}) → {row.provider_name}" for row in missing_providers
        )
        pc_hint = (
            "set providers.<name>.api_key in sevn.json and store the key, "
            "or run `sevn doctor --fix` to prompt and store missing keys"
        )
        result.add(
            DoctorCheck(
                id="provider_credentials",
                section=section_for("provider_credentials"),
                title=title_for("provider_credentials"),
                ok=False,
                severity="warn",
                detail=f"missing provider credentials: {missing_detail}",
                hint=pc_hint,
            ),
        )
        result.warnings.append(f"provider_credentials: {missing_detail}")
    elif unused_providers:
        unused_detail = ", ".join(unused_providers)
        result.add(
            DoctorCheck(
                id="provider_credentials",
                section=section_for("provider_credentials"),
                title=title_for("provider_credentials"),
                ok=True,
                severity="warn",
                detail=f"unused declared providers: {unused_detail}",
            ),
        )
        for name in unused_providers:
            result.warnings.append(format_unused_provider_warning(name))
    else:
        result.add(
            DoctorCheck(
                id="provider_credentials",
                section=section_for("provider_credentials"),
                title=title_for("provider_credentials"),
                ok=True,
                detail="assigned model slots have resolvable provider credentials",
            ),
        )

    from sevn.onboarding.live_validate import probe_openai_oauth_credential
    from sevn.security.secrets.factory import secrets_chain_from_workspace

    oauth_chain = secrets_chain_from_workspace(bw.layout.content_root, bw.config.secrets_backend)
    oauth_vc = probe_openai_oauth_credential(bw.raw, secrets_chain=oauth_chain)
    result.add_validation(oauth_vc)
    if not oauth_vc.ok:
        result.warnings.append(f"openai_oauth_credential: {oauth_vc.detail}")

    my_sevn_cfg = effective_my_sevn(bw.config)
    sync_cfg = effective_my_sevn_sync(bw.config)
    hub = (
        bw.config.self_improve.hub
        if bw.config.self_improve and bw.config.self_improve.hub
        else None
    )
    self_improve_enabled = (
        bw.config.self_improve.enabled
        if bw.config.self_improve is not None
        else DEFAULT_SELF_IMPROVE_ENABLED
    )
    use_github = hub.use_github if hub is not None else DEFAULT_SELF_IMPROVE_HUB_USE_GITHUB
    my_sevn_detail = (
        f"repo_url={my_sevn_cfg.repo_url}; sync_enabled={sync_cfg.enabled}; "
        f"sync_cron={sync_cfg.cron}; self_improve.enabled={self_improve_enabled}; "
        f"self_improve.hub.use_github={use_github}"
    )
    result.add(
        DoctorCheck(
            id="my_sevn",
            section=section_for("my_sevn"),
            title=title_for("my_sevn"),
            ok=True,
            detail=my_sevn_detail,
        ),
    )

    from sevn.config.my_sevn import effective_my_sevn_issues, effective_my_sevn_pipelines

    evo_issues_cfg = effective_my_sevn_issues(bw.config)
    if evo_issues_cfg.auto_run_on_import:
        evo_pipelines_cfg = effective_my_sevn_pipelines(bw.config)
        dry_run_active = (
            evo_pipelines_cfg.ci_dry_run_default or evo_pipelines_cfg.promotion_dry_run_default
        )
        if dry_run_active:
            auto_run_hint = (
                "auto_run_on_import=true but pipeline dry-run defaults are active "
                f"(ci_dry_run={evo_pipelines_cfg.ci_dry_run_default}, "
                f"promotion_dry_run={evo_pipelines_cfg.promotion_dry_run_default}); "
                "imported issues will be scheduled but runs will not produce real PRs "
                "until dry-run flags are disabled in my_sevn.pipelines"
            )
            result.add(
                DoctorCheck(
                    id="auto_run_on_import",
                    section=section_for("auto_run_on_import"),
                    title=title_for("auto_run_on_import"),
                    ok=True,
                    severity="warn",
                    detail=auto_run_hint,
                ),
            )
            result.warnings.append(f"auto_run_on_import: {auto_run_hint}")
        else:
            result.add(
                DoctorCheck(
                    id="auto_run_on_import",
                    section=section_for("auto_run_on_import"),
                    title=title_for("auto_run_on_import"),
                    ok=True,
                    detail="enabled; live pipelines",
                ),
            )

    from sevn.code_understanding.bootstrap import code_orientation_doctor_checks
    from sevn.config.sevn_repo import resolve_sevn_checkout_for_workspace

    checkout = resolve_sevn_checkout_for_workspace(
        bw.config,
        content_root=bw.layout.content_root,
    )
    co_warnings = code_orientation_doctor_checks(bw.config, checkout)
    if co_warnings:
        for line in co_warnings:
            result.warnings.append(line)
        result.add(
            DoctorCheck(
                id="code_orientation",
                section=section_for("code_orientation"),
                title=title_for("code_orientation"),
                ok=False,
                severity="warn",
                detail="; ".join(co_warnings),
            ),
        )
    else:
        detail = f"checkout={checkout}" if checkout is not None else "no sevn.bot checkout resolved"
        result.add(
            DoctorCheck(
                id="code_orientation",
                section=section_for("code_orientation"),
                title=title_for("code_orientation"),
                ok=True,
                detail=detail,
            ),
        )

    lock_path = operator_lock_path(sevn_home_dir())
    if lock_path.is_file():
        age_s = int(lock_file_age_seconds(lock_path))
        stale = lock_file_appears_stale(lock_path)
        lock_detail = (
            f"{lock_path} age={age_s}s (TTL={STALE_LOCK_TTL_SECONDS}s); "
            "mutating CLI commands auto-clear stale locks when the holder PID is dead"
        )
        result.add(
            DoctorCheck(
                id="operator_lock",
                section=section_for("operator_lock"),
                title=title_for("operator_lock"),
                ok=not stale,
                severity="warn" if stale else None,
                detail=lock_detail,
            ),
        )
        if stale:
            result.warnings.append(
                "operator lock file appears stale — if no other `sevn` is running, "
                f"remove {lock_path} or run a mutating command to recover",
            )
    else:
        result.add(
            DoctorCheck(
                id="operator_lock",
                section=section_for("operator_lock"),
                title=title_for("operator_lock"),
                ok=True,
                detail=f"no lock file at {lock_path}",
            ),
        )

    sevn_which = shutil.which("sevn")
    broken_cli: list[Path] = []
    seen_cli: set[Path] = set()
    if sevn_which:
        candidate = Path(sevn_which)
        seen_cli.add(candidate)
        if candidate.is_symlink() and not candidate.exists():
            broken_cli.append(candidate)
    for prefix in operator_path_prefixes():
        candidate = prefix / "sevn"
        if candidate in seen_cli:
            continue
        seen_cli.add(candidate)
        if candidate.is_symlink() and not candidate.exists():
            broken_cli.append(candidate)
    if broken_cli:
        cli_detail = f"broken symlink: {broken_cli[0]}"
        result.add(
            DoctorCheck(
                id="sevn_cli",
                section=section_for("sevn_cli"),
                title=title_for("sevn_cli"),
                ok=False,
                severity="warn",
                detail=cli_detail,
            )
        )
        result.warnings.append(cli_detail)
    elif sevn_which:
        result.add(
            DoctorCheck(
                id="sevn_cli",
                section=section_for("sevn_cli"),
                title=title_for("sevn_cli"),
                ok=True,
                detail=sevn_which,
            )
        )
    else:
        result.add(
            DoctorCheck(
                id="sevn_cli",
                section=section_for("sevn_cli"),
                title=title_for("sevn_cli"),
                ok=False,
                severity="warn",
                detail="sevn not found on PATH",
            )
        )
        result.warnings.append("sevn not found on PATH — run `make install-cli`")

    if options.check_extensions:
        try:
            from sevn.plugins.registry import (
                collect_plugin_slash_bindings,
                load_channel_plugin_classes,
                load_dashboard_badge_entries,
                load_plugin_hook_chain,
            )

            ph = load_plugin_hook_chain(bw.config, ProcessSettings())
            collect_plugin_slash_bindings(ph)
            chn = load_channel_plugin_classes(bw.config)
            badges = load_dashboard_badge_entries(bw.config)
            result.add(
                DoctorCheck(
                    id="extensions",
                    section=section_for("extensions"),
                    title=title_for("extensions"),
                    ok=True,
                    detail=(
                        f"plugin_hooks+channels entry points ok ({len(ph.hooks)} hooks, "
                        f"{len(chn)} channel classes, {len(badges)} dashboard badges)"
                    ),
                ),
            )
        except Exception as exc:
            detail = str(exc)
            result.add(
                DoctorCheck(
                    id="extensions",
                    section=section_for("extensions"),
                    title=title_for("extensions"),
                    ok=False,
                    severity="error",
                    detail=detail,
                ),
            )
            result.errors.append(f"extensions: {detail}")

    try:
        conn = open_sevn_sqlite(bw.layout.dot_sevn)
        conn.close()
        sqlite_detail = "sevn.db opened + migrations applied"
        sqlite_severity: Severity = None
        wal_path = bw.layout.dot_sevn / "sevn.db-wal"
        if wal_path.is_file():
            wal_size = wal_path.stat().st_size
            if wal_size >= WAL_CHECKPOINT_THRESHOLD_BYTES:
                sqlite_severity = "warn"
                sqlite_detail = f"{sqlite_detail}; wal={wal_size} bytes (threshold={WAL_CHECKPOINT_THRESHOLD_BYTES})"
                result.warnings.append(f"sqlite WAL large ({wal_size} bytes)")
        result.add(
            DoctorCheck(
                id="sqlite",
                section=section_for("sqlite"),
                title=title_for("sqlite"),
                ok=True,
                severity=sqlite_severity,
                detail=sqlite_detail,
            )
        )
    except (OSError, sqlite3.Error) as exc:
        result.add(
            DoctorCheck(
                id="sqlite",
                section=section_for("sqlite"),
                title=title_for("sqlite"),
                ok=False,
                severity="error",
                detail=str(exc),
            ),
        )
        result.errors.append(f"sqlite: {exc}")

    vc = doc.run_sync_coro(
        doc.probe_secrets_backend(
            content_root=bw.layout.content_root,
            section=bw.config.secrets_backend,
            strict_encrypted_file=section_uses_encrypted_file(bw.config.secrets_backend),
        ),
    )
    result.add_validation(vc)

    secrets_dir = secrets_dir_under_content_root(bw.layout.content_root)
    try:
        legacy_secrets = legacy_plaintext_entries(secrets_dir)
    except ValueError as exc:
        legacy_secrets = {}
        result.errors.append(f"secrets_backend: {exc}")
    if legacy_secrets:
        legacy_msg = f"legacy plaintext material: {len(legacy_secrets)} key(s) under {secrets_dir}"
        for idx, check in enumerate(result.checks):
            if check.id == "secrets_backend":
                result.checks[idx] = DoctorCheck(
                    id="secrets_backend",
                    section=section_for("secrets_backend"),
                    title=title_for("secrets_backend"),
                    ok=False,
                    severity="error",
                    detail=legacy_msg,
                    hint=check.hint,
                )
                break
        else:
            result.add(
                DoctorCheck(
                    id="secrets_backend",
                    section=section_for("secrets_backend"),
                    title=title_for("secrets_backend"),
                    ok=False,
                    severity="error",
                    detail=legacy_msg,
                )
            )
        result.errors.append(f"secrets_backend: {legacy_msg}")

    if section_uses_encrypted_file(bw.config.secrets_backend):
        from sevn.config.workspace_config import effective_encrypted_file_key_source
        from sevn.security.secrets.passphrase_prime import (
            keychain_has_unlock_secret,
            unlock_env_var_for,
        )

        ks = effective_encrypted_file_key_source(bw.config.secrets_backend)
        unlock_var = unlock_env_var_for(ks)
        in_env = bool(os.environ.get(unlock_var, "").strip())
        in_keychain = bool(doc.run_sync_coro(keychain_has_unlock_secret(key_source=ks)))
        if not in_env and not in_keychain:
            msg = (
                f"{unlock_var} is absent from env and macOS Keychain — daemons cannot open the "
                "encrypted store after reboot. Fix: run `sevn secrets store-passphrase` (macOS) "
                f"or export {unlock_var} before `sevn gateway start`"
            )
            result.add(
                DoctorCheck(
                    id="keychain_unlock",
                    section=section_for("keychain_unlock"),
                    title=title_for("keychain_unlock"),
                    ok=False,
                    severity="error",
                    detail=msg,
                ),
            )
            result.errors.append(f"keychain_unlock: {msg}")
        elif in_env and not in_keychain and sys.platform == "darwin":
            msg = (
                f"{unlock_var} is set in this shell but not stored in the macOS Keychain — the "
                "gateway daemon will lose it on logout/reboot. Run `sevn secrets store-passphrase` "
                "to make self-unlock survive reboot"
            )
            result.add(
                DoctorCheck(
                    id="keychain_unlock",
                    section=section_for("keychain_unlock"),
                    title=title_for("keychain_unlock"),
                    ok=False,
                    severity="warn",
                    detail=msg,
                ),
            )
            result.warnings.append(msg)
        else:
            result.add(
                DoctorCheck(
                    id="keychain_unlock",
                    section=section_for("keychain_unlock"),
                    title=title_for("keychain_unlock"),
                    ok=True,
                    detail=f"{unlock_var} reachable (env={in_env}, keychain={in_keychain})",
                ),
            )

    webapp_vc = doc.probe_webapp_https(merged_preview=bw.config.model_dump())
    result.add_validation(webapp_vc)

    try:
        docker_bin = doc.shutil.which("docker")
        if docker_bin is None:
            raise FileNotFoundError("docker not in PATH")
        doc.subprocess.run(  # nosec B603
            [docker_bin, "info"],
            check=True,
            capture_output=True,
            timeout=8.0,
        )
        result.add(
            DoctorCheck(
                id="docker",
                section=section_for("docker"),
                title=title_for("docker"),
                ok=True,
                detail="docker info succeeded",
            ),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"docker info failed ({exc})"
        result.add(
            DoctorCheck(
                id="docker",
                section=section_for("docker"),
                title=title_for("docker"),
                ok=False,
                severity="warn",
                detail=msg,
            ),
        )
        result.warnings.append(msg)

    from sevn.skills.browser_session import browser_readiness_snapshot

    readiness = browser_readiness_snapshot(bw.layout.content_root, bw.config)
    if readiness.executable:
        kind = "Brave" if readiness.is_brave else "Chromium-family"
        head_mode = "headless" if readiness.headless else "headed"
        rd_detail = f"{kind} binary {readiness.executable} (engine={readiness.engine}, {head_mode})"
        if readiness.cdp_url:
            rd_detail = f"{rd_detail}; CDP {readiness.cdp_url} reachable={readiness.cdp_ok}"
    else:
        rd_detail = (
            f"no browser binary resolved (engine={readiness.engine}, "
            f"headless={'yes' if readiness.headless else 'no'})"
        )
    result.add(
        DoctorCheck(
            id="browser_readiness",
            section=section_for("browser_readiness"),
            title=title_for("browser_readiness"),
            ok=readiness.executable is not None,
            severity="warn" if readiness.executable is None else None,
            detail=rd_detail,
            hint=None
            if readiness.executable
            else "Install Chrome/Brave or use Docker profile browser/gui with Brave preinstalled",
        ),
    )
    if readiness.executable is None:
        result.warnings.append(rd_detail)

    from sevn.skills.cua_doctor_check import probe_cua_skill_checks

    for cua_row in probe_cua_skill_checks(bw.config):
        cua_severity: Severity = (
            cast(Literal["warn", "error"], cua_row.severity)  # noqa: TC006
            if cua_row.severity in ("warn", "error")
            else None
        )
        cua_check = DoctorCheck(
            id=cua_row.check_id,
            section=section_for(cua_row.check_id),
            title=title_for(cua_row.check_id),
            ok=cua_row.ok,
            severity=cua_severity,
            detail=cua_row.detail,
            hint=cua_row.hint,
        )
        result.add(cua_check)
        if not cua_row.ok:
            msg = f"{cua_row.check_id}: {cua_row.detail}"
            if cua_row.hint:
                msg = f"{msg} — fix: {cua_row.hint}"
            result.warnings.append(msg)

    from sevn.skills.openwiki_doctor_check import probe_openwiki_skill_checks_async

    openwiki_rows = doc.run_sync_coro(
        probe_openwiki_skill_checks_async(
            bw.config,
            content_root=bw.layout.content_root,
        ),
    )
    for ow_row in openwiki_rows:
        ow_severity: Severity = (
            cast(Literal["warn", "error"], ow_row.severity)  # noqa: TC006
            if ow_row.severity in ("warn", "error")
            else None
        )
        ow_check = DoctorCheck(
            id=ow_row.check_id,
            section=section_for(ow_row.check_id),
            title=title_for(ow_row.check_id),
            ok=ow_row.ok,
            severity=ow_severity,
            detail=ow_row.detail,
            hint=ow_row.hint,
        )
        result.add(ow_check)
        if not ow_row.ok:
            msg = f"{ow_row.check_id}: {ow_row.detail}"
            if ow_row.hint:
                msg = f"{msg} — fix: {ow_row.hint}"
            result.warnings.append(msg)

    from sevn.skills.security_scan import read_workspace_scan_summary, resolve_skillspector_command

    ss_cmd = resolve_skillspector_command()
    if ss_cmd:
        summary = read_workspace_scan_summary(bw.layout.content_root)
        if summary:
            hc = summary.get("high_critical", 0)
            paths = summary.get("scanned_paths") or []
            detail = (
                f"SkillSpector CLI ok; last workspace scan: {len(paths)} path(s), "
                f"{hc} HIGH/CRITICAL finding(s)"
            )
        else:
            detail = "SkillSpector CLI ok; no workspace scan summary yet (run: sevn skills security-scan)"
        result.add(
            DoctorCheck(
                id="skillspector",
                section=section_for("skillspector"),
                title=title_for("skillspector"),
                ok=True,
                detail=detail,
            ),
        )
    else:
        detail = (
            "SkillSpector not installed (optional) — install with: uv sync --extra skillspector"
        )
        result.add(
            DoctorCheck(
                id="skillspector",
                section=section_for("skillspector"),
                title=title_for("skillspector"),
                ok=True,
                detail=detail,
            ),
        )
        result.warnings.append(detail)

    from sevn.agent.runtimes.pyodide_deno import (
        deno_binary_on_path,
        effective_sandbox_exec_driver,
        resolve_sandbox_exec_driver,
        sandbox_exec_unavailable_note,
    )

    configured_driver = resolve_sandbox_exec_driver(bw.config)
    effective_driver = effective_sandbox_exec_driver(bw.config)
    if configured_driver == "pyodide_deno" or effective_driver == "pyodide_deno":
        deno = deno_binary_on_path()
        driver_label = configured_driver or "auto"
        effective_label = effective_driver or "unavailable"
        if deno:
            result.add(
                DoctorCheck(
                    id="pyodide_deno",
                    section=section_for("pyodide_deno"),
                    title=title_for("pyodide_deno"),
                    ok=True,
                    detail=(
                        f"deno at {deno} (configured={driver_label}, effective={effective_label})"
                    ),
                ),
            )
        else:
            pending_note = sandbox_exec_unavailable_note(bw.config)
            msg = pending_note or (
                f"Pyodide sandbox configured ({driver_label}) but deno not on PATH; "
                "install Deno (https://deno.com/) for sandbox_exec"
            )
            if configured_driver == "pyodide_deno" and effective_driver == "docker":
                msg = f"{msg} — gateway boot will downgrade to docker until Deno is installed"
            result.add(
                DoctorCheck(
                    id="pyodide_deno",
                    section=section_for("pyodide_deno"),
                    title=title_for("pyodide_deno"),
                    ok=False,
                    severity="warn",
                    detail=msg,
                ),
            )
            result.warnings.append(msg)

    proxy_url = doc.resolve_proxy_base_url(workspace=bw.config)
    proxy_health_ok = False
    try:
        pr = doc.proxy_healthz_get(proxy_url, liveness=True)
        ok = pr.status_code < 400
        proxy_health_ok = ok
        result.add(
            DoctorCheck(
                id="proxy_healthz",
                section=section_for("proxy_healthz"),
                title=title_for("proxy_healthz"),
                ok=ok,
                detail=f"GET {proxy_url.rstrip('/')}/healthz -> {pr.status_code}",
            ),
        )
        if not ok:
            result.errors.append(f"proxy /healthz returned {pr.status_code}")
    except CliPreconditionError as exc:
        result.add(
            DoctorCheck(
                id="proxy_healthz",
                section=section_for("proxy_healthz"),
                title=title_for("proxy_healthz"),
                ok=False,
                detail=str(exc),
            ),
        )
        result.errors.append(str(exc))

    if proxy_url and proxy_health_ok:
        llm_vc = doc.run_sync_coro(
            doc.probe_llm_reachability(
                merged_preview=bw.config.model_dump(),
                cfg_proxy=bw.config.proxy if isinstance(bw.config.proxy, dict) else None,
                fail_on_proxy_503=True,
            ),
        )
        result.add_validation(llm_vc)

    try:
        h = doc.gateway_get("/health", workspace=bw.config, liveness=True)
        result.add(
            DoctorCheck(
                id="gateway_health",
                section=section_for("gateway_health"),
                title=title_for("gateway_health"),
                ok=True,
                detail=h.text[:200],
            ),
        )
    except CliAuthError as exc:
        detail = str(exc)
        result.add(
            DoctorCheck(
                id="gateway_health",
                section=section_for("gateway_health"),
                title=title_for("gateway_health"),
                ok=False,
                detail=detail,
            ),
        )
        result.errors.append(f"gateway /health: {detail}")
    except CliPreconditionError as exc:
        detail = str(exc)
        if doc.probe_gateway_listen_state(workspace=bw.config) == "conflict":
            detail = doc.gateway_listen_conflict_detail(workspace=bw.config)
        result.add(
            DoctorCheck(
                id="gateway_health",
                section=section_for("gateway_health"),
                title=title_for("gateway_health"),
                ok=False,
                detail=detail,
            ),
        )
        result.errors.append(f"gateway /health: {detail}")

    try:
        rdy = doc.gateway_get("/ready", workspace=bw.config, liveness=True)
        body_raw = rdy.json() if "json" in (rdy.headers.get("content-type") or "").lower() else {}
        body: dict[str, Any] = body_raw if isinstance(body_raw, dict) else {}
        ready_ok = rdy.status_code < 500 and bool(body.get("ready", rdy.status_code < 400))
        detail = json.dumps(body)[:500] if body else rdy.text[:200]
        result.add(
            DoctorCheck(
                id="gateway_ready",
                section=section_for("gateway_ready"),
                title=title_for("gateway_ready"),
                ok=ready_ok,
                detail=detail,
            ),
        )
        if not ready_ok:
            result.errors.append("gateway /ready reports not ready")
    except CliAuthError as exc:
        detail = str(exc)
        result.add(
            DoctorCheck(
                id="gateway_ready",
                section=section_for("gateway_ready"),
                title=title_for("gateway_ready"),
                ok=False,
                detail=detail,
            ),
        )
        result.errors.append(f"gateway /ready: {detail}")
    except CliPreconditionError as exc:
        detail = str(exc)
        if doc.probe_gateway_listen_state(workspace=bw.config) == "conflict":
            detail = doc.gateway_listen_conflict_detail(workspace=bw.config)
        result.add(
            DoctorCheck(
                id="gateway_ready",
                section=section_for("gateway_ready"),
                title=title_for("gateway_ready"),
                ok=False,
                detail=detail,
            ),
        )
        result.errors.append(f"gateway /ready: {detail}")

    llm_path = bw.layout.content_root / DEFAULT_LLMIGNORE_REL_PATH
    if llm_path.is_symlink():
        msg = f"symlink — unsafe: {llm_path}"
        result.add(
            DoctorCheck(
                id="llmignore",
                section=section_for("llmignore"),
                title=title_for("llmignore"),
                ok=False,
                severity="warn",
                detail=msg,
            )
        )
        result.warnings.append(msg)
    elif llm_path.is_dir():
        result.add(
            DoctorCheck(
                id="llmignore",
                section=section_for("llmignore"),
                title=title_for("llmignore"),
                ok=True,
                detail=str(llm_path),
            ),
        )
    else:
        msg = f"missing {llm_path}"
        result.add(
            DoctorCheck(
                id="llmignore",
                section=section_for("llmignore"),
                title=title_for("llmignore"),
                ok=False,
                severity="warn",
                detail=msg,
            ),
        )
        result.warnings.append(msg)

    from sevn.pdf.doctor_check import probe_pdf_optional_extra, probe_weasyprint_render

    for pdf_row in (probe_weasyprint_render(), probe_pdf_optional_extra()):
        pdf_severity: Severity = (
            cast(Literal["warn", "error"], pdf_row.severity)  # noqa: TC006
            if pdf_row.severity in ("warn", "error")
            else None
        )
        pdf_check = DoctorCheck(
            id=pdf_row.check_id,
            section=section_for(pdf_row.check_id),
            title=title_for(pdf_row.check_id),
            ok=pdf_row.ok,
            severity=pdf_severity,
            detail=pdf_row.detail,
            hint=pdf_row.hint,
        )
        result.add(pdf_check)
        if not pdf_row.ok:
            msg = f"{pdf_row.check_id}: {pdf_row.detail}"
            if pdf_row.hint:
                msg = f"{msg} — fix: {pdf_row.hint}"
            if pdf_row.severity == "error":
                result.errors.append(msg)
            else:
                result.warnings.append(msg)

    from sevn.browser import HAS_CDP

    if HAS_CDP:
        cdp_detail = "websockets import ok; browser CDP engine available"
        cdp_ok = True
    else:
        cdp_detail = "browser engine missing — run: uv sync --extra browser-cdp"
        cdp_ok = False
    result.add(
        DoctorCheck(
            id="browser_cdp_engine",
            section=section_for("browser_cdp_engine"),
            title=title_for("browser_cdp_engine"),
            ok=cdp_ok,
            severity=None if cdp_ok else "warn",
            detail=cdp_detail,
            hint=None if cdp_ok else "uv sync --extra browser-cdp",
        )
    )
    if not cdp_ok:
        result.warnings.append(cdp_detail)

    _PP_BINARIES = {
        "pp_espn": "espn-pp-cli",
        "pp_flight_goat": "flight-goat-pp-cli",
        "pp_movie_goat": "movie-goat-pp-cli",
        "pp_recipe_goat": "recipe-goat-pp-cli",
    }
    _PP_INSTALL_HINT = "make printing-press-starter-pack"
    _pp_missing: list[str] = []
    for check_id, binary in _PP_BINARIES.items():
        found = doc.shutil.which(binary)
        if found:
            result.add(
                DoctorCheck(
                    id=check_id,
                    section=section_for(check_id),
                    title=title_for(check_id),
                    ok=True,
                    detail=f"{binary} at {found}",
                ),
            )
        else:
            result.add(
                DoctorCheck(
                    id=check_id,
                    section=section_for(check_id),
                    title=title_for(check_id),
                    ok=False,
                    severity="warn",
                    detail=f"{binary} not on PATH",
                    hint=_PP_INSTALL_HINT,
                ),
            )
            _pp_missing.append(binary)
    if _pp_missing:
        result.warnings.append(
            f"printing-press-library: {len(_pp_missing)} binary/binaries missing "
            f"({', '.join(_pp_missing)}) — fix: {_PP_INSTALL_HINT}"
        )

    from sevn.voice.factory import probe_voice_backends

    voice_probe = doc.run_sync_coro(probe_voice_backends(bw.config))
    voice_ok = bool(voice_probe.get("first_stt")) or bool(voice_probe.get("first_tts"))
    voice_detail = (
        f"STT={voice_probe.get('first_stt') or 'none'}; "
        f"TTS={voice_probe.get('first_tts') or 'none'}"
    )
    voice_hints = voice_probe.get("hints")
    voice_hint = (
        "; ".join(str(h) for h in voice_hints)
        if isinstance(voice_hints, list) and voice_hints
        else None
    )
    voice_check = DoctorCheck(
        id="voice_backends",
        section=section_for("voice_backends"),
        title=title_for("voice_backends"),
        ok=voice_ok or not voice_probe.get("enabled", True),
        detail=voice_detail,
        hint=voice_hint,
    )
    result.add(voice_check)
    if voice_probe.get("enabled", True) and not voice_ok:
        msg = f"voice_backends: no working STT/TTS backend ({voice_detail})"
        if voice_hint:
            msg = f"{msg} — {voice_hint}"
        result.warnings.append(msg)

    from sevn.second_brain.witchcraft_bridge import WitchcraftConfig, witchcraft_indexer_available

    wc_cfg = WitchcraftConfig.from_workspace_config(bw.config)
    if wc_cfg is not None:
        probe_ok = witchcraft_indexer_available(wc_cfg, workspace_path=bw.layout.content_root)
        wiki_paths = None
        if bw.config.second_brain.enabled:
            from sevn.second_brain.witchcraft_reindex import resolve_index_wiki_paths

            wiki_paths = resolve_index_wiki_paths(
                config=bw.config,
                content_root=bw.layout.content_root,
            )
        wiki_hint = ""
        if wiki_paths is not None:
            wiki_hint = f"; wiki={wiki_paths[0]}"
        wc_detail = (
            f"binary present and db exists{wiki_hint}"
            if probe_ok
            else f"binary or db not found{wiki_hint}"
        )
        result.add(
            DoctorCheck(
                id="witchcraft_probe",
                section=section_for("witchcraft_probe"),
                title=title_for("witchcraft_probe"),
                ok=probe_ok,
                detail=wc_detail,
            ),
        )
        if not probe_ok:
            result.warnings.append(
                "witchcraft_probe: witchcraft_enabled is set but probe failed "
                f"({wc_detail}); install the witchcraft binary, run "
                "`sevn second-brain reindex`, and verify witchcraft.db_path"
            )

    from sevn.second_brain.layout_probe import probe_second_brain_vault_layout

    sb_probe = probe_second_brain_vault_layout(
        config=bw.config,
        content_root=bw.layout.content_root,
        raw_doc=bw.raw,
    )
    if sb_probe is not None:
        result.add(
            DoctorCheck(
                id="second_brain_vault_layout",
                section=section_for("second_brain_vault_layout"),
                title=title_for("second_brain_vault_layout"),
                ok=sb_probe.ok,
                detail=sb_probe.detail,
                hint=sb_probe.hint,
            ),
        )
        if not sb_probe.ok:
            msg = f"second_brain_vault_layout: {sb_probe.detail}"
            if sb_probe.hint:
                msg = f"{msg} — {sb_probe.hint}"
            result.warnings.append(msg)

    _has_skillspector = doc.shutil.which("skillspector") is not None
    if _has_skillspector:
        result.add(
            DoctorCheck(
                id="skillspector_extra",
                section=section_for("skillspector_extra"),
                title=title_for("skillspector_extra"),
                ok=True,
                detail="SkillSpector CLI on PATH; CI runs make skillspector-check",
            ),
        )
    else:
        result.add(
            DoctorCheck(
                id="skillspector_extra",
                section=section_for("skillspector_extra"),
                title=title_for("skillspector_extra"),
                ok=False,
                severity="warn",
                detail="SkillSpector CLI not on PATH (optional)",
                hint="make skillspector-check (isolated uv install)",
            ),
        )
        result.warnings.append(
            "skillspector: CLI not on PATH — run make skillspector-check once to verify"
        )

    orphaned_count = 0
    try:
        db_path = bw.layout.content_root / ".sevn" / "sevn.db"
        if db_path.is_file():
            from sevn.storage.migrate import apply_migrations

            conn = sqlite3.connect(str(db_path))
            try:
                apply_migrations(conn)
                row = conn.execute(
                    "SELECT COUNT(*) FROM subagent_runs WHERE status = 'orphaned'",
                ).fetchone()
                orphaned_count = int(row[0]) if row else 0
            finally:
                conn.close()
    except Exception as exc:
        result.add(
            DoctorCheck(
                id="subagents_registry",
                section=section_for("subagents_registry"),
                title=title_for("subagents_registry"),
                ok=False,
                severity="warn",
                detail=f"subagent_runs storage probe failed: {exc}",
            ),
        )
    else:
        enabled = True
        if bw.config.subagents is not None:
            enabled = bool(bw.config.subagents.enabled)
        detail = f"enabled={enabled}; orphaned_runs={orphaned_count}"
        result.add(
            DoctorCheck(
                id="subagents_registry",
                section=section_for("subagents_registry"),
                title=title_for("subagents_registry"),
                ok=True,
                detail=detail,
            ),
        )
        if orphaned_count:
            result.warnings.append(
                f"subagents: {orphaned_count} orphaned run(s) in storage — boot sweep marks stale rows",
            )

    if options.with_telegram_probe:
        result.add(
            DoctorCheck(
                id="telegram_probe",
                section=section_for("telegram_probe"),
                title=title_for("telegram_probe"),
                ok=False,
                detail="not implemented (optional Telegram Bot API probe)",
            ),
        )
        result.add_custom_error("telegram probe requested but not implemented")


__all__ = ["DoctorRunOptions", "run_doctor_probes"]
