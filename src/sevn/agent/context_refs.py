"""Context reference injection (@file, @folder).

Module: sevn.agent.context_refs
Depends: pathlib, re

Exports:
    expand_context_refs — replace @path tokens with file contents in user text.
"""

from __future__ import annotations

import re
from pathlib import Path  # noqa: TC003 — runtime path resolution

_REF_RE = re.compile(r"@([^\s@]+)")


def expand_context_refs(text: str, *, workspace_root: Path) -> str:
    """Expand ``@relative/path`` tokens to fenced file contents.

    Args:
        text (str): Inbound user message.
        workspace_root (Path): Operator workspace root for path resolution.

    Returns:
        str: Text with refs expanded (unknown refs left unchanged).

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as t:
        ...     root = Path(t)
        ...     _ = (root / "note.md").write_text("hello")
        ...     out = expand_context_refs("see @note.md", workspace_root=root)
        ...     "hello" in out
        True
    """
    if "@" not in text:
        return text

    def _replace(match: re.Match[str]) -> str:
        rel = match.group(1)
        target = (workspace_root / rel).resolve()
        try:
            target.relative_to(workspace_root.resolve())
        except ValueError:
            return match.group(0)
        if not target.is_file():
            return match.group(0)
        content = target.read_text(encoding="utf-8", errors="replace")
        return f"```file:{rel}\n{content}\n```"

    return _REF_RE.sub(_replace, text)
