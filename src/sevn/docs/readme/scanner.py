"""Repo/metadata scanner for README generation context.

Module: sevn.docs.readme.scanner
Depends: ast, json, pathlib, re, tomllib, sevn.docs.readme.fingerprint, sevn.docs.readme.manifest

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

import ast
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from loguru import logger

from sevn.docs.readme.brand import load_root_intro_lines, load_root_value_prop
from sevn.docs.readme.fingerprint import expand_source_globs
from sevn.docs.readme.manifest import ReadmeEntry
from sevn.docs.readme.model import (
    README_MAX_SYMBOL_FILES,
    _first_sentence,
    strip_inline_code,
    truncate_at_sentence,
)

DEFAULT_MAX_SYMBOL_FILES = README_MAX_SYMBOL_FILES

_SPEC_HEADING = re.compile(r"^#{1,3}\s+", re.MULTILINE)


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
    module_summaries = _build_module_summaries(repo_root, py_files)
    module_symbols = extract_module_symbols(repo_root, py_files)
    context: dict[str, Any] = {
        "slug": entry.slug,
        "profile": entry.profile,
        "title": entry.title,
        "summary": entry.summary,
        "tier_owner": entry.tier_owner,
        "output": entry.output,
        "specs": list(entry.specs),
        "source_globs": list(entry.source_globs),
        "source_dir": _primary_source_dir(entry.source_globs),
        "source_roots": source_roots,
        "source_files": source_files,
        "source_py_files": py_files,
        "module_summaries": module_summaries,
        "source_excerpt": _build_source_excerpt(repo_root, py_files),
        "spec_excerpt": _read_spec_excerpt(repo_root, list(entry.specs)),
        "module_symbols": module_symbols,
        "symbol_lineno": _build_symbol_lineno_map(module_symbols),
        "repo_root": repo_root,
        "package": _read_pyproject(repo_root),
        "sevn_config": _read_sevn_json(repo_root),
        "claude_md_excerpt": _read_claude_excerpt(repo_root),
        "specs_index": _list_specs(repo_root),
        "graphify": _read_graphify(repo_root),
        "references": list(entry.specs),
    }
    if entry.profile == "root":
        context["intro_lines"] = load_root_intro_lines(repo_root)
        value_prop = load_root_value_prop(repo_root)
        if value_prop is not None:
            context["value_prop"] = value_prop
    if entry.catalog == "skills":
        context["bundled_skills"] = _scan_bundled_skills(repo_root)
    return context


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
    out: dict[str, list[dict[str, int | str]]] = {}
    for rel in py_files[:max_files]:
        path = repo_root / rel
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            logger.debug("readme_scanner: syntax error in {}", rel)
            continue
        symbols: list[dict[str, int | str]] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                methods = [
                    (f"{node.name}.{child.name}", int(child.lineno))
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not child.name.startswith("_")
                ]
                for name, lineno in methods[:3]:
                    symbols.append({"name": name, "lineno": lineno})
                if len(methods) > 3:
                    symbols.append(
                        {
                            "name": f"{node.name} (+{len(methods) - 3} methods)",
                            "lineno": int(node.lineno),
                        }
                    )
            elif isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and not node.name.startswith("_"):
                symbols.append({"name": node.name, "lineno": int(node.lineno)})
        if symbols:
            out[rel] = symbols[:max_symbols_per_file]
    return out


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


def _symbol_names(entries: list[dict[str, int | str]] | list[object]) -> list[str]:
    """Normalize symbol records to bare names (scanner-local alias).

        Args:
    entries (list[dict[str, int | str]] | list[object]): Symbol records.

        Returns:
            list[str]: Symbol names.

        Examples:
            >>> _symbol_names([{"name": "run", "lineno": 2}])
            ['run']
    """
    names: list[str] = []
    for entry in entries:
        if isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            if name:
                names.append(name)
        elif isinstance(entry, str) and entry:
            names.append(entry)
    return names


def _build_symbol_lineno_map(
    module_symbols: dict[str, list[dict[str, int | str]]],
) -> dict[str, dict[str, int]]:
    """Build a nested path → symbol → line map for link emission.

        Args:
    module_symbols (dict[str, list[dict[str, int | str]]]): Scanner symbol inventory.

        Returns:
            dict[str, dict[str, int]]: Repo-relative path to symbol line numbers.

        Examples:
            >>> _build_symbol_lineno_map({"src/a.py": [{"name": "run", "lineno": 2}]})
            {'src/a.py': {'run': 2}}
    """
    out: dict[str, dict[str, int]] = {}
    for rel, entries in module_symbols.items():
        mapping: dict[str, int] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            line = entry.get("lineno")
            if name and line is not None and "(+" not in name:
                mapping[name] = int(line)
        if mapping:
            out[rel] = mapping
    return out


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
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end < 0:
        return ""
    block = text[3:end]
    lines: list[str] = []
    in_summary = False
    for line in block.splitlines():
        if line.startswith("summary:"):
            rest = line.split(":", maxsplit=1)[1].strip()
            if rest:
                lines.append(rest.strip("'\""))
            in_summary = True
            continue
        if in_summary:
            if line.startswith((" ", "\t")):
                lines.append(line.strip().strip("'\""))
                continue
            break
    return " ".join(lines).strip()


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


def _glob_dir_prefix(pattern: str) -> str:
    """Extract a directory prefix from a manifest glob pattern.

        Args:
    pattern (str): Manifest ``source_globs`` entry.

        Returns:
            str: Repo-relative directory prefix ending with ``/``.

        Examples:
            >>> _glob_dir_prefix("src/sevn/gateway/**")
            'src/sevn/gateway/'
    """
    if pattern.endswith("/**"):
        return pattern[:-3] + "/"
    prefix = pattern.split("*", maxsplit=1)[0]
    if prefix.endswith("/"):
        return prefix
    if "/" in prefix:
        return prefix.rsplit("/", maxsplit=1)[0] + "/"
    return prefix + "/"


def _common_path_prefix(paths: list[str]) -> str:
    """Return the longest shared ``/``-delimited prefix among directory paths.

        Args:
    paths (list[str]): Directory prefixes.

        Returns:
            str: Common prefix ending with ``/``, or empty when none.

        Examples:
            >>> _common_path_prefix(["src/sevn/gateway/", "src/sevn/agent/"])
            'src/sevn/'
    """
    normalized = [p.strip("/") for p in paths if p.strip("/")]
    if not normalized:
        return ""
    split = [p.split("/") for p in normalized]
    common: list[str] = []
    for parts in zip(*split, strict=False):
        if len(set(parts)) == 1:
            common.append(parts[0])
        else:
            break
    return "/".join(common) + "/" if common else ""


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
    roots = {_glob_dir_prefix(pattern) for pattern in source_globs}
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
        root = _glob_dir_prefix(pattern)
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


_SPECS_REF = re.compile(r"(?<![\w./-])specs/")
_PLAN_PRD_REF = re.compile(r"(?<![\w./-])(?:plan|prd)/[^\s')\"]+")


def _rewrite_design_doc_refs(text: str) -> str:
    """Rewrite gitignored design-doc path cites for published README emission.

        Args:
    text (str): Docstring or markdown excerpt.

        Returns:
            str: Text with ``specs/`` retargeted and ``plan/``/``prd/`` cites genericized.

        Examples:
            >>> _rewrite_design_doc_refs("('specs/17-gateway.md')")
            "('about-sevn.bot/specs/17-gateway.md')"
            >>> _rewrite_design_doc_refs("'plan/foo.md'")
            "'the design docs'"
    """
    text = _SPECS_REF.sub("about-sevn.bot/specs/", text)
    return _PLAN_PRD_REF.sub("the design docs", text)


def _first_docstring_sentence(text: str) -> str:
    """Return the first sentence from a module docstring or leading comment line.

        Args:
    text (str): Python source text.

        Returns:
            str: First sentence without raw quote characters.

        Examples:
            >>> _first_docstring_sentence('\"\"\"First sentence only.\"\"\"\\n')
            'First sentence only.'
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = None
    doc = ast.get_docstring(tree) if tree is not None else None
    if doc:
        sentence = _first_sentence(doc)
        if sentence:
            if len(sentence) <= 200:
                return sentence
            trimmed = truncate_at_sentence(sentence, 200)
            return trimmed or sentence[:200]
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    cleaned = first.strip("\"'").replace('"""', "").replace("'''", "")
    return truncate_at_sentence(cleaned, 200) or cleaned


def _build_module_summaries(repo_root: Path, py_files: list[str]) -> dict[str, str]:
    """Map repo-relative Python paths to module docstring first sentences.

        Args:
    repo_root (Path): Repository root.
    py_files (list[str]): Repo-relative Python paths.

        Returns:
            dict[str, str]: ``src/...py`` → summary text.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path as _P
            >>> td = _P(tempfile.mkdtemp())
            >>> p = td / "src/a.py"
            >>> p.parent.mkdir(parents=True)
            >>> _ = p.write_text('\"\"\"Hello module.\"\"\"\\n', encoding="utf-8")
            >>> _build_module_summaries(td, ["src/a.py"])["src/a.py"]
            'Hello module.'
    """
    repo_root = repo_root.resolve()
    out: dict[str, str] = {}
    for rel in py_files:
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("readme_scanner: unable to read source file at {}", path)
            continue
        summary = _first_docstring_sentence(text)
        if summary:
            out[rel] = _rewrite_design_doc_refs(strip_inline_code(summary))
    return out


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
        summary = _rewrite_design_doc_refs(strip_inline_code(summary))
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
    if not text.lstrip("\ufeff").startswith("---"):
        return ("", "")
    end = text.find("\n---", 3)
    if end < 0:
        return ("", "")
    block = text[3:end]
    name = ""
    description = ""
    lines = block.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("name:"):
            name = line.split(":", maxsplit=1)[1].strip().strip("'\"")
            idx += 1
            continue
        if line.startswith("description:"):
            rest = line.split(":", maxsplit=1)[1].strip()
            if rest.startswith(">"):
                collected: list[str] = []
                idx += 1
                while idx < len(lines) and lines[idx].startswith((" ", "\t")):
                    collected.append(lines[idx].strip().strip("'\""))
                    idx += 1
                description = " ".join(collected).strip()
                continue
            if rest.startswith("|"):
                collected = []
                idx += 1
                while idx < len(lines) and lines[idx].startswith((" ", "\t")):
                    collected.append(lines[idx].strip().strip("'\""))
                    idx += 1
                description = "\n".join(collected).strip()
                continue
            collected = [rest.strip("'\"")] if rest else []
            idx += 1
            while idx < len(lines) and lines[idx].startswith((" ", "\t")):
                collected.append(lines[idx].strip().strip("'\""))
                idx += 1
            description = " ".join(collected).strip()
            continue
        idx += 1
    return (name, description)


def _build_source_excerpt(
    repo_root: Path,
    py_files: list[str],
    *,
    max_files: int = DEFAULT_MAX_SYMBOL_FILES,
) -> str:
    """Build a compact excerpt listing key Python modules.

        Args:
    repo_root (Path): Repository root.
    py_files (list[str]): Repo-relative Python paths.
    max_files (int): Maximum files to list.

        Returns:
            str: Markdown bullet list excerpt.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path as _P
            >>> td = _P(tempfile.mkdtemp())
            >>> p = td / "src/a.py"
            >>> p.parent.mkdir(parents=True)
            >>> _ = p.write_text("# mod\\n", encoding="utf-8")
            >>> "- `src/a.py`" in _build_source_excerpt(td, ["src/a.py"])
            True
    """
    lines: list[str] = []
    for rel in py_files[:max_files]:
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("readme_scanner: unable to read source file at {}", path)
            continue
        summary = _first_docstring_sentence(text)
        safe_summary = _rewrite_design_doc_refs(strip_inline_code(summary))
        if safe_summary:
            lines.append(f"- `{rel}` — {safe_summary}")
        else:
            lines.append(f"- `{rel}`")
    if len(py_files) > max_files:
        lines.append(f"- … and {len(py_files) - max_files} more Python modules")
    return "\n".join(lines)
