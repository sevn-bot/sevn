"""Ripgrep-backed ``search_in_file`` tool (`specs/11-tools-registry.md` §4.3).

Module: sevn.tools.file_ops.search
Depends: sevn.tools.base, sevn.tools.context, sevn.tools.decorator, sevn.tools.paths

Exports:
    search_in_file_tool — ``@sevn_tool`` callable registered by :func:`register_file_ops_tools`.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import re
import shutil
from pathlib import Path
from typing import Final

from loguru import logger

from sevn.security.llmignore import is_llmignored
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool
from sevn.tools.file_ops.graphify_result_prefix import graphify_prefix_for_search_path
from sevn.tools.paths import (
    WorkspacePathError,
    display_path_for_tool,
    resolve_tool_path,
)

MAX_SEARCH_MATCHES: Final[int] = 500
_LLMIGNORE_GLOB: Final[str] = "!**/.llmignore/**"
_python_fallback_logged: bool = False


def _rel_posix(workspace: Path, candidate: Path) -> str:
    """Return ``candidate`` as a workspace-relative POSIX path string.

    Args:
        workspace (Path): Workspace content root.
        candidate (Path): Resolved absolute path.

    Returns:
        str: Relative POSIX path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> f = ws / "a.txt"
        >>> _ = f.write_text("x", encoding="utf-8")
        >>> _rel_posix(ws, f.resolve())
        'a.txt'
    """
    return candidate.relative_to(workspace.expanduser().resolve()).as_posix()


def _path_error_envelope(exc: BaseException) -> str:
    """Map guard failures to §3.1 envelopes.

    Args:
        exc (BaseException): Raised guard or validation error.

    Returns:
        str: JSON failure envelope string.

    Examples:
        >>> "VALIDATION_ERROR" in _path_error_envelope(WorkspacePathError("bad"))
        True
    """
    if isinstance(exc, PermissionError):
        return enveloped_failure(str(exc), code=ToolResultCode.PERMISSION_DENIED)
    if isinstance(exc, WorkspacePathError):
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    return enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)


def _find_rg_binary() -> str | None:
    """Locate the ``rg`` executable on ``PATH``.

    Returns:
        str | None: Absolute path to ``rg`` when found.

    Examples:
        >>> out = _find_rg_binary()
        >>> out is None or out.endswith("rg")
        True
    """
    return shutil.which("rg")


def _log_python_fallback_once() -> None:
    """Emit the ripgrep-missing warning at most once per process.

    Returns:
        None

    Examples:
        >>> _log_python_fallback_once()
        >>> True
        True
    """
    global _python_fallback_logged
    if not _python_fallback_logged:
        logger.warning("search_in_file_no_ripgrep_using_python_fallback")
        _python_fallback_logged = True


def _iter_search_files(
    workspace: Path,
    search_path: Path,
    *,
    include_glob: str | None,
) -> list[Path]:
    """Collect readable files under ``search_path`` honouring include globs.

    Args:
        workspace (Path): Workspace content root.
        search_path (Path): Resolved file or directory to search.
        include_glob (str | None): Optional glob filter relative to ``search_path``.

    Returns:
        list[Path]: Sorted candidate file paths.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> f = ws / "a.txt"
        >>> _ = f.write_text("x", encoding="utf-8")
        >>> files = _iter_search_files(ws, f, include_glob=None)
        >>> files[0].name
        'a.txt'
    """
    if search_path.is_file():
        return [search_path.resolve()]

    pattern = include_glob.strip() if include_glob else "**/*"
    candidates: list[Path] = []
    for path in sorted(search_path.rglob("*")):
        if not path.is_file():
            continue
        if is_llmignored(path, workspace):
            continue
        rel = path.relative_to(search_path)
        if not fnmatch.fnmatch(rel.as_posix(), pattern):
            continue
        candidates.append(path.resolve())
    return candidates


def _run_python_search_sync(
    *,
    workspace: Path,
    pattern: str,
    search_path: Path,
    include_glob: str | None,
    max_matches: int = MAX_SEARCH_MATCHES,
) -> tuple[list[dict[str, object]], bool, str | None]:
    """Walk files with ``re.finditer`` when ripgrep is unavailable.

    Args:
        workspace (Path): Workspace content root.
        pattern (str): Regex pattern.
        search_path (Path): Resolved file or directory path to search.
        include_glob (str | None): Optional glob filter relative to ``search_path``.
        max_matches (int): Maximum match rows to collect.

    Returns:
        tuple[list[dict[str, object]], bool, str | None]: Matches, truncation flag,
            and optional error message when the regex is invalid.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> f = ws / "a.txt"
        >>> _ = f.write_text("needle here\\n", encoding="utf-8")
        >>> matches, truncated, err = _run_python_search_sync(
        ...     workspace=ws,
        ...     pattern="needle",
        ...     search_path=f,
        ...     include_glob=None,
        ... )
        >>> err is None and matches[0]["text"] == "needle here"
        True
    """
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return [], False, f"invalid regex: {exc}"

    matches: list[dict[str, object]] = []
    truncated = False
    for file_path in _iter_search_files(workspace, search_path, include_glob=include_glob):
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not compiled.search(line):
                continue
            matches.append(
                {
                    "path": display_path_for_tool(workspace, file_path),
                    "line": line_no,
                    "text": line.rstrip("\n"),
                },
            )
            if len(matches) >= max_matches:
                truncated = True
                return matches, truncated, None
    return matches, truncated, None


async def _run_python_search(
    *,
    workspace: Path,
    pattern: str,
    search_path: Path,
    include_glob: str | None,
    max_matches: int = MAX_SEARCH_MATCHES,
) -> tuple[list[dict[str, object]], bool, str | None]:
    """Async wrapper around :func:`_run_python_search_sync`.

    Args:
        workspace (Path): Workspace content root.
        pattern (str): Regex pattern.
        search_path (Path): Resolved file or directory path to search.
        include_glob (str | None): Optional glob filter relative to ``search_path``.
        max_matches (int): Maximum match rows to collect.

    Returns:
        tuple[list[dict[str, object]], bool, str | None]: Matches, truncation flag,
            and optional error message when the regex is invalid.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_run_python_search)
        True
    """
    return await asyncio.to_thread(
        _run_python_search_sync,
        workspace=workspace,
        pattern=pattern,
        search_path=search_path,
        include_glob=include_glob,
        max_matches=max_matches,
    )


def _build_rg_argv(
    *,
    rg_binary: str,
    pattern: str,
    search_path: Path,
    include_glob: str | None,
) -> list[str]:
    """Build a ripgrep argv list for workspace search.

    Args:
        rg_binary (str): Resolved ``rg`` executable path.
        pattern (str): Ripgrep search pattern (regex).
        search_path (Path): Resolved file or directory to search.
        include_glob (str | None): Optional glob filter forwarded to ``--glob``.

    Returns:
        list[str]: Argument vector for :func:`asyncio.create_subprocess_exec`.

    Examples:
        >>> from pathlib import Path
        >>> argv = _build_rg_argv(
        ...     rg_binary="/usr/bin/rg",
        ...     pattern="foo",
        ...     search_path=Path("/tmp/ws"),
        ...     include_glob="**/*.py",
        ... )
        >>> argv[0]
        '/usr/bin/rg'
        >>> "--glob" in argv
        True
    """
    argv: list[str] = [
        rg_binary,
        "--json",
        "--line-number",
        "--no-heading",
        "--glob",
        _LLMIGNORE_GLOB,
    ]
    if include_glob:
        argv.extend(["--glob", include_glob.strip()])
    argv.extend([pattern, str(search_path)])
    return argv


def _parse_rg_match_line(
    line: str,
    *,
    workspace: Path,
    matches: list[dict[str, object]],
    max_matches: int,
) -> bool:
    """Parse one ``rg --json`` stdout line into ``matches`` when it is a hit.

    Args:
        line (str): One stdout line from ripgrep JSON mode.
        workspace (Path): Workspace content root for relative paths.
        matches (list[dict[str, object]]): Accumulator for parsed match rows.
        max_matches (int): Stop parsing when ``matches`` reaches this length.

    Returns:
        bool: ``True`` when the match cap was reached during this parse.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> f = ws / "x.txt"
        >>> _ = f.write_text("needle", encoding="utf-8")
        >>> payload = (
        ...     '{"type":"match","data":{"path":{"text":"'
        ...     + str(f)
        ...     + '"},"lines":{"text":"needle here"},"line_number":1}}'
        ... )
        >>> rows: list[dict[str, object]] = []
        >>> _parse_rg_match_line(payload, workspace=ws, matches=rows, max_matches=10)
        False
        >>> rows[0]["line"]
        1
    """
    if len(matches) >= max_matches:
        return True
    try:
        blob = json.loads(line)
    except json.JSONDecodeError:
        return False
    if not isinstance(blob, dict) or blob.get("type") != "match":
        return False
    data = blob.get("data")
    if not isinstance(data, dict):
        return False
    path_blob = data.get("path")
    if not isinstance(path_blob, dict):
        return False
    path_text = path_blob.get("text")
    if not isinstance(path_text, str):
        return False
    candidate = Path(path_text).expanduser().resolve()
    if is_llmignored(candidate, workspace):
        return False
    line_number = data.get("line_number")
    lines_blob = data.get("lines")
    text = ""
    if isinstance(lines_blob, dict):
        raw_text = lines_blob.get("text")
        if isinstance(raw_text, str):
            text = raw_text.rstrip("\n")
    matches.append(
        {
            "path": display_path_for_tool(workspace, candidate),
            "line": line_number if isinstance(line_number, int) else 0,
            "text": text,
        },
    )
    return len(matches) >= max_matches


def _format_match_lines(matches: list[dict[str, object]]) -> str:
    """Render matches as ``path:line:text`` rows for agent-facing output.

    Args:
        matches (list[dict[str, object]]): Parsed match dicts from ripgrep.

    Returns:
        str: Newline-separated match lines.

    Examples:
        >>> _format_match_lines([{"path": "a.py", "line": 2, "text": "x"}])
        'a.py:2:x'
    """
    rows: list[str] = []
    for row in matches:
        rel = row.get("path", "")
        line_no = row.get("line", 0)
        text = row.get("text", "")
        rows.append(f"{rel}:{line_no}:{text}")
    return "\n".join(rows)


async def _run_ripgrep(
    *,
    workspace: Path,
    pattern: str,
    search_path: Path,
    include_glob: str | None,
    max_matches: int = MAX_SEARCH_MATCHES,
) -> tuple[list[dict[str, object]], bool, str | None]:
    """Execute ripgrep and return parsed matches.

    Args:
        workspace (Path): Workspace content root.
        pattern (str): Ripgrep regex pattern.
        search_path (Path): Resolved file or directory path to search.
        include_glob (str | None): Optional ``--glob`` filter.
        max_matches (int): Maximum match rows to collect.

    Returns:
        tuple[list[dict[str, object]], bool, str | None]: Matches, truncation flag,
            and optional error message when ripgrep fails.

    Examples:
        >>> import asyncio
        >>> import tempfile
        >>> from pathlib import Path
        >>> async def _demo() -> tuple[int, bool]:
        ...     ws = Path(tempfile.mkdtemp())
        ...     target = ws / "missing-for-rg-demo"
        ...     matches, truncated, err = await _run_ripgrep(
        ...         workspace=ws,
        ...         pattern="x",
        ...         search_path=target,
        ...         include_glob=None,
        ...         max_matches=5,
        ...     )
        ...     return len(matches), truncated
        ...
        >>> asyncio.run(_demo())  # doctest: +SKIP
        (0, False)
    """
    rg_binary = _find_rg_binary()
    if rg_binary is None:
        return [], False, "ripgrep (rg) not found on PATH"

    argv = _build_rg_argv(
        rg_binary=rg_binary,
        pattern=pattern,
        search_path=search_path,
        include_glob=include_glob,
    )
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

    if proc.returncode not in (0, 1):
        detail = stderr_text or f"ripgrep exited with code {proc.returncode}"
        return [], False, detail

    matches: list[dict[str, object]] = []
    truncated = False
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    for line in stdout_text.splitlines():
        if not line.strip():
            continue
        if _parse_rg_match_line(
            line,
            workspace=workspace,
            matches=matches,
            max_matches=max_matches,
        ):
            truncated = True
            break

    return matches, truncated, None


@sevn_tool(
    name="search_in_file",
    category="file_ops",
    description="Regex search file contents under a workspace path via ripgrep.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Ripgrep regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "File or directory (workspace-relative, default '.').",
            },
            "include": {
                "type": "string",
                "description": "Optional glob filter (e.g. '**/*.py').",
            },
        },
        "required": ["pattern"],
    },
    large_result=True,
)
async def search_in_file_tool(
    ctx: ToolContext,
    pattern: str,
    path: str = ".",
    include: str | None = None,
) -> str:
    """Search workspace files with ripgrep and return capped ``path:line:text`` hits.

    Args:
        ctx (ToolContext): Invocation context (``workspace_path`` is content root).
        pattern (str): Ripgrep regex pattern.
        path (str): Workspace-relative file or directory to search.
        include (str | None): Optional glob filter passed to ripgrep ``--glob``.

    Returns:
        str: §3.1 JSON envelope with ``matches``, ``content``, and ``truncated`` flag.

    Examples:
        >>> search_in_file_tool.__name__
        'search_in_file_tool'
    """
    root = ctx.workspace_path
    pattern_text = pattern.strip()
    if not pattern_text:
        return enveloped_failure("pattern must be non-empty", code=ToolResultCode.VALIDATION_ERROR)

    try:
        target, rel_path = resolve_tool_path(root, path, checkout=ctx.checkout_path)
    except (PermissionError, WorkspacePathError) as exc:
        return _path_error_envelope(exc)

    if not target.is_file() and not target.is_dir():
        return enveloped_failure(f"not found: {path}", code=ToolResultCode.VALIDATION_ERROR)

    rg_binary = _find_rg_binary()
    if rg_binary is None:
        _log_python_fallback_once()
        matches, truncated, search_error = await _run_python_search(
            workspace=root,
            pattern=pattern_text,
            search_path=target,
            include_glob=include,
        )
        engine = "python"
    else:
        matches, truncated, search_error = await _run_ripgrep(
            workspace=root,
            pattern=pattern_text,
            search_path=target,
            include_glob=include,
        )
        engine = "ripgrep"
    if search_error is not None:
        code = (
            ToolResultCode.VALIDATION_ERROR
            if "regex" in search_error.lower() or "parse" in search_error.lower()
            else ToolResultCode.INTERNAL_ERROR
        )
        return enveloped_failure(search_error, code=code)

    prefix = graphify_prefix_for_search_path(
        ctx.graphify_profiles or [],
        target if target.is_dir() else target.parent,
    )
    content = prefix + _format_match_lines(matches)
    base = rel_path if target.is_dir() else display_path_for_tool(root, target.parent)
    return enveloped_success(
        {
            "pattern": pattern_text,
            "base": base,
            "path": rel_path,
            "include": include,
            "matches": matches,
            "content": content,
            "count": len(matches),
            "truncated": truncated,
            "engine": engine,
        },
    )


__all__ = [
    "MAX_SEARCH_MATCHES",
    "_log_python_fallback_once",
    "_run_python_search",
    "search_in_file_tool",
]
