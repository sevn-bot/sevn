"""Typed scan context returned by the README repo scanner.

Module: sevn.docs.readme.scan_context
Depends: dataclasses, pathlib, typing

Exports:
    ScanContext — structured scanner output for one manifest entry.

Examples:
    >>> from sevn.docs.readme.scan_context import ScanContext
    >>> ctx = ScanContext(slug="gateway", profile="subsystem", title="Gateway", summary="S.")
    >>> ctx.to_dict()["slug"]
    'gateway'
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ScanContext:
    """Structured context for README section renderers and templates."""

    slug: str
    profile: str
    title: str
    summary: str
    tier_owner: str = ""
    output: str = ""
    specs: list[str] = field(default_factory=list)
    source_globs: list[str] = field(default_factory=list)
    source_dir: str = "src/sevn/"
    source_roots: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    source_py_files: list[str] = field(default_factory=list)
    module_summaries: dict[str, str] = field(default_factory=dict)
    module_docstring_prose: dict[str, str] = field(default_factory=dict)
    source_excerpt: str = ""
    spec_excerpt: str = ""
    module_symbols: dict[str, list[dict[str, int | str]]] = field(default_factory=dict)
    symbol_lineno: dict[str, dict[str, int]] = field(default_factory=dict)
    repo_root: Path | None = None
    package: dict[str, str] = field(default_factory=dict)
    sevn_config: dict[str, Any] | None = None
    claude_md_excerpt: str = ""
    specs_index: list[str] = field(default_factory=list)
    graphify: dict[str, Any] | None = None
    references: list[str] = field(default_factory=list)
    intro_lines: list[str] = field(default_factory=list)
    value_prop: str | None = None
    bundled_skills: list[dict[str, str]] = field(default_factory=list)
    index_entries: list[dict[str, Any]] = field(default_factory=list)
    subsystem_entries: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict compatible with legacy section builders.

        Returns:
            dict[str, Any]: Scanner context as a mapping.

        Examples:
            >>> ScanContext(slug="gateway", profile="subsystem", title="G", summary="S.").to_dict()["slug"]
            'gateway'
        """
        return asdict(self)
