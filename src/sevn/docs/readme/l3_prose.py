"""Level 3 deep-dive prose and D21 link emission for README generation.

Module: sevn.docs.readme.l3_prose
Depends: pathlib, sevn.docs.readme.links, sevn.docs.readme.manifest, sevn.docs.readme.prose,
    sevn.docs.readme.symbols

Exports:
    build_level3_deep_dive — narrative Level 3 body with module inventory and invariants.

Examples:
    >>> from pathlib import Path
    >>> from sevn.docs.readme.l3_prose import build_level3_deep_dive
    >>> from sevn.docs.readme.manifest import ReadmeEntry
    >>> body = build_level3_deep_dive(
    ...     ReadmeEntry("g", "G", "S.", "subsystem", "g", "o.md", ("src/**",), ("specs/x.md",)),
    ...     "src/sevn/gateway/",
    ...     ["src/sevn/gateway/a.py"],
    ...     {"src/sevn/gateway/a.py": [{"name": "Foo.bar", "lineno": 4}]},
    ...     {"repo_root": Path("."), "module_summaries": {}, "module_docstring_prose": {}},
    ... )
    >>> "src/sevn/gateway/a.py" in body
    True
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sevn.docs.readme.links import readme_relative_href
from sevn.docs.readme.manifest import ReadmeEntry
from sevn.docs.readme.prose import strip_inline_code
from sevn.docs.readme.symbols import README_MAX_SYMBOL_FILES, SymbolRecord
from sevn.docs.readme.text_utils import format_path_list


def build_level3_deep_dive(
    entry: ReadmeEntry,
    source_dir: str,
    py_files: list[str],
    module_symbols: dict[str, Any],
    scan: dict[str, Any],
) -> str:
    """Very detailed Level 3 with verified paths, symbols, and instructional prose.

        Args:
    entry (ReadmeEntry): Manifest row.
    source_dir (str): Primary source directory.
    py_files (list[str]): Python module paths.
    module_symbols (dict[str, list[SymbolRecord | dict[str, int | str]]]): AST symbol inventory.
    scan (dict[str, Any]): Scanner context.

        Returns:
            str: Deep-dive markdown body.

        Examples:
            >>> from pathlib import Path
            >>> body = build_level3_deep_dive(
            ...     ReadmeEntry("g", "G", "S.", "subsystem", "g", "o.md", ("src/**",), ("specs/x.md",)),
            ...     "src/sevn/gateway/",
            ...     ["src/sevn/gateway/a.py"],
            ...     {"src/sevn/gateway/a.py": [{"name": "Foo.bar", "lineno": 4}]},
            ...     {"repo_root": Path("."), "module_summaries": {}, "module_docstring_prose": {}},
            ... )
            >>> "src/sevn/gateway/a.py" in body
            True
    """
    repo_root = scan.get("repo_root")
    repo_path = repo_root if isinstance(repo_root, Path) else None
    if repo_path is not None:
        source_link = _file_markdown_link(
            entry,
            repo_path,
            source_dir if source_dir.endswith("/") else f"{source_dir}/",
            directory=True,
            label=source_dir,
        )
    else:
        source_link = f"`{source_dir}`"
    spec_links = _spec_markdown_links(entry, repo_path, list(entry.specs))
    sections: list[str] = [
        f"Primary source tree: {source_link} ({len(py_files)} Python files). "
        f"Normative design: {spec_links or format_path_list(list(entry.specs))}."
    ]
    inventory_lines: list[str] = []
    for rel in py_files[:README_MAX_SYMBOL_FILES]:
        inventory_lines.append(_build_module_inventory_block(entry, repo_path, rel, scan))
    if len(py_files) > README_MAX_SYMBOL_FILES:
        inventory_lines.append(
            f"{len(py_files) - README_MAX_SYMBOL_FILES} more Python files under "
            f"{source_link} — including "
            f"{format_path_list(py_files[README_MAX_SYMBOL_FILES : README_MAX_SYMBOL_FILES + 4], max_items=4)}."
        )
    sections.append("### Module inventory\n\n" + "\n\n".join(inventory_lines))
    if entry.specs:
        spec_link = (
            _file_markdown_link(entry, repo_path, entry.specs[0])
            if repo_path is not None
            else f"`{entry.specs[0]}`"
        )
        sections.append(
            f"### Extension and invariants\n\n"
            f"Follow {spec_link} for merge gates, error semantics, and "
            f"compatibility constraints. After code changes under {source_link}, "
            f"run `sevn readme update {entry.slug}` and `make readme-check`."
        )
    return "\n\n".join(sections)


def _spec_markdown_links(
    entry: ReadmeEntry,
    repo_path: Path | None,
    specs: list[str],
) -> str:
    """Format spec paths as D21 markdown links when ``repo_path`` is set.

    Args:
        entry (ReadmeEntry): Manifest row.
        repo_path (Path | None): Repository root.
        specs (list[str]): Normative spec paths.

        Returns:
            str: Comma-separated markdown links or backtick paths.

        Examples:
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> _spec_markdown_links(
            ...     ReadmeEntry("g", "G", "S", "subsystem", "g", "o.md", ("a",), ("specs/x.md",)),
            ...     None,
            ...     ["specs/x.md"],
            ... )
            '`specs/x.md`'
    """
    if not specs:
        return ""
    if repo_path is None:
        return format_path_list(specs)
    links = [_file_markdown_link(entry, repo_path, spec) for spec in specs[:4]]
    remainder = len(specs) - 4
    if remainder > 0:
        return ", ".join(links) + f", and {remainder} more"
    return ", ".join(links)


def _build_module_inventory_block(
    entry: ReadmeEntry,
    repo_root: Path | None,
    rel: str,
    scan: dict[str, Any],
) -> str:
    """Render one module's deep-dive prose block with D21 links.

        Args:
    entry (ReadmeEntry): Manifest row.
    repo_root (Path | None): Repository root for href emission.
    rel (str): Repo-relative Python module path.
    scan (dict[str, Any]): Scanner context.

        Returns:
            str: Markdown prose for one module.

        Examples:
            >>> block = _build_module_inventory_block(
            ...     ReadmeEntry("g", "G", "S.", "subsystem", "g", "o.md", ("src/**",), ()),
            ...     None,
            ...     "src/sevn/demo/a.py",
            ...     {"module_symbols": {}, "module_summaries": {"src/sevn/demo/a.py": "Demo."}},
            ... )
            >>> "Working with" in block
            True
    """
    module_symbols: dict[str, list[SymbolRecord | dict[str, int | str]]] = scan.get(
        "module_symbols", {}
    )
    module_summaries: dict[str, str] = scan.get("module_summaries", {})
    module_docstring_prose: dict[str, str] = scan.get("module_docstring_prose", {})
    symbols = module_symbols.get(rel, [])
    file_link = _file_markdown_link(entry, repo_root, rel) if repo_root is not None else f"`{rel}`"
    docstring = module_docstring_prose.get(rel) or module_summaries.get(rel, "")
    if docstring:
        docstring = strip_inline_code(docstring)
    if not docstring:
        docstring = f"This module implements part of the {entry.title} package."
    lines = [docstring, "", f"Working with {file_link}: inspect the public entry points below."]
    linked_symbols = _linked_symbol_list(entry, repo_root, rel, symbols)
    if linked_symbols:
        tail = linked_symbols[0]
        if len(linked_symbols) > 1:
            tail = f"{tail}, then {', '.join(linked_symbols[1:4])}"
        lines.append(f"Start with {tail}.")
    return "\n".join(lines)


def _file_markdown_link(
    entry: ReadmeEntry,
    repo_root: Path | None,
    target: str,
    *,
    directory: bool = False,
    label: str | None = None,
) -> str:
    """Build a markdown file link for generated README prose.

        Args:
    entry (ReadmeEntry): Manifest row.
    repo_root (Path | None): Repository root.
    target (str): Repo-relative target path.
    directory (bool): When true, link to a directory prefix.
    label (str | None): Optional link label; defaults to basename.

        Returns:
            str: Markdown link or backtick fallback when ``repo_root`` is absent.

        Examples:
            >>> _file_markdown_link(
            ...     ReadmeEntry("g", "G", "S.", "subsystem", "g", "docs/readmes/g.md", ("src/**",), ()),
            ...     Path("."),
            ...     "src/sevn/gateway/a.py",
            ... )
            '[`a.py`](../../src/sevn/gateway/a.py)'
    """
    if repo_root is None:
        return f"`{label or target}`"
    href = readme_relative_href(
        readme_output=entry.output,
        target=target,
        repo_root=repo_root,
        directory=directory,
    )
    text = label or target.rsplit("/", maxsplit=1)[-1]
    if directory and text.endswith("/"):
        text = text.rstrip("/")
    return f"[`{text}`]({href})"


def _linked_symbol_list(
    entry: ReadmeEntry,
    repo_root: Path | None,
    rel: str,
    symbols: Sequence[object],
) -> list[str]:
    """Format symbol records as definition-site markdown links.

        Args:
    entry (ReadmeEntry): Manifest row.
    repo_root (Path | None): Repository root.
    rel (str): Repo-relative Python module path.
    symbols (list[SymbolRecord | dict[str, int | str]]): Symbol records from the scanner.

        Returns:
            list[str]: Markdown link fragments for each symbol.

        Examples:
            >>> _linked_symbol_list(
            ...     ReadmeEntry("g", "G", "S.", "subsystem", "g", "o.md", ("src/**",), ()),
            ...     None,
            ...     "src/a.py",
            ...     [{"name": "Foo.bar", "lineno": 4}],
            ... )
            ['`Foo.bar`']
    """
    links: list[str] = []
    for record in symbols:
        if not isinstance(record, dict):
            continue
        name = str(record.get("name", "")).strip()
        if not name or "(+" in name:
            continue
        line = record.get("lineno")
        if repo_root is None or line is None:
            links.append(f"`{name}`")
            continue
        href = readme_relative_href(
            readme_output=entry.output,
            target=rel,
            repo_root=repo_root,
            line=int(line),
        )
        links.append(f"[`{name}`]({href})")
    return links
