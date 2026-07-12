"""Span tree rendering for ``sevn traces`` (W6 foundation).

Module: sevn.cli.render.tree
Depends: sevn.cli.render.console

Exports:
    SpanTreeNode — nested span row for trace rendering.
    render_span_tree — print a span hierarchy with timings and status.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sevn.cli.render.console import get_console, is_rich, plain_echo


@dataclass
class SpanTreeNode:
    """One node in a trace span tree."""

    label: str
    duration_ms: float | None = None
    status: str = "ok"
    children: list[SpanTreeNode] = field(default_factory=list)


def _format_node(node: SpanTreeNode, *, prefix: str, is_last: bool) -> list[str]:
    """Render one span node as plain-text tree lines.

    Args:
        node (SpanTreeNode): Span node to render.
        prefix (str): ASCII tree prefix for this depth.
        is_last (bool): Whether ``node`` is the last sibling.

    Returns:
        list[str]: Plain-text lines for ``node`` and descendants.

    Examples:
        >>> lines = _format_node(SpanTreeNode("a"), prefix="", is_last=True)
        >>> lines[0].startswith("└─")
        True
    """
    branch = "└─ " if is_last else "├─ "
    timing = ""
    if node.duration_ms is not None:
        timing = f" ({node.duration_ms:.1f}ms)"
    status_suffix = f" [{node.status.upper()}]" if node.status.lower() != "ok" else ""
    lines = [f"{prefix}{branch}{node.label}{timing}{status_suffix}"]
    child_prefix = prefix + ("   " if is_last else "│  ")
    for idx, child in enumerate(node.children):
        lines.extend(
            _format_node(child, prefix=child_prefix, is_last=idx == len(node.children) - 1)
        )
    return lines


def _rich_add_children(parent: object, children: list[SpanTreeNode]) -> None:
    """Attach Rich tree branches for span children.

    Args:
        parent (object): Rich ``Tree`` node to attach under.
        children (list[SpanTreeNode]): Child span nodes.

    Examples:
        >>> from rich.tree import Tree
        >>> tree = Tree("root")
        >>> _rich_add_children(tree, [SpanTreeNode("child")])
    """
    for child in children:
        label = child.label
        if child.duration_ms is not None:
            label = f"{label} ({child.duration_ms:.1f}ms)"
        if child.status.lower() != "ok":
            label = f"{label} [{child.status.upper()}]"
        branch = parent.add(label)  # type: ignore[attr-defined]
        if child.children:
            _rich_add_children(branch, child.children)


def render_span_tree(root: SpanTreeNode, *, title: str | None = None) -> None:
    """Render a nested span tree to stdout.

    Args:
        root (SpanTreeNode): Tree root (children printed; root label optional title).
        title (str | None): Optional heading above the tree.

    Examples:
        >>> node = SpanTreeNode("turn", children=[SpanTreeNode("tool_call")])
        >>> render_span_tree(node)  # doctest: +SKIP
    """
    if title:
        if is_rich():
            get_console().print(title, style="bold")
        else:
            plain_echo(title)
    if is_rich():
        from rich.tree import Tree

        tree = Tree(root.label or "trace")
        _rich_add_children(tree, root.children)
        get_console().print(tree)
        return
    for idx, child in enumerate(root.children):
        for line in _format_node(child, prefix="", is_last=idx == len(root.children) - 1):
            plain_echo(line)


__all__ = ["SpanTreeNode", "render_span_tree"]
