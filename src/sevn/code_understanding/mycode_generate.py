"""MYCODE markdown generator + atomic writer (`specs/28-code-understanding.md` §2.3).

Module: sevn.code_understanding.mycode_generate
Depends: os, pathlib, typing, sevn.code_understanding.models

Exports:
    Classes:
        Transport — minimal Protocol matching ``specs/05-llm-transports.md``.
    Functions:
        generate_mycode_markdown — render a digest (and optional CGR JSON) to markdown.
        write_mycode — atomically write markdown content to disk.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.code_understanding.models import MycodeScanDigest


@runtime_checkable
class Transport(Protocol):
    """Minimal completion transport contract used by MYCODE generation.

    The full transport contract lives in ``specs/05-llm-transports.md``. This
    Protocol exists so this module imports nothing from a not-yet-built
    transport package; any object with a synchronous ``complete(prompt) -> str``
    method satisfies it.

    Example:
        >>> class _Stub:
        ...     def complete(self, prompt: str) -> str:
        ...         return prompt[:5]
        >>> isinstance(_Stub(), Transport)
        True
    """

    def complete(self, prompt: str) -> str:
        """Return a single non-streaming completion for ``prompt``.

        Args:
            prompt (str): Text to send upstream.

        Returns:
            str: Provider response.

        Examples:
            >>> class _S:
            ...     def complete(self, prompt: str) -> str:
            ...         return prompt
            >>> _S().complete("hi")
            'hi'
        """
        ...


def _render_deterministic(digest: MycodeScanDigest, cgr_json: bytes | None) -> str:
    """Render a digest to deterministic markdown without calling any LLM.

    Args:
        digest (MycodeScanDigest): Scan result to render.
        cgr_json (bytes | None): Optional CGR export bytes; size noted in output.

    Returns:
        str: UTF-8 markdown text.

    Examples:
        >>> from sevn.code_understanding.models import MycodeScanDigest
        >>> body = _render_deterministic(MycodeScanDigest(root="/r"), None)
        >>> "MYCODE" in body
        True
    """
    lines: list[str] = []
    lines.append("# MYCODE")
    lines.append("")
    lines.append(f"- root: `{digest.root}`")
    lines.append(f"- files: {len(digest.files)}")
    if digest.ignored:
        lines.append(f"- ignored patterns: {', '.join(sorted(digest.ignored))}")
    if cgr_json is not None:
        lines.append(f"- code-graph-rag export: {len(cgr_json)} bytes")
    lines.append("")
    lines.append("## Files")
    lines.append("")
    for entry in digest.files:
        lines.append(f"### `{entry.path}` ({entry.language})")
        lines.append("")
        lines.append(f"- lines: {entry.line_count}")
        if entry.symbols:
            lines.append(f"- symbols: {', '.join(entry.symbols)}")
        if entry.imports:
            lines.append(f"- imports: {', '.join(entry.imports)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_mycode_markdown(
    digest: MycodeScanDigest,
    *,
    cgr_json: bytes | None = None,
    transport: Transport | None = None,
) -> str:
    """Render a digest to a markdown string suitable for ``MYCODE.md``.

    When ``transport`` is ``None`` (or fails), the function returns a fully
    deterministic markdown rendering — useful for unit tests and offline
    skill runs. When a transport is supplied, the deterministic body is sent
    as a prompt and the upstream completion is returned verbatim (the caller
    decides whether to write the upstream text or fall back).

    Args:
        digest (MycodeScanDigest): Scan result to render.
        cgr_json (bytes | None, optional): Optional CGR export bytes. Defaults to None.
        transport (Transport | None, optional): Optional completion transport.
            Defaults to None.

    Returns:
        str: Markdown body terminated with a trailing newline.

    Examples:
        >>> from sevn.code_understanding.models import MycodeScanDigest
        >>> generate_mycode_markdown(MycodeScanDigest(root="/r")).startswith("# MYCODE")
        True
    """
    deterministic = _render_deterministic(digest, cgr_json)
    if transport is None:
        return deterministic
    try:
        upstream = transport.complete(deterministic)
    except Exception:
        return deterministic
    return upstream if isinstance(upstream, str) and upstream else deterministic


def write_mycode(output_path: Path, content: str) -> None:
    """Atomically write ``content`` to ``output_path``.

    The function creates parent directories on demand, writes to a sibling
    ``.tmp`` file, then ``os.replace``-s it onto the target so concurrent
    readers never see a partial document.

    Args:
        output_path (Path): Destination ``MYCODE.md`` path.
        content (str): UTF-8 markdown text to persist.

    Raises:
        OSError: When the target directory cannot be created.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> target = _P(tempfile.mkdtemp()) / "out" / "MYCODE.md"
        >>> write_mycode(target, "# MYCODE\\n")
        >>> target.read_text(encoding="utf-8")
        '# MYCODE\\n'
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, output_path)
