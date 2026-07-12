"""Generic install-action executors (`plan/onboarding-comprehensive-setup` W0.5).

Module: sevn.onboarding.install_actions.executors
Depends: asyncio, pathlib, shlex, sevn.onboarding.capabilities_manifest

Exports:
    idempotent_check_satisfied — skip action when check passes.
    execute_install_action — run one ``InstallAction`` and stream log lines.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sevn.onboarding.capabilities_manifest import InstallAction
from sevn.onboarding.install_actions import special as install_special

run_computer_use_validate = install_special.run_computer_use_validate
run_cua_agent_validate = install_special.run_cua_agent_validate
run_lume_validate = install_special.run_lume_validate
run_openwiki_validate = install_special.run_openwiki_validate

ProgressEvent = dict[str, Any]


def _action_cwd(action: InstallAction, install_root: Path) -> Path:
    """Resolve working directory for an install action.

    Args:
        action (InstallAction): Manifest install step.
        install_root (Path): Default sevn.bot checkout root.

    Returns:
        Path: Directory for subprocess execution.

    Examples:
        >>> from sevn.onboarding.capabilities_manifest import InstallAction
        >>> _action_cwd(
        ...     InstallAction(id="t", kind="noop", argv=[], fatal=False),
        ...     Path("/repo"),
        ... ) == Path("/repo")
        True
    """
    if action.cwd:
        return Path(action.cwd).expanduser()
    return install_root


async def idempotent_check_satisfied(
    check: str,
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> bool:
    """Return True when ``idempotent_check`` indicates the action can be skipped.

    Args:
        check (str): Shell argv string or ``import …`` Python probe.
        cwd (Path): Working directory for the probe.
        env (dict[str, str] | None): Extra environment variables.

    Returns:
        bool: Whether the check succeeded (action should be skipped).

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(idempotent_check_satisfied("false", cwd=Path(".")))
        False
    """
    text = check.strip()
    if not text:
        return False
    run_env = {**os.environ, **(env or {})}
    if text.startswith("import "):
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            text,
            cwd=str(cwd),
            env=run_env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return (await proc.wait()) == 0
    argv = shlex.split(text)
    if not argv:
        return False
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        env=run_env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return (await proc.wait()) == 0


async def execute_install_action(
    action: InstallAction,
    *,
    install_root: Path,
    capability_id: str,
    merged_config: dict[str, Any] | None = None,
    content_root: Path | None = None,
    secrets_context: Any | None = None,
) -> AsyncIterator[ProgressEvent]:
    """Execute one install action and yield W0.5 progress JSON events.

    Args:
        action (InstallAction): Manifest install step.
        install_root (Path): sevn.bot checkout root for ``uv`` / ``make``.
        capability_id (str): Owning capability id for progress metadata.
        merged_config (dict[str, Any] | None): Promoted workspace document.
        content_root (Path | None): Workspace content root for secret probes.
        secrets_context (Any | None): Optional preloaded secrets helper.

    Returns:
        AsyncIterator[ProgressEvent]: ``start``, ``log``, and ``end`` events.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.onboarding.capabilities_manifest import InstallAction
        >>> noop = InstallAction(id="t.noop", kind="noop", argv=[], fatal=False)
        >>> events = asyncio.run(
        ...     _collect_events(
        ...         execute_install_action(
        ...             noop, install_root=Path("."), capability_id="t"
        ...         )
        ...     )
        ... )
        >>> events[-1]["status"]
        'ok'
    """
    yield {
        "type": "start",
        "action_id": action.id,
        "capability_id": capability_id,
    }

    if action.kind == "noop":
        noop_validators = {
            "skill.computer_use.noop": install_special.run_computer_use_validate,
            "skill.cua_agent.noop": install_special.run_cua_agent_validate,
            "skill.lume.noop": install_special.run_lume_validate,
            "skill.openwiki.noop": install_special.run_openwiki_validate,
        }
        validator = noop_validators.get(action.id)
        if validator is not None:
            code, detail = validator(
                merged_config=merged_config,
                content_root=content_root,
            )
            yield {"type": "log", "action_id": action.id, "line": detail}
            status = "ok" if code == 0 else "failed"
            yield {
                "type": "end",
                "action_id": action.id,
                "status": status,
                "exit_code": code,
                "fatal": action.fatal,
            }
            return
        note = action.note or "skipped"
        yield {"type": "log", "action_id": action.id, "line": note}
        yield {
            "type": "end",
            "action_id": action.id,
            "status": "ok",
            "exit_code": 0,
            "fatal": action.fatal,
        }
        return

    cwd = _action_cwd(action, install_root)
    if action.idempotent_check and await idempotent_check_satisfied(
        action.idempotent_check,
        cwd=cwd,
        env=action.env,
    ):
        yield {
            "type": "log",
            "action_id": action.id,
            "line": "idempotent check passed — skipped",
        }
        yield {
            "type": "end",
            "action_id": action.id,
            "status": "skipped",
            "exit_code": 0,
            "fatal": action.fatal,
        }
        return

    if action.kind == "secret_required":
        ok, detail = await _check_secrets_required(
            action.argv,
            content_root=content_root,
            secrets_context=secrets_context,
            merged_config=merged_config,
        )
        yield {"type": "log", "action_id": action.id, "line": detail}
        yield {
            "type": "end",
            "action_id": action.id,
            "status": "ok" if ok else "failed",
            "exit_code": 0 if ok else 1,
            "fatal": action.fatal,
        }
        return

    if action.kind == "uv_extra":
        async for event in _run_subprocess_stream(
            action,
            capability_id=capability_id,
            argv=["uv", "sync", "--extra", *action.argv],
            cwd=cwd,
        ):
            yield event
        return

    if action.kind == "make_target":
        async for event in _run_subprocess_stream(
            action,
            capability_id=capability_id,
            argv=["make", *action.argv],
            cwd=cwd,
        ):
            yield event
        return

    if action.kind == "second_brain_bootstrap":
        from sevn.config.loader import load_workspace
        from sevn.second_brain.layout_probe import fix_second_brain_layout

        root = install_root
        try:
            cfg, _layout = load_workspace(sevn_json=root / "sevn.json")
            created = fix_second_brain_layout(config=cfg, content_root=root)
            line = f"bootstrapped Second Brain layout ({', '.join(created) or 'already complete'})"
            yield {"type": "log", "action_id": action.id, "line": line}
            yield {
                "type": "end",
                "action_id": action.id,
                "status": "ok",
                "exit_code": 0,
                "fatal": action.fatal,
            }
        except Exception as exc:
            yield {"type": "log", "action_id": action.id, "line": str(exc)}
            yield {
                "type": "end",
                "action_id": action.id,
                "status": "failed",
                "exit_code": 1,
                "fatal": action.fatal,
            }
        return

    if action.kind == "subprocess":
        async for event in _run_subprocess_stream(
            action,
            capability_id=capability_id,
            argv=list(action.argv),
            cwd=cwd,
        ):
            yield event
        return

    yield {
        "type": "log",
        "action_id": action.id,
        "line": f"unsupported install kind: {action.kind}",
    }
    yield {
        "type": "end",
        "action_id": action.id,
        "status": "failed",
        "exit_code": 1,
        "fatal": action.fatal,
    }


async def _check_secrets_required(
    logical_keys: list[str],
    *,
    content_root: Path | None,
    secrets_context: Any | None,
    merged_config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Verify required logical secrets exist in the wizard / workspace chain.

    Args:
        logical_keys (list[str]): Secret logical keys from manifest ``argv``.
        content_root (Path | None): Workspace content root.
        secrets_context (Any | None): Unused reserved hook.
        merged_config (dict[str, Any] | None): Workspace document for OpenWiki auto-map.

    Returns:
        tuple[bool, str]: Whether all keys are present and a status line.

    Examples:
        >>> import asyncio
        >>> ok, msg = asyncio.run(
        ...     _check_secrets_required(
        ...         ["missing.key"], content_root=None, secrets_context=None,
        ...     )
        ... )
        >>> ok is False and "workspace content root" in msg
        True
    """
    _ = secrets_context
    if not logical_keys:
        return True, "no secrets required"
    from sevn.skills.openwiki_secrets import (
        OPENWIKI_LLM_API_KEY_SECRET,
        openwiki_credentials_resolved,
    )

    if (
        OPENWIKI_LLM_API_KEY_SECRET in logical_keys
        and merged_config is not None
        and content_root is not None
    ):
        from sevn.config.workspace_config import parse_workspace_config

        cfg = parse_workspace_config(merged_config)
        creds_ok, cred_detail = await openwiki_credentials_resolved(
            cfg,
            content_root=content_root,
        )
        if creds_ok:
            return True, cred_detail
    if content_root is None:
        return False, "workspace content root unavailable for secret check"
    from sevn.onboarding.wizard_credentials import (
        read_wizard_credential_values,
        secrets_section_from_sevn_json,
    )
    from sevn.security.secrets.factory import secrets_chain_from_workspace

    sevn_json = content_root.parent / "sevn.json"
    section = secrets_section_from_sevn_json(sevn_json) if sevn_json.is_file() else None
    wizard_vals = await read_wizard_credential_values(content_root, section=section)
    chain = secrets_chain_from_workspace(content_root, section)
    missing: list[str] = []
    for key in logical_keys:
        if wizard_vals.get(key):
            continue
        val = await chain.get(key)
        if val:
            continue
        if os.environ.get(key, "").strip():
            continue
        missing.append(key)
    if missing:
        return False, f"missing required secret(s): {', '.join(missing)}"
    return True, f"secret(s) present: {', '.join(logical_keys)}"


async def _run_subprocess_stream(
    action: InstallAction,
    *,
    capability_id: str,
    argv: list[str],
    cwd: Path,
) -> AsyncIterator[ProgressEvent]:
    """Run ``argv`` and stream stdout/stderr as log lines.

    Args:
        action (InstallAction): Manifest install step.
        capability_id (str): Owning capability id (progress metadata).
        argv (list[str]): Command argv.
        cwd (Path): Working directory.

    Returns:
        AsyncIterator[ProgressEvent]: Log and end events for the subprocess.

    Examples:
        >>> _run_subprocess_stream.__name__
        '_run_subprocess_stream'
    """
    _ = capability_id
    run_env = {**os.environ, **(action.env or {})}
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            env=run_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        yield {"type": "log", "action_id": action.id, "line": str(exc)}
        yield {
            "type": "end",
            "action_id": action.id,
            "status": "failed",
            "exit_code": 1,
            "fatal": action.fatal,
        }
        return

    stdout = proc.stdout
    if stdout is None:
        yield {"type": "log", "action_id": action.id, "line": "subprocess stdout unavailable"}
        yield {
            "type": "end",
            "action_id": action.id,
            "status": "failed",
            "exit_code": 1,
            "fatal": action.fatal,
        }
        return
    while True:
        line = await stdout.readline()
        if not line:
            break
        text = line.decode(errors="replace").rstrip()
        if text:
            yield {"type": "log", "action_id": action.id, "line": text}
    code = await proc.wait()
    yield {
        "type": "end",
        "action_id": action.id,
        "status": "ok" if code == 0 else "failed",
        "exit_code": code,
        "fatal": action.fatal,
    }


async def _collect_events(gen: AsyncIterator[ProgressEvent]) -> list[ProgressEvent]:
    """Drain an async progress iterator (doctest helper).

    Args:
        gen (AsyncIterator[ProgressEvent]): Event stream.

    Returns:
        list[ProgressEvent]: Collected events.

    Examples:
        >>> _collect_events.__name__
        '_collect_events'
    """
    out: list[ProgressEvent] = []
    async for event in gen:
        out.append(event)
    return out


__all__ = [
    "ProgressEvent",
    "execute_install_action",
    "idempotent_check_satisfied",
]
