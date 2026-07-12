"""AST-backed docstring/symbol helpers for workspace Python files.

Module: sevn.tools.file_ops.docstrings
Depends: ast, sevn.tools.base, sevn.tools.codes, sevn.tools.context, sevn.tools.decorator, sevn.tools.paths

Exports:
    get_module_docstring_tool — return module docstring + line range.
    get_symbol_docstring_tool — return class/function docstring + line range.
    list_symbols_tool — list top-level classes/functions with line ranges.
"""

from __future__ import annotations

import ast

from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool
from sevn.tools.paths import WorkspacePathError, resolve_tool_path


def _read_python_source(ctx: ToolContext, path: str) -> tuple[str, str] | tuple[None, str]:
    """Read and validate one Python source file.

    Args:
        ctx (ToolContext): Runtime tool context.
        path (str): Workspace-relative path.

    Returns:
        tuple[str, str] | tuple[None, str]: ``(source, resolved_path)`` on success;
            ``(None, error_json)`` when validation/read fails.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_read_python_source)
        True
    """
    try:
        target, rel = resolve_tool_path(ctx.workspace_path, path, checkout=ctx.checkout_path)
    except (WorkspacePathError, PermissionError) as exc:
        code = (
            ToolResultCode.PERMISSION_DENIED
            if isinstance(exc, PermissionError)
            else ToolResultCode.VALIDATION_ERROR
        )
        return None, enveloped_failure(str(exc), code=code)
    if not target.is_file():
        return None, enveloped_failure(f"not found: {path}", code=ToolResultCode.VALIDATION_ERROR)
    if target.suffix.lower() != ".py":
        return None, enveloped_failure(
            "path must point to a .py file", code=ToolResultCode.VALIDATION_ERROR
        )
    try:
        return target.read_text(encoding="utf-8", errors="replace"), rel
    except OSError as exc:
        return None, enveloped_failure(str(exc), code=ToolResultCode.INTERNAL_ERROR)


@sevn_tool(
    name="get_module_docstring",
    category="file_ops",
    description="Return top-of-file module docstring and line range for a Python file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)
async def get_module_docstring_tool(ctx: ToolContext, path: str) -> str:
    """Return module docstring text with its source line range.

    Args:
        ctx (ToolContext): Runtime tool context.
        path (str): Python file path.

    Returns:
        str: JSON envelope with ``docstring`` and ``line_start``/``line_end``.

    Examples:
        >>> get_module_docstring_tool.__name__
        'get_module_docstring_tool'
    """
    source, payload = _read_python_source(ctx, path)
    if source is None:
        return payload
    rel = payload
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    doc = ast.get_docstring(tree, clean=False)
    if doc is None:
        return enveloped_failure("module has no docstring", code=ToolResultCode.VALIDATION_ERROR)
    if not tree.body or not isinstance(tree.body[0], ast.Expr):
        return enveloped_failure(
            "module docstring node not found", code=ToolResultCode.VALIDATION_ERROR
        )
    node = tree.body[0]
    return enveloped_success(
        {
            "path": rel,
            "docstring": doc,
            "line_start": int(getattr(node, "lineno", 1)),
            "line_end": int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
        }
    )


@sevn_tool(
    name="get_symbol_docstring",
    category="file_ops",
    description="Return class/function docstring and line range for a Python symbol.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "symbol": {"type": "string"},
        },
        "required": ["path", "symbol"],
        "additionalProperties": False,
    },
)
async def get_symbol_docstring_tool(ctx: ToolContext, path: str, symbol: str) -> str:
    """Return docstring text for a top-level class/function symbol.

    Args:
        ctx (ToolContext): Runtime tool context.
        path (str): Python file path.
        symbol (str): Top-level class/function name.

    Returns:
        str: JSON envelope with symbol metadata and docstring.

    Examples:
        >>> get_symbol_docstring_tool.__name__
        'get_symbol_docstring_tool'
    """
    source, payload = _read_python_source(ctx, path)
    if source is None:
        return payload
    rel = payload
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == symbol
        ):
            doc = ast.get_docstring(node, clean=False)
            if doc is None:
                return enveloped_failure(
                    f"symbol `{symbol}` has no docstring",
                    code=ToolResultCode.VALIDATION_ERROR,
                )
            return enveloped_success(
                {
                    "path": rel,
                    "symbol": symbol,
                    "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                    "docstring": doc,
                    "line_start": int(getattr(node, "lineno", 1)),
                    "line_end": int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                }
            )
    return enveloped_failure(f"symbol not found: {symbol}", code=ToolResultCode.VALIDATION_ERROR)


@sevn_tool(
    name="list_symbols",
    category="file_ops",
    description="List top-level class/function symbols with line ranges for a Python file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)
async def list_symbols_tool(ctx: ToolContext, path: str) -> str:
    """List top-level class/function symbols in declaration order.

    Args:
        ctx (ToolContext): Runtime tool context.
        path (str): Python file path.

    Returns:
        str: JSON envelope with ``symbols`` list.

    Examples:
        >>> list_symbols_tool.__name__
        'list_symbols_tool'
    """
    source, payload = _read_python_source(ctx, path)
    if source is None:
        return payload
    rel = payload
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    symbols: list[dict[str, object]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            symbols.append(
                {
                    "name": node.name,
                    "kind": "class",
                    "line_start": int(getattr(node, "lineno", 1)),
                    "line_end": int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                {
                    "name": node.name,
                    "kind": "function",
                    "line_start": int(getattr(node, "lineno", 1)),
                    "line_end": int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
                }
            )
    return enveloped_success({"path": rel, "symbols": symbols, "count": len(symbols)})


__all__ = [
    "get_module_docstring_tool",
    "get_symbol_docstring_tool",
    "list_symbols_tool",
]
