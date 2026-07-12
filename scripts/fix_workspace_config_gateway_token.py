#!/usr/bin/env python3
"""Rewrite test ``WorkspaceConfig(...)`` calls when ``gateway.token`` is missing.

Module: scripts.fix_workspace_config_gateway_token
Depends: ast, pathlib, sys

Exports:
    main — CLI entry; rewrite Python sources in place.

Examples:
    >>> isinstance(_GW_REF, str) and "${SECRET:" in _GW_REF
    True
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_GW_REF = "${SECRET:keychain:sevn.gateway.token}"


class _WorkspaceConfigTransformer(ast.NodeTransformer):
    """Rewrite bare ``WorkspaceConfig(...)`` to ``WorkspaceConfig.minimal(...)``."""

    def visit_Call(self, node: ast.Call) -> ast.AST:
        """Transform one call node when it targets ``WorkspaceConfig`` without gateway.

        Args:
            node (ast.Call): AST call node under visit.

        Returns:
            ast.AST: Possibly rewritten call node.

        Examples:
            >>> t = _WorkspaceConfigTransformer()
            >>> n = ast.parse("WorkspaceConfig()").body[0].value
            >>> isinstance(t.visit_Call(n), ast.Call)
            True
        """
        self.generic_visit(node)
        if not _is_workspace_config_call(node.func):
            return node
        if _call_has_gateway(node):
            return node
        keywords: list[ast.keyword] = []
        for kw in node.keywords:
            if kw.arg == "schema_version" and _is_schema_version_one(kw.value):
                continue
            keywords.append(kw)
        return ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="WorkspaceConfig", ctx=ast.Load()),
                attr="minimal",
                ctx=ast.Load(),
            ),
            args=[],
            keywords=keywords,
        )


class _ParseConfigTransformer(ast.NodeTransformer):
    """Inject ``gateway.token`` into dict literals passed to config parsers."""

    def visit_Call(self, node: ast.Call) -> ast.AST:
        """Transform ``parse_workspace_config`` / ``model_validate`` dict args.

        Args:
            node (ast.Call): AST call node under visit.

        Returns:
            ast.AST: Possibly rewritten call node.

        Examples:
            >>> t = _ParseConfigTransformer()
            >>> n = ast.parse('parse_workspace_config({"schema_version": 1})').body[0].value
            >>> isinstance(t.visit_Call(n), ast.Call)
            True
        """
        self.generic_visit(node)
        if not (len(node.args) == 1 and isinstance(node.args[0], ast.Dict)):
            return node
        if not (
            (isinstance(node.func, ast.Name) and node.func.id == "parse_workspace_config")
            or (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "WorkspaceConfig"
                and node.func.attr == "model_validate"
            )
        ):
            return node
        d = node.args[0]
        if not _dict_has_schema_version(d) or _dict_has_gateway_key(d):
            return node
        new_keys = list(d.keys)
        new_values = list(d.values)
        new_keys.append(ast.Constant(value="gateway"))
        new_values.append(
            ast.Dict(
                keys=[ast.Constant(value="token")],
                values=[ast.Constant(value=_GW_REF)],
            ),
        )
        return ast.Call(
            func=node.func,
            args=[ast.Dict(keys=new_keys, values=new_values)],
            keywords=node.keywords,
        )


def _is_workspace_config_call(func: ast.AST) -> bool:
    """Return whether ``func`` names ``WorkspaceConfig``.

    Args:
        func (ast.AST): Callee expression from a ``Call`` node.

    Returns:
        bool: ``True`` when ``func`` is the name ``WorkspaceConfig``.

    Examples:
        >>> _is_workspace_config_call(ast.Name(id="WorkspaceConfig", ctx=ast.Load()))
        True
    """
    return isinstance(func, ast.Name) and func.id == "WorkspaceConfig"


def _call_has_gateway(node: ast.Call) -> bool:
    """Return whether ``node`` already passes a ``gateway=`` keyword.

    Args:
        node (ast.Call): Candidate ``WorkspaceConfig`` call node.

    Returns:
        bool: ``True`` when a ``gateway`` keyword is present.

    Examples:
        >>> n = ast.parse("WorkspaceConfig(gateway={})").body[0].value
        >>> _call_has_gateway(n)
        True
    """
    return any(kw.arg == "gateway" for kw in node.keywords if kw.arg)


def _is_schema_version_one(value: ast.AST) -> bool:
    """Return whether ``value`` is the constant ``1``.

    Args:
        value (ast.AST): Keyword value node.

    Returns:
        bool: ``True`` for ``ast.Constant(value=1)``.

    Examples:
        >>> _is_schema_version_one(ast.Constant(value=1))
        True
    """
    return isinstance(value, ast.Constant) and value.value == 1


def _dict_has_schema_version(d: ast.Dict) -> bool:
    """Return whether dict literal ``d`` includes ``schema_version``.

    Args:
        d (ast.Dict): Dict literal node.

    Returns:
        bool: ``True`` when a ``schema_version`` key is present.

    Examples:
        >>> d = ast.parse('{"schema_version": 1}').body[0].value
        >>> _dict_has_schema_version(d)
        True
    """
    return any(isinstance(key, ast.Constant) and key.value == "schema_version" for key in d.keys)


def _dict_has_gateway_key(d: ast.Dict) -> bool:
    """Return whether dict literal ``d`` includes a ``gateway`` key.

    Args:
        d (ast.Dict): Dict literal node.

    Returns:
        bool: ``True`` when a ``gateway`` key is present.

    Examples:
        >>> d = ast.parse('{"gateway": {}}').body[0].value
        >>> _dict_has_gateway_key(d)
        True
    """
    return any(isinstance(key, ast.Constant) and key.value == "gateway" for key in d.keys)


class _GatewayConfigTransformer(ast.NodeTransformer):
    """Inject ``token=`` into bare ``GatewayConfig(...)`` keyword calls."""

    def visit_Call(self, node: ast.Call) -> ast.AST:
        """Transform ``GatewayConfig`` calls that omit ``token``.

        Args:
            node (ast.Call): AST call node under visit.

        Returns:
            ast.AST: Possibly rewritten call node.

        Examples:
            >>> t = _GatewayConfigTransformer()
            >>> n = ast.parse("GatewayConfig(host='127.0.0.1')").body[0].value
            >>> isinstance(t.visit_Call(n), ast.Call)
            True
        """
        self.generic_visit(node)
        if not (isinstance(node.func, ast.Name) and node.func.id == "GatewayConfig"):
            return node
        if node.args:
            return node
        if any(kw.arg == "token" for kw in node.keywords if kw.arg):
            return node
        token_kw = ast.keyword(
            arg="token",
            value=ast.Constant(value=_GW_REF),
        )
        return ast.Call(
            func=node.func,
            args=node.args,
            keywords=[token_kw, *node.keywords],
        )


def _transform_source(text: str) -> str:
    """Parse ``text``, apply AST transforms, and return unparsed source.

    Args:
        text (str): Python module source.

    Returns:
        str: Transformed source text.

    Examples:
        >>> out = _transform_source("x = 1\\n")
        >>> out.startswith("x")
        True
    """
    tree = ast.parse(text)
    tree = _GatewayConfigTransformer().visit(tree)
    tree = _WorkspaceConfigTransformer().visit(tree)
    tree = _ParseConfigTransformer().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + ("\n" if text.endswith("\n") else "")


def main(paths: list[str]) -> int:
    """Rewrite files under ``paths``; return process exit code.

    Args:
        paths (list[str]): Files or directories to scan.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> main([])
        0
    """
    changed = 0
    for raw in paths:
        path = Path(raw)
        if not path.is_file() or path.suffix != ".py":
            continue
        text = path.read_text(encoding="utf-8")
        if "WorkspaceConfig(" not in text and "parse_workspace_config(" not in text:
            continue
        try:
            new_text = _transform_source(text)
        except SyntaxError:
            print(f"skip syntax error: {path}", file=sys.stderr)
            continue
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed += 1
            print(path)
    print(f"updated {changed} files")
    return 0


if __name__ == "__main__":
    roots = sys.argv[1:] or ["tests"]
    files: list[str] = []
    for root in roots:
        p = Path(root)
        if p.is_file():
            files.append(str(p))
        else:
            files.extend(str(f) for f in p.rglob("*.py"))
    raise SystemExit(main(files))
