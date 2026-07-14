"""Level 2 how-it-works prose for subsystem README profiles.

Module: sevn.docs.readme.l2_prose
Depends: dataclasses, sevn.docs.readme.manifest, sevn.docs.readme.symbols, sevn.docs.readme.text_utils

Exports:
    L2ProsePolicy — manifest-driven Level-2 flow policy.
    build_level2_how_it_works — technical Level 2 body from scan context.

Examples:
    >>> from sevn.docs.readme.l2_prose import build_level2_how_it_works
    >>> from sevn.docs.readme.manifest import ReadmeEntry
    >>> body = build_level2_how_it_works(
    ...     ReadmeEntry("g", "Gateway", "S.", "subsystem", "g", "o.md", ("src/**",), ("specs/x.md",)),
    ...     {"source_dir": "src/sevn/gateway/"},
    ...     ["src/sevn/gateway/a.py"],
    ...     "",
    ... )
    >>> "src/sevn/gateway/" in body
    True
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sevn.docs.readme.manifest import ReadmeEntry
from sevn.docs.readme.symbols import symbol_names
from sevn.docs.readme.text_utils import format_path_list, truncate_at_sentence


@dataclass(frozen=True)
class L2ProsePolicy:
    """Manifest-driven policy for Level-2 flow paragraphs."""

    turn_spine: bool
    provider_keys_via_proxy: bool
    l2_flow_suffix: str

    @classmethod
    def from_entry(cls, entry: ReadmeEntry) -> L2ProsePolicy:
        """Build policy from a manifest row.

        Args:
            entry (ReadmeEntry): Manifest row.

        Returns:
            L2ProsePolicy: Parsed policy flags.

        Examples:
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> L2ProsePolicy.from_entry(ReadmeEntry("g", "G", "S", "subsystem", "g", "o.md", ("a",), ()))
            L2ProsePolicy(turn_spine=False, provider_keys_via_proxy=False, l2_flow_suffix='')
        """
        return cls(
            turn_spine=entry.turn_spine,
            provider_keys_via_proxy=entry.provider_keys_via_proxy,
            l2_flow_suffix=entry.l2_flow_suffix.strip(),
        )

    def flow_suffix(self) -> str:
        """Return optional suffix prose for turn-spine flow paragraphs.

        Returns:
            str: Suffix sentence or empty string.

        Examples:
            >>> L2ProsePolicy(True, False, "Extra.").flow_suffix()
            'Extra.'
        """
        if self.l2_flow_suffix:
            return self.l2_flow_suffix
        if self.provider_keys_via_proxy:
            return "Provider API calls are brokered by the egress proxy."
        return ""


def build_level2_how_it_works(
    entry: ReadmeEntry,
    scan: dict[str, Any],
    py_files: list[str],
    spec_excerpt: str,
) -> str:
    """Technical Level 2 — roughly 2x a brief overview.

    Args:
        entry (ReadmeEntry): Manifest row.
        scan (dict[str, Any]): Scanner context.
        py_files (list[str]): Repo-relative Python paths.
        spec_excerpt (str): Spec prose excerpt.

    Returns:
        str: Technical how-it-works body.

    Examples:
        >>> body = build_level2_how_it_works(
        ...     ReadmeEntry("g", "Gateway", "S.", "subsystem", "g", "o.md", ("src/**",), ("specs/x.md",)),
        ...     {"source_dir": "src/sevn/gateway/"},
        ...     ["src/sevn/gateway/a.py"],
        ...     "",
        ... )
        >>> "src/sevn/gateway/" in body
        True
    """
    policy = L2ProsePolicy.from_entry(entry)
    source_dir = str(scan.get("source_dir", "src/sevn/"))
    source_roots = [str(root) for root in scan.get("source_roots", ())]
    module_symbols: dict[str, list[dict[str, int | str]]] = scan.get("module_symbols", {})
    flow = _build_flow_section(entry, policy, py_files, source_dir, source_roots, module_symbols)
    if len(source_roots) > 1:
        layout = (
            f"### Components and layout\n\n"
            f"Implementation spans {format_path_list(source_roots, max_items=len(source_roots))}. "
            f"The package contains {len(py_files)} Python module(s); primary entry points "
            f"include {format_path_list(py_files, max_items=6)}."
        )
    else:
        layout = (
            f"### Components and layout\n\n"
            f"Implementation lives under `{source_dir}`. "
            f"The package contains {len(py_files)} Python module(s); primary entry points "
            f"include {format_path_list(py_files, max_items=6)}."
        )
    parts = [
        layout,
        flow,
        f"### Configuration\n\n"
        f"Operator settings come from `sevn.json` in the workspace. Related normative "
        f"specs: {format_path_list(list(entry.specs))}. "
        f"Run `sevn config validate` after edits; use `sevn doctor` to confirm the "
        f"install sees the expected layout.",
    ]
    if module_symbols:
        symbol_lines = []
        for rel, symbols in list(module_symbols.items())[:5]:
            names = symbol_names(symbols)
            symbol_lines.append(f"- `{rel}` — {', '.join(f'`{s}`' for s in names[:4])}")
        parts.append("### Key modules\n\n" + "\n".join(symbol_lines))
    if spec_excerpt:
        spec_context = truncate_at_sentence(spec_excerpt, 1200)
        if spec_context:
            parts.append(f"### Spec context\n\n{spec_context}")
    return "\n\n".join(parts)


def _build_flow_section(
    entry: ReadmeEntry,
    policy: L2ProsePolicy,
    py_files: list[str],
    source_dir: str,
    source_roots: list[str],
    module_symbols: dict[str, list[dict[str, int | str]]],
) -> str:
    """Build the data-and-control-flow subsection.

    Args:
        entry (ReadmeEntry): Manifest row.
        policy (L2ProsePolicy): Level-2 prose policy.
        py_files (list[str]): Repo-relative Python paths.
        source_dir (str): Primary source directory.
        source_roots (list[str]): All source roots from globs.
        module_symbols (dict): Symbol inventory.

        Returns:
            str: Markdown flow subsection.

        Examples:
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> body = _build_flow_section(
            ...     ReadmeEntry("g", "G", "S", "subsystem", "g", "o.md", ("a",), ()),
            ...     L2ProsePolicy(True, False, ""),
            ...     ["src/a.py"],
            ...     "src/sevn/",
            ...     ["src/sevn/"],
            ...     {},
            ... )
            >>> "turn spine" in body
            True
    """
    if policy.turn_spine:
        flow = (
            f"### Data and control flow\n\n"
            f"{entry.title} sits in the sevn.bot turn spine: a channel delivers a message, "
            f"the gateway normalises it, triage routes work to the right executor, and the "
            f"reply returns through the same channel adapter. This subsystem owns the "
            f"responsibilities described in the manifest summary."
        )
        suffix = policy.flow_suffix()
        if suffix:
            flow += f" {suffix}"
        return flow
    module_names = [
        rel.rsplit("/", maxsplit=1)[-1].removesuffix(".py").replace("_", " ")
        for rel in py_files[:6]
    ]
    if module_names:
        modules_phrase = ", ".join(f"`{name}`" for name in module_names[:4])
        if len(module_names) > 4:
            modules_phrase += f", and {len(module_names) - 4} more"
        graph = (
            f"{entry.title} is organized around {modules_phrase} under "
            f"{format_path_list([source_dir], max_items=1)}"
        )
    else:
        graph = f"{entry.title} implements supporting services under `{source_dir}`"
    if len(source_roots) > 1:
        graph += (
            f"; implementation spans {format_path_list(source_roots, max_items=len(source_roots))}."
        )
    else:
        graph += f" with {len(py_files)} Python module(s) in the scanned tree."
    entry_points: list[str] = []
    for rel, symbols in list(module_symbols.items())[:4]:
        names = symbol_names(symbols)
        if names:
            entry_points.append(f"{rel.rsplit('/', 1)[-1]} ({names[0]})")
    if entry_points:
        graph += f" Primary entry points include {', '.join(entry_points)}."
    return f"### Data and control flow\n\n{graph}"
