"""Repo/metadata scanner for README generation context.

Module: sevn.docs.readme.scanner
Depends: ast, json, pathlib, re, tomllib, sevn.docs.readme.fingerprint, sevn.docs.readme.glob_paths,
    sevn.docs.readme.manifest, sevn.docs.readme.module_index, sevn.docs.readme.scan_context,
    sevn.docs.readme.text_utils

Exports:
    scan_repo_context — structured context dict for one README entry.
    resolve_spec_path — locate a manifest spec path under the repo.
    extract_module_symbols — AST inventory of public classes/functions per module.
    symbol_lineno_for_module — lookup a symbol definition line in scan output.

Examples:
    >>> from pathlib import Path
    >>> from sevn.docs.readme.manifest import get_entry, load_manifest
    >>> m = load_manifest(Path("docs/readmes/manifest.toml"))
    >>> ctx = scan_repo_context(Path("."), get_entry(m, "gateway"))
    >>> ctx["slug"] == "gateway"
    True
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from sevn.docs.readme.brand import load_root_intro_lines, load_root_value_prop
from sevn.docs.readme.fingerprint import expand_source_globs
from sevn.docs.readme.glob_paths import glob_dir_prefix
from sevn.docs.readme.manifest import ReadmeEntry
from sevn.docs.readme.module_index import ModuleIndex, build_module_indexes
from sevn.docs.readme.prose import rewrite_design_doc_refs, strip_inline_code
from sevn.docs.readme.scan_context import ScanContext
from sevn.docs.readme.symbols import README_MAX_SYMBOL_FILES
from sevn.docs.readme.text_utils import truncate_at_sentence

DEFAULT_MAX_SYMBOL_FILES = README_MAX_SYMBOL_FILES


def scan_repo_context(repo_root: Path, entry: ReadmeEntry) -> dict[str, Any]:
    """Scan repo metadata and source globs for one manifest entry.

        Args:
    repo_root (Path): Repository root.
    entry (ReadmeEntry): Manifest row to scan for.

        Returns:
            dict[str, Any]: Structured context for section renderers and templates.

        Examples:
            >>> from pathlib import Path as _P
            >>> from sevn.docs.readme.manifest import get_entry, load_manifest
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> ctx = scan_repo_context(_P("."), get_entry(m, "gateway"))
            >>> "package" in ctx and "source_files" in ctx
            True
    """
    repo_root = repo_root.resolve()
    source_paths = expand_source_globs(repo_root, entry.source_globs, tracked_only=False)
    source_files = [p.relative_to(repo_root).as_posix() for p in source_paths]
    py_files = [rel for rel in source_files if rel.endswith(".py")]

    source_roots = _source_dir_roots(entry.source_globs)
    module_indexes = build_module_indexes(
        repo_root,
        py_files,
        max_files=DEFAULT_MAX_SYMBOL_FILES,
    )
    module_summaries = {
        rel: index.summary for rel, index in module_indexes.items() if index.summary
    }
    module_docstring_prose = {
        rel: index.docstring_prose for rel, index in module_indexes.items() if index.docstring_prose
    }
    module_symbols = {rel: index.symbols for rel, index in module_indexes.items() if index.symbols}
    context = ScanContext(
        slug=entry.slug,
        profile=entry.profile,
        title=entry.title,
        summary=entry.summary,
        tier_owner=entry.tier_owner,
        output=entry.output,
        specs=list(entry.specs),
        source_globs=list(entry.source_globs),
        source_dir=_primary_source_dir(entry.source_globs),
        source_roots=source_roots,
        source_files=source_files,
        source_py_files=py_files,
        module_summaries=module_summaries,
        module_docstring_prose=module_docstring_prose,
        source_excerpt=_build_source_excerpt(module_indexes, py_files),
        spec_excerpt=_read_spec_excerpt(repo_root, list(entry.specs)),
        module_symbols=module_symbols,
        repo_root=repo_root,
        package=_read_pyproject(repo_root),
        sevn_config=_read_sevn_json(repo_root),
        claude_md_excerpt=_read_claude_excerpt(repo_root),
        specs_index=_list_specs(repo_root),
        graphify=_read_graphify(repo_root),
        references=list(entry.specs),
    )
    if entry.profile == "root":
        context.intro_lines = list(load_root_intro_lines(repo_root))
        value_prop = load_root_value_prop(repo_root)
        if value_prop is not None:
            context.value_prop = value_prop
    if entry.catalog == "skills":
        context.bundled_skills = _scan_bundled_skills(repo_root)
    return context.to_dict()


def resolve_spec_path(repo_root: Path, spec_rel: str) -> Path | None:
    """Resolve a manifest spec path to an on-disk file.

        Args:
    repo_root (Path): Repository root.
    spec_rel (str): Manifest spec path (e.g. ``specs/17-gateway.md``).

        Returns:
            Path | None: Absolute path when found.

        Examples:
            >>> from pathlib import Path as _P
            >>> p = resolve_spec_path(_P("."), "specs/01-system-overview.md")
            >>> p is None or p.is_file()
            True
    """
    repo_root = repo_root.resolve()
    candidates = [
        repo_root / spec_rel,
        repo_root / "about-sevn.bot" / spec_rel.removeprefix("specs/"),
        repo_root / "about-sevn.bot" / "specs" / Path(spec_rel).name,
        repo_root / ".ignorelocal" / "design" / spec_rel,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def extract_module_symbols(
    repo_root: Path,
    py_files: list[str],
    *,
    max_files: int = DEFAULT_MAX_SYMBOL_FILES,
    max_symbols_per_file: int = 8,
) -> dict[str, list[dict[str, int | str]]]:
    """Build a map of Python module paths to public class/function symbols.

        Args:
    repo_root (Path): Repository root.
    py_files (list[str]): Repo-relative Python paths.
    max_files (int): Maximum modules to scan.
    max_symbols_per_file (int): Cap symbols listed per module.

        Returns:
            dict[str, list[dict[str, int | str]]]: ``src/...py`` → symbol records
            with ``name`` and definition-site ``lineno``.

        Examples:
            >>> import tempfile
            >>> td = Path(tempfile.mkdtemp())
            >>> p = td / "src/sevn/demo/a.py"
            >>> p.parent.mkdir(parents=True)
            >>> _ = p.write_text("class Foo:\\n    def bar(self): pass\\n", encoding="utf-8")
            >>> syms = extract_module_symbols(td, ["src/sevn/demo/a.py"])
            >>> syms["src/sevn/demo/a.py"][0]["name"]
            'Foo.bar'
    """
    repo_root = repo_root.resolve()
    indexes = build_module_indexes(
        repo_root,
        py_files,
        max_files=max_files,
        max_symbols_per_file=max_symbols_per_file,
    )
    return {rel: index.symbols for rel, index in indexes.items() if index.symbols}


def symbol_lineno_for_module(
    symbols: dict[str, list[object]],
    rel_path: str,
    symbol: str,
) -> int | None:
    """Return the definition line for ``symbol`` inside ``rel_path``.

        Args:
    symbols (dict[str, list[object]]): Output of :func:`extract_module_symbols`.
    rel_path (str): Repo-relative Python module path.
    symbol (str): Function or ``Class.method`` name.

        Returns:
            int | None: 1-based AST line number when found.

        Examples:
            >>> symbol_lineno_for_module(
            ...     {"src/a.py": [{"name": "run", "lineno": 4}]},
            ...     "src/a.py",
            ...     "run",
            ... )
            4
    """
    for entry in symbols.get(rel_path, []):
        if isinstance(entry, dict):
            name = str(entry.get("name", ""))
            if name == symbol or name.endswith(f".{symbol}"):
                line = entry.get("lineno")
                return int(line) if line is not None else None
        elif isinstance(entry, str) and entry == symbol:
            return None
    return None


def _read_spec_excerpt(
    repo_root: Path,
    spec_paths: list[str],
    *,
    max_chars: int = 2400,
) -> str:
    """Read introductory prose from linked spec files.

        Args:
    repo_root (Path): Repository root.
    spec_paths (list[str]): Manifest ``specs`` entries.
    max_chars (int): Maximum combined excerpt length.

        Returns:
            str: Plain-text excerpt (may be empty).

        Examples:
            >>> isinstance(_read_spec_excerpt(Path("."), []), str)
            True
    """
    chunks: list[str] = []
    remaining = max_chars
    for spec_rel in spec_paths:
        path = resolve_spec_path(repo_root, spec_rel)
        if path is None:
            continue
        raw = path.read_text(encoding="utf-8")
        summary = _spec_frontmatter_summary(raw)
        body = _spec_body_without_frontmatter(raw)
        prose = _first_spec_prose(body, max_lines=40)
        if summary and (not prose or prose.startswith("Offline scaffold")):
            prose = summary
        elif summary and prose:
            prose = f"{summary}\n\n{prose}"
        if not prose:
            continue
        chunk = f"From {spec_rel}:\n{prose}"
        if len(chunk) > remaining:
            trimmed = truncate_at_sentence(chunk, remaining)
            if not trimmed:
                continue
            chunk = trimmed
        chunks.append(chunk)
        remaining -= len(chunk)
        if remaining <= 0:
            break
    return "\n\n".join(chunks).strip()


def _frontmatter_data(text: str) -> dict[str, Any]:
    """Parse YAML frontmatter from a markdown file when present.

        Args:
    text (str): Full markdown file contents.

        Returns:
            dict[str, Any]: Parsed frontmatter mapping, or empty dict.

        Examples:
            >>> _frontmatter_data("---\\nsummary: Hello\\n---\\n")
            {'summary': 'Hello'}
    """
    if not text.lstrip("\ufeff").startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _spec_frontmatter_summary(text: str) -> str:
    """Extract the ``summary`` field from YAML frontmatter when present.

        Args:
    text (str): Full spec file contents.

        Returns:
            str: Summary text or empty string.

        Examples:
            >>> _spec_frontmatter_summary("---\\nsummary: Hello world\\n---\\n")
            'Hello world'
    """
    summary = _frontmatter_data(text).get("summary", "")
    if isinstance(summary, list):
        return " ".join(str(part).strip() for part in summary if str(part).strip())
    return str(summary).strip()


def _spec_body_without_frontmatter(text: str) -> str:
    """Strip YAML frontmatter from a spec markdown file when present.

        Args:
    text (str): Full spec file contents.

        Returns:
            str: Body without leading ``---`` block.

        Examples:
            >>> _spec_body_without_frontmatter("---\\nid: x\\n---\\n\\n# Title\\n")
            '\\n\\n# Title\\n'
    """
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            return text[end + 4 :]
    return text


def _first_spec_prose(body: str, *, max_lines: int = 40) -> str:
    """Return the first substantive prose block from a spec body.

        Args:
    body (str): Spec markdown body.
    max_lines (int): Line cap for the excerpt.

        Returns:
            str: Prose excerpt.

        Examples:
            >>> txt = "# Title\\n\\nIntro paragraph.\\n\\n## Section\\nMore."
            >>> "Intro paragraph" in _first_spec_prose(txt)
            True
    """
    lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                lines.append("")
            continue
        if stripped.startswith("#"):
            if lines:
                break
            continue
        if stripped.startswith("```"):
            break
        lines.append(stripped)
        if len(lines) >= max_lines:
            break
    return "\n".join(lines).strip()


def _source_dir_roots(source_globs: tuple[str, ...]) -> list[str]:
    """List distinct source-tree roots referenced by manifest globs.

        Args:
    source_globs (tuple[str, ...]): Manifest ``source_globs`` patterns.

        Returns:
            list[str]: Sorted unique directory prefixes.

        Examples:
            >>> _source_dir_roots(("src/sevn/gateway/**", "infra/**"))
            ['infra/', 'src/sevn/gateway/']
    """
    roots = {glob_dir_prefix(pattern) for pattern in source_globs}
    return sorted(roots)


def _primary_source_dir(source_globs: tuple[str, ...]) -> str:
    """Pick a badge/link source directory from manifest globs.

        Args:
    source_globs (tuple[str, ...]): Manifest ``source_globs`` patterns.

        Returns:
            str: Repo-relative directory prefix ending with ``/``.

        Examples:
            >>> _primary_source_dir(("src/sevn/gateway/**",))
            'src/sevn/gateway/'
            >>> _primary_source_dir(("src/sevn/secrets/**", "src/sevn/security/secrets/**"))
            'src/sevn/secrets/'
    """
    dirs: list[str] = []
    seen: set[str] = set()
    for pattern in source_globs:
        root = glob_dir_prefix(pattern)
        if root not in seen:
            dirs.append(root)
            seen.add(root)
    if not dirs:
        return "src/sevn/"
    if len(dirs) == 1:
        return dirs[0]
    return dirs[0]


def _read_pyproject(repo_root: Path) -> dict[str, str]:
    """Read name/version/description from ``pyproject.toml``.

        Args:
    repo_root (Path): Repository root.

        Returns:
            dict[str, str]: Package metadata with ``name``, ``version``, ``description``.

        Examples:
            >>> from pathlib import Path as _P
            >>> meta = _read_pyproject(_P("."))
            >>> meta["name"]
            'sevn'
    """
    path = repo_root / "pyproject.toml"
    if not path.is_file():
        return {"name": "sevn", "version": "0.0.0", "description": ""}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        return {"name": "sevn", "version": "0.0.0", "description": ""}
    return {
        "name": str(project.get("name", "sevn")),
        "version": str(project.get("version", "0.0.0")),
        "description": str(project.get("description", "")),
    }


def _read_sevn_json(repo_root: Path) -> dict[str, Any] | None:
    """Read ``sevn.json`` when present.

        Args:
    repo_root (Path): Repository root.

        Returns:
            dict[str, Any] | None: Parsed config or ``None`` when absent/invalid.

        Examples:
            >>> isinstance(_read_sevn_json(Path("/nonexistent")), (dict, type(None)))
            True
    """
    for candidate in (repo_root / "sevn.json", repo_root / "config" / "sevn.json"):
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("readme_scanner: invalid sevn.json at {}", candidate)
            return None
        if isinstance(data, dict):
            return data
    return None


def _read_claude_excerpt(repo_root: Path, *, max_lines: int = 40) -> str:
    """Return the first ``max_lines`` of ``CLAUDE.md``.

        Args:
    repo_root (Path): Repository root.
    max_lines (int): Maximum lines to include.

        Returns:
            str: Excerpt text (empty when file missing).

        Examples:
            >>> isinstance(_read_claude_excerpt(Path(".")), str)
            True
    """
    path = repo_root / "CLAUDE.md"
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()[:max_lines]
    return "\n".join(lines).strip()


def _list_specs(repo_root: Path) -> list[str]:
    """List ``specs/*.md`` paths relative to repo root.

        Args:
    repo_root (Path): Repository root.

        Returns:
            list[str]: Sorted spec paths (may be empty).

        Examples:
            >>> specs = _list_specs(Path("."))
            >>> all(p.startswith("specs/") for p in specs) or specs == []
            True
    """
    specs_dir = repo_root / ".ignorelocal" / "design" / "specs"
    if not specs_dir.is_dir():
        specs_dir = repo_root / "specs"
    if not specs_dir.is_dir():
        return []
    prefix = specs_dir.relative_to(repo_root)
    return sorted((prefix / p.name).as_posix() for p in specs_dir.glob("*.md"))


def _read_graphify(repo_root: Path) -> dict[str, Any] | None:
    """Load optional ``graphify-out/graph.json`` summary when present.

        Args:
    repo_root (Path): Repository root.

        Returns:
            dict[str, Any] | None: Node/edge counts or ``None`` when absent.

        Examples:
            >>> isinstance(_read_graphify(Path(".")), (dict, type(None)))
            True
    """
    path = repo_root / "graphify-out" / "graph.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.debug("readme_scanner: invalid graphify graph.json at {}", path)
        return None
    if not isinstance(data, dict):
        return None
    nodes = data.get("nodes")
    edges = data.get("edges")
    return {
        "path": path.relative_to(repo_root).as_posix(),
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "edge_count": len(edges) if isinstance(edges, list) else 0,
    }


def _build_source_excerpt(
    module_indexes: Mapping[str, ModuleIndex],
    py_files: list[str],
    *,
    max_files: int = DEFAULT_MAX_SYMBOL_FILES,
) -> str:
    """Build a compact excerpt listing key Python modules.

    Args:
        module_indexes (dict[str, ModuleIndex]): Parsed module indexes.
        py_files (list[str]): Repo-relative Python paths.
        max_files (int): Maximum files to list.

    Returns:
        str: Markdown bullet list excerpt.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> from sevn.docs.readme.module_index import parse_module_index
        >>> td = _P(tempfile.mkdtemp())
        >>> p = td / "src/a.py"
        >>> p.parent.mkdir(parents=True)
        >>> _ = p.write_text('\"\"\"Mod.\"\"\"\\n', encoding="utf-8")
        >>> idx = parse_module_index(td, "src/a.py")
        >>> "- `src/a.py`" in _build_source_excerpt({"src/a.py": idx}, ["src/a.py"])
        True
    """
    lines: list[str] = []
    for rel in py_files[:max_files]:
        index = module_indexes.get(rel)
        if index is None:
            lines.append(f"- `{rel}`")
            continue
        summary = index.summary
        safe_summary = rewrite_design_doc_refs(strip_inline_code(summary)) if summary else ""
        if safe_summary:
            lines.append(f"- `{rel}` — {safe_summary}")
        else:
            lines.append(f"- `{rel}`")
    if len(py_files) > max_files:
        lines.append(f"- … and {len(py_files) - max_files} more Python modules")
    return "\n".join(lines)


def _scan_bundled_skills(repo_root: Path) -> list[dict[str, str]]:
    """Collect bundled skill rows from ``core/*/SKILL.md`` frontmatter.

        Args:
    repo_root (Path): Repository root.

        Returns:
            list[dict[str, str]]: Rows with ``name``, ``path``, and ``summary`` keys.

        Examples:
            >>> rows = _scan_bundled_skills(Path("."))
            >>> isinstance(rows, list)
            True
    """
    repo_root = repo_root.resolve()
    core = repo_root / "src/sevn/data/bundled_skills/core"
    if not core.is_dir():
        return []
    rows: list[dict[str, str]] = []
    for skill_dir in sorted(core.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        rel = skill_md.relative_to(repo_root).as_posix()
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            logger.warning("readme_scanner: unable to read bundled skill at {}", skill_md)
            continue
        name, description = _skill_frontmatter_fields(text)
        if not name:
            name = skill_dir.name
        summary = description.strip()
        if len(summary) > 300:
            summary = truncate_at_sentence(summary, 300) or summary[:300]
        if not summary:
            summary = name
        summary = rewrite_design_doc_refs(strip_inline_code(summary))
        rows.append({"name": name, "path": rel, "summary": summary})
    return rows


def _skill_frontmatter_fields(text: str) -> tuple[str, str]:
    """Extract ``name`` and ``description`` from a ``SKILL.md`` frontmatter block.

        Args:
    text (str): Full ``SKILL.md`` contents.

        Returns:
            tuple[str, str]: Skill name and description text.

        Examples:
            >>> _skill_frontmatter_fields("---\\nname: demo\\ndescription: Do things.\\n---\\n")
            ('demo', 'Do things.')
            >>> _skill_frontmatter_fields(
            ...     "---\\nname: fold\\ndescription: >-\\n  Line one.\\n  Line two.\\n---\\n"
            ... )
            ('fold', 'Line one. Line two.')
    """
    data = _frontmatter_data(text)
    name = str(data.get("name", "")).strip()
    description = data.get("description", "")
    if isinstance(description, list):
        description = " ".join(str(part).strip() for part in description if str(part).strip())
    else:
        description = str(description).strip()
    return (name, description)
