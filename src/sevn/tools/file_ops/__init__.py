"""Workspace file operation tools (`plan/tools-skills-full-inventory-wave-plan.md` Wave 1-3).

Module: sevn.tools.file_ops
Depends: sevn.tools.base, sevn.tools.decorator, sevn.tools.file_ops.read,
    sevn.tools.file_ops.list_glob, sevn.tools.file_ops.search,
    sevn.tools.file_ops.write, sevn.tools.file_ops.delete

Exports:
    register_file_ops_tools — register read-only or full mutating file tools.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sevn.tools.decorator import tool_from_decorated
from sevn.tools.file_ops.delete import delete_tool
from sevn.tools.file_ops.docstrings import (
    get_module_docstring_tool,
    get_symbol_docstring_tool,
    list_symbols_tool,
)
from sevn.tools.file_ops.list_glob import (
    file_info_tool,
    find_file_tool,
    glob_tool,
    list_dir_tool,
)
from sevn.tools.file_ops.read import read_tool
from sevn.tools.file_ops.search import search_in_file_tool
from sevn.tools.file_ops.write import (
    copy_file_tool,
    create_folder_tool,
    edit_tool,
    move_file_tool,
    write_tool,
)
from sevn.tools.transcript import history_tool, read_transcript_tool

if TYPE_CHECKING:
    from sevn.tools.base import ToolExecutor

_READ_ONLY_TOOLS: tuple[Callable[..., Any], ...] = (
    read_tool,
    list_dir_tool,
    glob_tool,
    find_file_tool,
    file_info_tool,
    search_in_file_tool,
    get_module_docstring_tool,
    get_symbol_docstring_tool,
    list_symbols_tool,
    history_tool,
    read_transcript_tool,
)

_MUTATING_TOOLS: tuple[Callable[..., Any], ...] = (
    write_tool,
    edit_tool,
    create_folder_tool,
    move_file_tool,
    copy_file_tool,
    delete_tool,
)


def register_file_ops_tools(executor: ToolExecutor, *, read_only: bool = False) -> None:
    """Register native file-operation tools on ``executor``.

    Wave 1 registers the read-only slice when ``read_only=True``. Mutating tools
    (``write``, ``edit``, …) register when ``read_only=False``.

    Args:
        executor (ToolExecutor): Session registry executor.
        read_only (bool): When ``True``, register only read-only tools.

    Returns:
        None

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.file_ops import register_file_ops_tools
        >>> exe = ToolExecutor()
        >>> register_file_ops_tools(exe, read_only=True)
        >>> {d.name for d in exe.definitions()} >= {"read", "glob"}
        True
    """
    for tool_fn in _READ_ONLY_TOOLS:
        executor.register(tool_from_decorated(tool_fn))
    if read_only:
        return
    for tool_fn in _MUTATING_TOOLS:
        executor.register(tool_from_decorated(tool_fn))


__all__ = [
    "register_file_ops_tools",
]
