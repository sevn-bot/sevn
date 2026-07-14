"""Single-pass AST index for README scanner module walks.

Module: sevn.docs.readme.module_index
Depends: ast, pathlib, sevn.docs.readme.prose, sevn.docs.readme.text_utils

Exports:
    ModuleIndex — parsed module summary, prose, symbols, and raw text.
    parse_module_index — build one module index from a repo-relative path.
    build_module_indexes — index many Python modules in one pass.

Examples:
    >>> import tempfile
    >>> from pathlib import Path
    >>> td = Path(tempfile.mkdtemp())
    >>> p = td / "src/sevn/demo/a.py"
    >>> p.parent.mkdir(parents=True)
    >>> _ = p.write_text("class Foo:\\n    def bar(self): pass\\n", encoding="utf-8")
    >>> idx = parse_module_index(td, "src/sevn/demo/a.py")
    >>> idx is not None and idx.symbols[0]["name"] == "Foo.bar"
    True
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from sevn.docs.readme.prose import (
    module_docstring_prose,
    rewrite_design_doc_refs,
    strip_inline_code,
)
from sevn.docs.readme.text_utils import first_sentence, truncate_at_sentence


@dataclass(frozen=True)
class ModuleIndex:
    """Parsed module summary, prose, and symbols."""

    summary: str
    docstring_prose: str
    symbols: list[dict[str, int | str]]


def build_module_indexes(
    repo_root: Path,
    py_files: list[str],
    *,
    max_files: int,
    max_symbols_per_file: int = 8,
) -> dict[str, ModuleIndex]:
    """Index many Python modules with one read + AST parse each.

    Args:
        repo_root (Path): Repository root.
        py_files (list[str]): Repo-relative Python paths.
        max_files (int): Maximum modules to index.
        max_symbols_per_file (int): Cap symbols listed per module.

        Returns:
            dict[str, ModuleIndex]: Repo-relative path → parsed index.

        Examples:
            >>> build_module_indexes(Path(".").resolve(), [], max_files=0)
            {}
    """
    repo_root = repo_root.resolve()
    out: dict[str, ModuleIndex] = {}
    for rel in py_files[:max_files]:
        index = parse_module_index(
            repo_root,
            rel,
            max_symbols_per_file=max_symbols_per_file,
        )
        if index is not None:
            out[rel] = index
    return out


def parse_module_index(
    repo_root: Path,
    rel: str,
    *,
    max_symbols_per_file: int = 8,
) -> ModuleIndex | None:
    """Build one module index from a repo-relative Python path.

    Args:
        repo_root (Path): Repository root.
        rel (str): Repo-relative Python path.
        max_symbols_per_file (int): Cap symbols listed per module.

        Returns:
            ModuleIndex | None: Parsed index, or None when unreadable.

        Examples:
            >>> parse_module_index(Path(".").resolve(), "missing.py") is None
            True
    """
    path = repo_root / rel
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("readme_scanner: unable to read source file at {}", path)
        return None
    summary = ""
    docstring_prose = ""
    symbols: list[dict[str, int | str]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        logger.debug("readme_scanner: syntax error in {}", rel)
        summary = rewrite_design_doc_refs(strip_inline_code(_summary_from_tree(None, text)))
        return ModuleIndex(summary=summary, docstring_prose="", symbols=[])
    if not isinstance(tree, ast.Module):
        summary = rewrite_design_doc_refs(strip_inline_code(_summary_from_tree(tree, text)))
        return ModuleIndex(summary=summary, docstring_prose="", symbols=[])
    doc = ast.get_docstring(tree)
    if doc:
        prose = module_docstring_prose(doc.strip())
        if prose:
            docstring_prose = rewrite_design_doc_refs(strip_inline_code(prose))
    summary = rewrite_design_doc_refs(strip_inline_code(_summary_from_tree(tree, text)))
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
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith(
            "_"
        ):
            symbols.append({"name": node.name, "lineno": int(node.lineno)})
    return ModuleIndex(
        summary=summary,
        docstring_prose=docstring_prose,
        symbols=symbols[:max_symbols_per_file],
    )


def _summary_from_tree(tree: ast.Module | None, text: str) -> str:
    """Return first-sentence summary from an already-parsed module tree.

    Args:
        tree (ast.AST | None): Parsed module tree, or None on syntax error.
        text (str): Full module source text.

    Returns:
        str: Summary sentence capped at 200 characters.

    Examples:
        >>> _summary_from_tree(None, "class X: pass\\n")
        'class X: pass'
    """
    doc = ast.get_docstring(tree) if tree is not None else None
    if doc:
        sentence = first_sentence(doc)
        if sentence:
            if len(sentence) <= 200:
                return sentence
            trimmed = truncate_at_sentence(sentence, 200)
            return trimmed or sentence[:200]
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    cleaned = first.strip("\"'").replace('"""', "").replace("'''", "")
    return truncate_at_sentence(cleaned, 200) or cleaned
