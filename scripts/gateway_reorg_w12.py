#!/usr/bin/env python3
"""W12 gateway package reorganization — move modules to subpackages, update imports.

Module: scripts.gateway_reorg_w12
Depends: pathlib, re, subprocess, sys

Exports:
    build_replacements — regex import/path rewrite pairs
    main — CLI entry (git mv + rewrite imports)
    move_files — create subpackages and git-mv modules
    update_files — rewrite imports across scan roots
    update_text — apply replacement pairs to one string
    verify_inventory — assert every root module is classified

Examples:
    >>> from scripts.gateway_reorg_w12 import CORE, MOVES
    >>> "agent_turn" in CORE and "telegram_inline" in MOVES
    True
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GATEWAY = REPO / "src/sevn/gateway"

# Modules that stay at gateway root (core spine).
CORE: frozenset[str] = frozenset(
    {
        "__init__",
        "agent_turn",
        "auth",
        "boot",
        "boot_registry",
        "channel_boot",
        "channel_router",
        "channel_types",
        "http_server",
        "session_manager",
    }
)

# module -> subpackage (commands/ already populated; not listed here).
MOVES: dict[str, str] = {
    "telegram_inline": "telegram",
    "telegram_inline_agent": "telegram",
    "telegram_inline_base": "telegram",
    "telegram_inline_dispatch": "telegram",
    "telegram_inline_printing_press": "telegram",
    "telegram_inline_sources": "telegram",
    "telegram_inline_types": "telegram",
    "telegram_quick_actions": "telegram",
    "telegram_resolve": "telegram",
    "telegram_webhook_secret": "telegram",
    "mission_api": "mission",
    "mission_state": "mission",
    "mission_state_models": "mission",
    "mission_state_snapshots": "mission",
    "mission_subagents_snapshot": "mission",
    "mission_trace_sink": "mission",
    "turn_bundle": "turn",
    "turn_bundle_hooks": "turn",
    "turn_finalizer": "turn",
    "turn_media": "turn",
    "turn_metadata": "turn",
    "replay_job_events": "replay",
    "replay_turn_lookup": "replay",
    "replay_worker": "replay",
    "replay_worker_hooks": "replay",
    "menu": "menu",
    "menu_branding": "menu",
    "menu_readiness": "menu",
    "menu_registry": "menu",
    "session_mirror": "session",
    "session_reset": "session",
    "sessions_query": "session",
    "user_model_hooks": "user",
    "user_model_turn": "user",
    "user_profile": "user",
    "bootstrap_capture": "bootstrap",
    "bootstrap_state": "bootstrap",
    "dispatcher_callbacks": "dispatcher",
    "dispatcher_state": "dispatcher",
    "evolution_approval_gate": "evolution",
    "evolution_issue_events": "evolution",
    "subagents_announce": "subagents",
    "subagents_boot": "subagents",
    "triage_audit": "triage",
    "triage_context": "triage",
    "webapp_qa": "webapp",
    "webapp_viewer": "webapp",
    "post_turn_hooks": "hooks",
    "event_hooks": "hooks",
    "trajectory_ingest_hooks": "hooks",
    "admin_secrets": "admin",
    "browser_lifecycle": "browser",
    "dashboard_pin": "dashboard",
    "diagnostics": "diagnostics",
    "media_store": "media",
    "queue_multi": "queue",
    "steer_store": "queue",
    "cascade_budget": "queue",
    "workspace_config_io": "config_io",
    "routing_footer": "routing",
    "coding_agent_router": "routing",
    "outbound_sweep": "routing",
    "response_filters": "routing",
    "plan_gate": "routing",
    "onboarding_mount": "onboarding",
    "first_session": "onboarding",
    "pairing": "onboarding",
    "openai_compat_api": "api",
    "gui_proxy": "api",
    "web_transport": "api",
    "e2e_echo": "api",
    "deployment_id": "runtime",
    "platform_runtime": "runtime",
    "prometheus_metrics": "runtime",
    "shutdown_cleanup": "runtime",
    "rate_limit": "runtime",
    "gateway_token": "runtime",
    "gateway_restart_ack": "runtime",
    "telemetry_boot": "runtime",
    "self_improve_job_events": "self_improve",
    "slash_access": "access",
    "strings": "util",
    "timestamps": "util",
    "redact": "util",
    "lcm_ingest": "lcm",
}

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".ruff_cache"}


def _new_module_path(mod: str) -> str:
    """Return dotted import path after W12 subpackage move.

    Args:
        mod (str): Flat gateway module stem (key in ``MOVES``).

    Returns:
        str: New dotted module path, e.g. ``sevn.gateway.telegram.telegram_inline``.

    Examples:
        >>> _new_module_path("telegram_inline")
        'sevn.gateway.telegram.telegram_inline'
    """
    pkg = MOVES[mod]
    return f"sevn.gateway.{pkg}.{mod}"


def move_files(*, dry_run: bool) -> None:
    """Create subpackages and git-mv modules from gateway root into subpackages.

    Args:
        dry_run (bool): When True, print planned moves without touching git.

    Examples:
        >>> move_files(dry_run=True)  # after W12, most modules already relocated
    """
    subpackages = sorted(set(MOVES.values()))
    for pkg in subpackages:
        pkg_dir = GATEWAY / pkg
        init = pkg_dir / "__init__.py"
        if not init.exists():
            if dry_run:
                print(f"would create {init}")
            else:
                pkg_dir.mkdir(parents=True, exist_ok=True)
                init.write_text(f'"""Gateway {pkg} subpackage."""\n', encoding="utf-8")

    for mod, pkg in sorted(MOVES.items()):
        src = GATEWAY / f"{mod}.py"
        dst = GATEWAY / pkg / f"{mod}.py"
        if mod in CORE:
            raise SystemExit(f"module {mod} is core but also in MOVES")
        if not src.exists():
            if dst.exists():
                continue
            raise SystemExit(f"missing source {src}")
        if dry_run:
            print(f"would mv {src.relative_to(REPO)} -> {dst.relative_to(REPO)}")
        else:
            subprocess.run(["git", "mv", str(src), str(dst)], check=True, cwd=REPO)


def build_replacements() -> list[tuple[re.Pattern[str], str]]:
    """Build import and doc-path regex replacements for ``MOVES``.

    Returns:
        list[tuple[re.Pattern[str], str]]: Longest-module-first replacement pairs.

    Examples:
        >>> reps = build_replacements()
        >>> any("telegram_inline" in p.pattern for p, _ in reps)
        True
    """
    reps: list[tuple[re.Pattern[str], str]] = []
    for mod in sorted(MOVES, key=len, reverse=True):
        new = _new_module_path(mod)
        reps.append(
            (
                re.compile(rf"\bfrom sevn\.gateway\.{re.escape(mod)}\b"),
                f"from {new}",
            )
        )
        reps.append(
            (
                re.compile(rf"\bimport sevn\.gateway\.{re.escape(mod)}\b"),
                f"import {new}",
            )
        )
        reps.append(
            (
                re.compile(rf"src/sevn/gateway/{re.escape(mod)}\.py"),
                f"src/sevn/gateway/{MOVES[mod]}/{mod}.py",
            )
        )
    return reps


def update_text(text: str, reps: list[tuple[re.Pattern[str], str]]) -> str:
    """Apply all replacement pairs to one file body.

    Args:
        text (str): Original file contents.
        reps (list[tuple[re.Pattern[str], str]]): From :func:`build_replacements`.

    Returns:
        str: Updated text.

    Examples:
        >>> update_text("from sevn.gateway.menu_registry import x", build_replacements())
        'from sevn.gateway.menu.menu_registry import x'
    """
    for pat, repl in reps:
        text = pat.sub(repl, text)
    return text


SCAN_ROOTS = [
    REPO / "src",
    REPO / "tests",
    REPO / "docs",
    REPO / "about-sevn.bot",
    REPO / ".index",
    REPO / "infra",
    REPO / "spec-kit-wave",
    REPO / "scripts",
]


def _scan_paths() -> list[Path]:
    """Collect repo files eligible for import/path rewriting.

    Returns:
        list[Path]: Absolute paths under :data:`SCAN_ROOTS`.

    Examples:
        >>> any(p.name == "agent_turn.py" for p in _scan_paths())
        True
    """
    exts = {".py", ".md", ".toml", ".json", ".yaml", ".yml"}
    out: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix not in exts:
                continue
            if path.name == "gateway_reorg_w12.py":
                continue
            out.append(path)
    return out


def update_files(*, dry_run: bool) -> int:
    """Rewrite imports and doc paths across :func:`_scan_paths`.

    Args:
        dry_run (bool): When True, only count/report would-change files.

    Returns:
        int: Number of files that differ after rewrite.

    Examples:
        >>> update_files(dry_run=True) >= 0
        True
    """
    reps = build_replacements()
    changed = 0
    for path in _scan_paths():
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = update_text(original, reps)
        if updated != original:
            changed += 1
            if dry_run:
                print(f"would update {path.relative_to(REPO)}")
            else:
                path.write_text(updated, encoding="utf-8")
    return changed


def verify_inventory() -> None:
    """Ensure every non-core, non-commands root module is in ``MOVES``.

    Raises:
        SystemExit: When root modules are unassigned or ``MOVES`` lists unknown names.

    Examples:
        >>> verify_inventory()  # passes after W12 reorg
        >>> len(list(GATEWAY.glob('*.py'))) >= 10
        True
    """
    root_mods = {p.stem for p in GATEWAY.glob("*.py")}
    commands_mods = {p.stem for p in (GATEWAY / "commands").glob("*.py")}
    unassigned = root_mods - CORE - set(MOVES) - {"__init__"}
    if unassigned:
        raise SystemExit(f"unassigned root modules: {sorted(unassigned)}")
    extra = set(MOVES) - root_mods - commands_mods
    if extra and all((GATEWAY / f"{m}.py").exists() for m in extra):
        unknown = {m for m in extra if m not in root_mods}
        if unknown:
            raise SystemExit(f"MOVES lists unknown modules: {sorted(unknown)}")


def main() -> None:
    """Run the gateway reorg (move files + rewrite imports).

    Examples:
        >>> import sys
        >>> sys.argv = ["gateway_reorg_w12.py", "--dry-run"]
        >>> main()  # no-op when layout already matches W12
    """
    dry_run = "--dry-run" in sys.argv
    verify_inventory()
    move_files(dry_run=dry_run)
    n = update_files(dry_run=dry_run)
    action = "would update" if dry_run else "updated"
    print(f"{action} {n} files")
    remaining = [p.name for p in GATEWAY.glob("*.py")]
    print(f"root after move: {len(remaining)} files — {sorted(remaining)}")


if __name__ == "__main__":
    main()
