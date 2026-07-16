"""Background process management tool (`plan/tools-skills-full-inventory-wave-plan.md` Wave 8).

Tracks asyncio subprocess jobs per gateway session with start/stop/list/output actions.

Module: sevn.tools.process
Depends: asyncio, shlex, uuid, sevn.tools.base, sevn.tools.context, sevn.tools.decorator,
    sevn.tools.paths

Exports:
    BackgroundJob — tracked subprocess record for one session job.
    process_tool — multi-action background job control.
    register_process_tools — register ``process`` on a ``ToolExecutor``.
    reset_process_store_for_tests — clear in-memory job tables (tests only).
    list_session_jobs — testable job listing helper.

Examples:
    >>> from sevn.tools.process import reset_process_store_for_tests
    >>> reset_process_store_for_tests()
    >>> True
    True
"""

from __future__ import annotations

import asyncio
import contextlib
import shlex
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from sevn.runtime.operator_path import augment_operator_path
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated
from sevn.tools.paths import resolve_workspace_relative_path

if TYPE_CHECKING:
    from sevn.tools.base import ToolExecutor

ProcessAction = Literal["start", "stop", "list", "output"]
ProcessActionInput = Literal["start", "stop", "list", "output", "read"]
JobStatus = Literal["running", "completed", "stopped", "failed"]

DEFAULT_OUTPUT_TAIL_LINES: Final[int] = 200
MAX_OUTPUT_TAIL_LINES: Final[int] = 2000
MAX_CAPTURE_CHARS: Final[int] = 256_000

# Model-facing aliases mapped before dispatch (D8). ``run`` stays unknown so
# ``did_you_mean`` can offer start|output — it is ambiguous between them.
_ACTION_ALIASES: Final[dict[str, ProcessAction]] = {"read": "output"}

_PROCESS_TOOLS: tuple[Any, ...] = ()
_jobs_by_session: dict[str, dict[str, BackgroundJob]] = {}


@dataclass
class BackgroundJob:
    """One session-scoped background subprocess."""

    job_id: str
    command: list[str]
    cwd: Path
    proc: asyncio.subprocess.Process | None = None
    stdout_parts: list[str] = field(default_factory=list)
    stderr_parts: list[str] = field(default_factory=list)
    status: JobStatus = "running"
    returncode: int | None = None
    reader_tasks: list[asyncio.Task[None]] = field(default_factory=list, repr=False)


def reset_process_store_for_tests() -> None:
    """Drop all tracked background jobs (unit tests only).

    Returns:
        None

    Examples:
        >>> reset_process_store_for_tests()
        >>> True
        True
    """
    for jobs in _jobs_by_session.values():
        for job in jobs.values():
            _cancel_job_readers(job)
            if job.proc is not None and job.proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    job.proc.kill()
    _jobs_by_session.clear()


def _session_jobs(session_id: str) -> dict[str, BackgroundJob]:
    """Return the mutable job map for ``session_id``.

    Args:
        session_id (str): Gateway session identifier.

    Returns:
        dict[str, BackgroundJob]: Job id to record mapping.

    Examples:
        >>> reset_process_store_for_tests()
        >>> jobs = _session_jobs("demo")
        >>> isinstance(jobs, dict)
        True
    """
    return _jobs_by_session.setdefault(session_id, {})


def _cancel_job_readers(job: BackgroundJob) -> None:
    """Cancel stdout/stderr reader tasks for ``job``.

    Args:
        job (BackgroundJob): Job whose readers should stop.

    Returns:
        None

    Examples:
        >>> job = BackgroundJob(job_id="j", command=["echo"], cwd=Path("."))
        >>> _cancel_job_readers(job) is None
        True
    """
    for task in job.reader_tasks:
        task.cancel()
    job.reader_tasks.clear()


async def _read_stream(
    stream: asyncio.StreamReader | None,
    parts: list[str],
    *,
    label: str,
) -> None:
    """Append decoded chunks from ``stream`` into ``parts`` with a size cap.

    Args:
        stream (asyncio.StreamReader | None): Pipe to drain.
        parts (list[str]): Mutable capture buffer.
        label (str): ``stdout`` or ``stderr`` (logging only).

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_read_stream)
        True
    """
    _ = label
    if stream is None:
        return
    total = sum(len(part) for part in parts)
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        text = chunk.decode("utf-8", errors="replace")
        parts.append(text)
        total += len(text)
        if total >= MAX_CAPTURE_CHARS:
            overflow = total - MAX_CAPTURE_CHARS
            parts[-1] = parts[-1][overflow:]
            break


def _finalize_job_status(job: BackgroundJob) -> None:
    """Set ``job.status`` from ``job.proc.returncode`` when the process exited.

    Args:
        job (BackgroundJob): Job to update in place.

    Returns:
        None

    Examples:
        >>> job = BackgroundJob(job_id="j", command=["echo"], cwd=Path("."), status="running")
        >>> _finalize_job_status(job)
        >>> job.status
        'running'
    """
    proc = job.proc
    if proc is None:
        return
    if proc.returncode is None:
        return
    job.returncode = proc.returncode
    if job.status == "stopped":
        return
    job.status = "completed" if proc.returncode == 0 else "failed"


async def _watch_job_exit(job: BackgroundJob) -> None:
    """Wait for ``job.proc`` to exit and refresh ``job.status``.

    Args:
        job (BackgroundJob): Running job to monitor.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_watch_job_exit)
        True
    """
    proc = job.proc
    if proc is None:
        return
    try:
        await proc.wait()
    except asyncio.CancelledError:
        raise
    finally:
        _finalize_job_status(job)
        _cancel_job_readers(job)


def _parse_command(command: str | list[str]) -> list[str]:
    """Normalize a shell string or argv list into an argv vector.

    Args:
        command (str | list[str]): Shell command or argv.

    Returns:
        list[str]: Non-empty argv.

    Raises:
        ValueError: When ``command`` is empty after parsing.

    Examples:
        >>> _parse_command("echo hi")
        ['echo', 'hi']
        >>> _parse_command(["echo", "hi"])
        ['echo', 'hi']
    """
    if isinstance(command, list):
        argv = [str(part) for part in command if str(part).strip()]
    else:
        argv = shlex.split(command.strip())
    if not argv:
        msg = "command must be non-empty"
        raise ValueError(msg)
    return argv


def list_session_jobs(session_id: str) -> list[dict[str, object]]:
    """Return serializable summaries for all jobs in ``session_id``.

    Args:
        session_id (str): Gateway session identifier.

    Returns:
        list[dict[str, object]]: Job metadata rows.

    Examples:
        >>> reset_process_store_for_tests()
        >>> list_session_jobs("missing")
        []
    """
    rows: list[dict[str, object]] = []
    for job in _session_jobs(session_id).values():
        _finalize_job_status(job)
        rows.append(
            {
                "job_id": job.job_id,
                "command": list(job.command),
                "cwd": str(job.cwd),
                "status": job.status,
                "returncode": job.returncode,
            },
        )
    return rows


def _tail_text(parts: list[str], *, max_lines: int) -> str:
    """Join capture parts and return the last ``max_lines`` lines.

    Args:
        parts (list[str]): Captured stream chunks.
        max_lines (int): Maximum lines to keep from the tail.

    Returns:
        str: Tail text (may be empty).

    Examples:
        >>> _tail_text(["a\\nb\\n", "c\\n"], max_lines=2)
        'b\\nc\\n'
    """
    text = "".join(parts)
    if not text:
        return ""
    lines = text.splitlines(keepends=True)
    if len(lines) <= max_lines:
        return text
    return "".join(lines[-max_lines:])


async def _start_job(
    ctx: ToolContext,
    *,
    command: str | list[str],
    cwd: str | None,
) -> str:
    """Spawn a background subprocess under ``ctx.workspace_path``.

    Args:
        ctx (ToolContext): Active tool runtime frame.
        command (str | list[str]): Shell command or argv list.
        cwd (str | None): Optional workspace-relative working directory.

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_start_job)
        True
    """
    try:
        argv = _parse_command(command)
    except ValueError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)

    work_cwd = ctx.workspace_path
    if cwd:
        try:
            work_cwd = resolve_workspace_relative_path(ctx.workspace_path, cwd)
        except ValueError as exc:
            return enveloped_failure(str(exc), code=ToolResultCode.PERMISSION_DENIED)

    job_id = uuid.uuid4().hex[:12]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=work_cwd,
            env=augment_operator_path(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return enveloped_failure(
            f"process start failed: {exc}",
            code=ToolResultCode.INTERNAL_ERROR,
            data={"command": argv},
        )

    job = BackgroundJob(job_id=job_id, command=argv, cwd=work_cwd, proc=proc)
    if proc.stdout is not None:
        job.reader_tasks.append(
            asyncio.create_task(_read_stream(proc.stdout, job.stdout_parts, label="stdout"))
        )
    if proc.stderr is not None:
        job.reader_tasks.append(
            asyncio.create_task(_read_stream(proc.stderr, job.stderr_parts, label="stderr"))
        )
    job.reader_tasks.append(asyncio.create_task(_watch_job_exit(job)))
    _session_jobs(ctx.session_id)[job_id] = job
    return enveloped_success(
        {
            "job_id": job_id,
            "command": argv,
            "cwd": str(work_cwd),
            "status": job.status,
        },
    )


async def _stop_job(ctx: ToolContext, *, job_id: str) -> str:
    """Terminate a tracked background job.

    Args:
        ctx (ToolContext): Active tool runtime frame.
        job_id (str): Job identifier from ``start``.

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_stop_job)
        True
    """
    job = _session_jobs(ctx.session_id).get(job_id)
    if job is None:
        return enveloped_failure(
            f"unknown job_id: {job_id}",
            code=ToolResultCode.VALIDATION_ERROR,
            data={"job_id": job_id},
        )
    proc = job.proc
    if proc is None or proc.returncode is not None:
        _finalize_job_status(job)
        return enveloped_success(
            {"job_id": job_id, "status": job.status, "returncode": job.returncode}
        )

    job.status = "stopped"
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except TimeoutError:
        proc.kill()
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()
    job.returncode = proc.returncode
    for task in list(job.reader_tasks):
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=2.0)
    job.reader_tasks.clear()
    return enveloped_success({"job_id": job_id, "status": job.status, "returncode": job.returncode})


async def _output_job(ctx: ToolContext, *, job_id: str, lines: int | None) -> str:
    """Return captured stdout/stderr for ``job_id``.

    Args:
        ctx (ToolContext): Active tool runtime frame.
        job_id (str): Job identifier from ``start``.
        lines (int | None): Optional tail line cap.

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_output_job)
        True
    """
    job = _session_jobs(ctx.session_id).get(job_id)
    if job is None:
        return enveloped_failure(
            f"unknown job_id: {job_id}",
            code=ToolResultCode.VALIDATION_ERROR,
            data={"job_id": job_id},
        )
    tail = DEFAULT_OUTPUT_TAIL_LINES if lines is None else min(max(1, lines), MAX_OUTPUT_TAIL_LINES)
    _finalize_job_status(job)
    return enveloped_success(
        {
            "job_id": job_id,
            "status": job.status,
            "returncode": job.returncode,
            "stdout": _tail_text(job.stdout_parts, max_lines=tail),
            "stderr": _tail_text(job.stderr_parts, max_lines=tail),
        },
    )


def _job_status_for_error(ctx: ToolContext, job_id: str | None) -> dict[str, object]:
    """Build wrong-action error extras including the referenced job's status.

    Args:
        ctx (ToolContext): Active tool runtime frame.
        job_id (str | None): Job id from the failed call, when present.

    Returns:
        dict[str, object]: Payload fragment with ``job_id`` / ``job_status`` when known.

    Examples:
        >>> reset_process_store_for_tests()
        >>> from pathlib import Path
        >>> ctx = ToolContext(
        ...     session_id="s", workspace_path=Path("."), workspace_id="w", registry_version=1
        ... )
        >>> _job_status_for_error(ctx, None)
        {}
    """
    if not job_id:
        return {}
    job = _session_jobs(ctx.session_id).get(job_id)
    if job is None:
        return {"job_id": job_id, "job_status": None}
    _finalize_job_status(job)
    return {"job_id": job_id, "job_status": job.status}


def _unknown_action_failure(
    ctx: ToolContext,
    *,
    action: str,
    job_id: str | None,
) -> str:
    """Return a self-correcting failure for an invalid ``process`` action.

    Includes the referenced ``job_id``'s current status when known (D8) so one
    follow-up call can choose ``output`` / ``stop`` without a separate ``list``.

    Args:
        ctx (ToolContext): Active tool runtime frame.
        action (str): The invalid action string as supplied by the model.
        job_id (str | None): Optional job id from the same call.

    Returns:
        str: §3.1 JSON failure envelope.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_unknown_action_failure)
        True
    """
    extras = _job_status_for_error(ctx, job_id)
    status = extras.get("job_status")
    status_clause = ""
    if job_id and status is not None:
        status_clause = f" Referenced job {job_id!r} status is {status}."
    elif job_id:
        status_clause = f" Referenced job_id {job_id!r} is unknown."
    return enveloped_failure(
        f"unknown action {action!r}; expected one of start|stop|list|output "
        f"(read is an alias for output).{status_clause} "
        "process runs background jobs only — there is no synchronous run: use "
        "action=start then action=output (or action=read), or terminal_run "
        "for an interactive shell.",
        code=ToolResultCode.VALIDATION_ERROR,
        data={"action": action, **extras},
    )


@sevn_tool(
    name="process",
    category="process",
    description=(
        "Start, stop, list, or read output from background workspace subprocesses. "
        "action=read is an alias for action=output; there is no synchronous run."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "list", "output", "read"],
                "description": (
                    "Operation on the session job table. "
                    "``read`` is an alias for ``output`` (fetch captured stdout/stderr)."
                ),
            },
            "command": {
                "type": "string",
                "description": "Shell command or argv string for action=start.",
            },
            "argv": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional argv list for action=start (overrides command).",
            },
            "cwd": {
                "type": "string",
                "description": "Workspace-relative working directory for action=start.",
            },
            "job_id": {
                "type": "string",
                "description": "Background job id for action=stop or action=output/read.",
            },
            "lines": {
                "type": "integer",
                "description": "Tail line cap for action=output/read (default 200).",
            },
        },
        "required": ["action"],
    },
    abortable=True,
    sandbox_mode="subprocess",
)
async def process_tool(
    ctx: ToolContext,
    *,
    action: ProcessActionInput,
    command: str | None = None,
    argv: list[str] | None = None,
    cwd: str | None = None,
    job_id: str | None = None,
    lines: int | None = None,
) -> str:
    """Dispatch background job control for the active session.

    Args:
        ctx (ToolContext): Active tool runtime frame.
        action (str): ``start``, ``stop``, ``list``, ``output``, or alias ``read``.
        command (str | None): Shell command when ``action=start``.
        argv (list[str] | None): Optional argv override when ``action=start``.
        cwd (str | None): Workspace-relative cwd when ``action=start``.
        job_id (str | None): Target job for ``stop`` / ``output`` / ``read``.
        lines (int | None): Tail cap for ``output`` / ``read``.

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(process_tool)
        True
    """
    canonical = _ACTION_ALIASES.get(action, action)

    if canonical == "start":
        cmd: str | list[str]
        if argv:
            cmd = argv
        elif command:
            cmd = command
        else:
            return enveloped_failure(
                "command or argv is required for action=start",
                code=ToolResultCode.VALIDATION_ERROR,
            )
        return await _start_job(ctx, command=cmd, cwd=cwd)

    if canonical == "list":
        return enveloped_success({"jobs": list_session_jobs(ctx.session_id)})

    if canonical == "stop":
        if not job_id:
            return enveloped_failure(
                "job_id is required for action=stop and action=output",
                code=ToolResultCode.VALIDATION_ERROR,
            )
        return await _stop_job(ctx, job_id=job_id)

    if canonical == "output":
        if not job_id:
            return enveloped_failure(
                "job_id is required for action=stop and action=output",
                code=ToolResultCode.VALIDATION_ERROR,
            )
        return await _output_job(ctx, job_id=job_id, lines=lines)

    return _unknown_action_failure(ctx, action=action, job_id=job_id)


_PROCESS_TOOLS = (process_tool,)


def register_process_tools(executor: ToolExecutor) -> None:
    """Register Wave 8 background ``process`` tool.

    Args:
        executor (ToolExecutor): Registry under construction.

    Returns:
        None

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.process import register_process_tools
        >>> exe = ToolExecutor()
        >>> register_process_tools(exe)
        >>> "process" in {d.name for d in exe.definitions()}
        True
    """
    for tool_fn in _PROCESS_TOOLS:
        executor.register(tool_from_decorated(tool_fn))


__all__ = [
    "ProcessAction",
    "ProcessActionInput",
    "list_session_jobs",
    "process_tool",
    "register_process_tools",
    "reset_process_store_for_tests",
]
