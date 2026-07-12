#!/usr/bin/env python3
"""Bundled ``cua-agent`` skill — goal-driven autonomous loop wrapper.

Module: sevn.data.bundled_skills.core.cua-agent.scripts.run_agent
Depends: argparse, asyncio, subprocess, sevn.config.loader, sevn.lcm.script_cli,
    sevn.skills.cua_agent, sevn.skills.errors

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
from typing import Any

from sevn.config.loader import SevnJsonNotFoundError, load_workspace
from sevn.lcm.script_cli import write_error, write_ok, workspace_from_env
from sevn.skills.computer_use import resolve_cua_cli_command
from sevn.skills.cua_agent import validate_cua_agent_run
from sevn.skills.errors import SKILL_VALIDATION, SkillExecutionError

_DEFAULT_MODEL = "anthropic/claude-sonnet-4-5-20250929"
_TRAJECTORY_URL_RE = re.compile(r"https?://\S+")


async def _run_autonomous_loop(*, goal: str, model: str, max_steps: int) -> dict[str, Any]:
    """Run ``ComputerAgent`` toward ``goal`` and return the final event payload.

    Args:
        goal (str): Operator-approved task description.
        model (str): LiteLLM model string for ``ComputerAgent``.
        max_steps (int): Reserved step budget (upstream agent enforces internally).

    Returns:
        dict[str, Any]: Last agent event dict, or a minimal summary when empty.

    Raises:
        SkillExecutionError: When ``cua-agent`` is not installed.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_run_autonomous_loop)
        True
    """
    _ = max_steps
    try:
        from computer import Computer
        from cua_agent import ComputerAgent
    except ImportError as exc:
        msg = (
            "cua-agent package not installed; run `pip install cua-agent` "
            "(plan/architecture/11-onboarding.md)"
        )
        raise SkillExecutionError(msg, code=SKILL_VALIDATION) from exc

    agent = ComputerAgent(model=model, tools=[Computer()])
    messages: list[dict[str, str]] = [{"role": "user", "content": goal}]
    final: dict[str, Any] | None = None
    async for event in agent.run(messages):
        if isinstance(event, dict):
            final = event
    return final or {"status": "completed", "goal": goal}


def _share_trajectory(cua_cmd: str) -> str | None:
    """Upload the latest session trajectory and return a share URL when available.

    Args:
        cua_cmd (str): Resolved ``cua`` executable on PATH.

    Returns:
        str | None: HTTPS share link from ``cua trajectory share``, or ``None``.

    Examples:
        >>> _share_trajectory("/nonexistent/cua") is None
        True
    """
    try:
        proc = subprocess.run(
            [cua_cmd, "trajectory", "share", "--no-open"],
            capture_output=True,
            text=True,
            check=True,
            timeout=180,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    match = _TRAJECTORY_URL_RE.search(combined)
    return match.group(0).rstrip(").,") if match else None


def main(argv: list[str] | None = None) -> int:
    """Run the cua-agent autonomous loop after HITL approval.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success; ``1`` on validation or runtime failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True, help="Operator-approved task for the agent.")
    parser.add_argument("--model", default=_DEFAULT_MODEL, help="LiteLLM model id.")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=50,
        help="Step budget hint (upstream agent may enforce separately).",
    )
    parser.add_argument(
        "--approved",
        action="store_true",
        help="Required HITL flag — set only after operator confirms this run.",
    )
    args = parser.parse_args(argv)

    workspace = workspace_from_env()
    try:
        cfg, _layout = load_workspace(start_dir=workspace)
    except SevnJsonNotFoundError as exc:
        write_error(code=SKILL_VALIDATION, error=str(exc))
        return 1
    except Exception as exc:
        write_error(code=SKILL_VALIDATION, error=str(exc))
        return 1

    try:
        validate_cua_agent_run(cfg=cfg, approved=args.approved)
    except SkillExecutionError as exc:
        write_error(code=exc.code, error=str(exc))
        return 1

    try:
        result = asyncio.run(
            _run_autonomous_loop(goal=args.goal, model=args.model, max_steps=args.max_steps),
        )
    except SkillExecutionError as exc:
        write_error(code=exc.code, error=str(exc))
        return 1
    except Exception as exc:
        write_error(code=SKILL_VALIDATION, error=str(exc))
        return 1

    trajectory_url = _share_trajectory(resolve_cua_cli_command(cfg))
    write_ok(
        {
            "goal": args.goal,
            "model": args.model,
            "result": result,
            "trajectory_url": trajectory_url,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
