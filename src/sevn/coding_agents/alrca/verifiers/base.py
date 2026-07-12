"""ALRCA verifier protocol and built-in kinds (CA3.4).

Module: sevn.coding_agents.alrca.verifiers.base
Depends: asyncio, dataclasses, enum, pathlib

Exports:
    BuiltinVerifierKind — known verifier spec prefixes.
    VerifierResult — pass/fail result envelope.
    build_verifier — construct a verifier callable from a spec string.
    run_verifier_spec — resolve and run a verifier spec in one call.

Spec string format:
    ``make:<target>`` — run ``make <target>`` in workspace_path (exit 0 = pass).
    ``script:<cmd>`` — run arbitrary shell command (exit 0 = pass).
    ``llm_judge:<label>`` — fuzzy LLM evaluator stub (always passes without model cfg).
    Any other string is treated as a bare shell command.

Examples:
    >>> import asyncio, pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as t:
    ...     import asyncio
    ...     from sevn.coding_agents.alrca.verifiers.base import run_verifier_spec
    ...     r = asyncio.run(run_verifier_spec("script:true", pathlib.Path(t)))
    ...     r.passed
    True
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


class BuiltinVerifierKind(StrEnum):
    """Known built-in verifier spec prefixes."""

    make = "make:"
    script = "script:"
    llm_judge = "llm_judge:"


@dataclass
class VerifierResult:
    """Outcome of one verifier run.

    Args:
        passed (bool): Whether the verifier succeeded.
        spec (str): Verifier spec string that produced this result.
        output (str): Captured stdout/stderr (truncated to 4096 chars).
        exit_code (int | None): Process exit code when applicable.

    Examples:
        >>> VerifierResult(passed=True, spec="make:lint").passed
        True
    """

    passed: bool
    spec: str
    output: str = ""
    exit_code: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_DEFAULT_TIMEOUT = 300.0


async def _run_command(
    cmd: str,
    spec: str,
    workspace_path: Path,
) -> VerifierResult:
    """Run a shell command and return a VerifierResult.

    Args:
        cmd (str): Shell command string to execute.
        spec (str): Original verifier spec string for attribution.
        workspace_path (Path): Working directory for the subprocess.

    Returns:
        VerifierResult: Pass when exit code is 0, fail otherwise.

    Examples:
        >>> import asyncio, pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as t:
        ...     r = asyncio.run(_run_command("true", "script:true", pathlib.Path(t)))
        ...     r.passed
        True
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(workspace_path),
        )
        try:
            async with asyncio.timeout(_DEFAULT_TIMEOUT):
                raw_stdout, _ = await proc.communicate()
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return VerifierResult(
                passed=False,
                spec=spec,
                output=f"[timeout after {_DEFAULT_TIMEOUT}s]",
                exit_code=-1,
            )
        output = (raw_stdout or b"").decode(errors="replace")[-4096:]
        return VerifierResult(
            passed=proc.returncode == 0,
            spec=spec,
            output=output,
            exit_code=proc.returncode,
        )
    except OSError as exc:
        return VerifierResult(passed=False, spec=spec, output=str(exc), exit_code=-1)


def build_verifier(spec: str) -> Any:
    """Construct a verifier async callable from a spec string.

    Args:
        spec (str): One of ``make:<target>``, ``script:<cmd>``, ``llm_judge:<label>``,
            or a bare shell command treated as ``script:``.

    Returns:
        Any: Async callable ``(workspace_path: Path) -> VerifierResult``.

    Examples:
        >>> import asyncio, pathlib, tempfile
        >>> v = build_verifier("script:true")
        >>> with tempfile.TemporaryDirectory() as t:
        ...     r = asyncio.run(v(pathlib.Path(t)))
        ...     r.passed
        True
    """
    stripped = spec.strip()

    if stripped.startswith("make:"):
        target = stripped[5:].strip()

        async def _make(workspace_path: Path) -> VerifierResult:
            return await _run_command(f"make {shlex.quote(target)}", stripped, workspace_path)

        return _make

    if stripped.startswith("script:"):
        cmd = stripped[7:].strip()

        async def _script(workspace_path: Path) -> VerifierResult:
            return await _run_command(cmd, stripped, workspace_path)

        return _script

    if stripped.startswith("llm_judge:"):
        label = stripped[10:].strip()

        async def _llm(workspace_path: Path) -> VerifierResult:
            _ = workspace_path
            return VerifierResult(
                passed=True,
                spec=stripped,
                output=f"[llm_judge:{label}] stub — no evaluator model configured",
            )

        return _llm

    # Bare command — treat as script.
    async def _bare(workspace_path: Path) -> VerifierResult:
        return await _run_command(stripped, stripped, workspace_path)

    return _bare


async def run_verifier_spec(spec: str, workspace_path: Path) -> VerifierResult:
    """Resolve and run a verifier spec in one call.

    Args:
        spec (str): Verifier spec string (e.g. ``script:true``, ``make:lint``).
        workspace_path (Path): Working directory for the verifier subprocess.

    Returns:
        VerifierResult: Pass/fail outcome from the constructed verifier.

    Examples:
        >>> import asyncio, pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as t:
        ...     r = asyncio.run(run_verifier_spec("script:true", pathlib.Path(t)))
        ...     r.passed
        True
    """
    verifier = build_verifier(spec)
    result: VerifierResult = await verifier(workspace_path)
    return result


__all__ = [
    "BuiltinVerifierKind",
    "VerifierResult",
    "build_verifier",
    "run_verifier_spec",
]
