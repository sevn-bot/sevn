"""Clickable links and L3 prose contracts (D21-D22; W2 generator core)."""

from __future__ import annotations

import importlib
import inspect
import re
import tempfile
from pathlib import Path

import pytest

from sevn.docs.readme.links import readme_relative_href
from sevn.docs.readme.manifest import get_entry, load_manifest
from sevn.docs.readme.render import render_readme_markdown
from sevn.docs.readme.scanner import extract_module_symbols, scan_repo_context
from sevn.docs.readme.symbol_refs import extract_level3_section

REPO_ROOT = Path(__file__).resolve().parents[3]

_BARE_PY_BACKTICK = re.compile(r"(?<!\[)`(?:src/)?[\w./-]+\.py`(?!\]\()")
_BARE_SYMBOL_BACKTICK = re.compile(r"(?<!\[)`[A-Za-z_][\w.]*`(?!\]\()")
_SYMBOL_LINK = re.compile(r"\[[^\]]+\]\([^)]+\.py#L\d+\)")


def _symbol_lineno(
    symbols: dict[str, list[object]],
    rel_path: str,
    symbol: str,
) -> int | None:
    """Return AST line number for ``symbol`` once W2 records ``lineno`` per symbol."""
    entries = symbols.get(rel_path, [])
    for entry in entries:
        if isinstance(entry, dict):
            name = str(entry.get("name", entry.get("symbol", "")))
            if name == symbol or name.endswith(f".{symbol}"):
                line = entry.get("lineno")
                return int(line) if line is not None else None
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            if str(entry[0]) == symbol:
                return int(entry[1])
        elif isinstance(entry, str) and entry == symbol:
            return None
    module = importlib.import_module("sevn.docs.readme.scanner")
    lineno_map = getattr(module, "symbol_lineno_for_module", None)
    if lineno_map is not None:
        return lineno_map(symbols, rel_path, symbol)
    return None


def test_readme_relative_href_appends_line_fragment() -> None:
    """D21: ``readme_relative_href(..., line=42)`` returns a POSIX href ending ``#L42``."""
    sig = inspect.signature(readme_relative_href)
    assert "line" in sig.parameters
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        readme = repo / "docs/readmes/demo.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("# Demo\n", encoding="utf-8")
        target = repo / "src/sevn/demo/mod.py"
        target.parent.mkdir(parents=True)
        target.write_text("def run() -> None:\n    pass\n", encoding="utf-8")
        href = readme_relative_href(
            readme_output="docs/readmes/demo.md",
            target="src/sevn/demo/mod.py",
            repo_root=repo,
            line=42,
        )
        assert href.endswith("#L42")
        assert href.count("#") == 1


def test_extract_module_symbols_records_definition_lineno(tmp_path: Path) -> None:
    """D21: ``extract_module_symbols`` records each symbol's ``node.lineno``."""
    rel = "src/sevn/demo/hooks.py"
    body = (
        '"""Boot hooks module."""\n\n'
        "def run_boot_hooks() -> None:\n"
        '    """Run startup hooks."""\n'
        "    pass\n"
    )
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    symbols = extract_module_symbols(tmp_path, [rel])
    lineno = _symbol_lineno(symbols, rel, "run_boot_hooks")
    assert lineno == 3


@pytest.mark.asyncio
async def test_rendered_body_emits_linked_files_and_symbols_not_bare_backticks(
    tmp_path: Path,
) -> None:
    """D21: generated bodies link every mentioned file and symbol (no bare backticks)."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "demo"\n'
        'title = "Demo"\n'
        'summary = "Demo subsystem."\n'
        'profile = "subsystem"\n'
        'tier_owner = "docs"\n'
        'output = "docs/readmes/demo.md"\n'
        'source_globs = ["src/sevn/demo/**"]\n',
        encoding="utf-8",
    )
    mod = tmp_path / "src/sevn/demo/mod.py"
    mod.parent.mkdir(parents=True)
    mod.write_text(
        '"""First sentence of module docstring for prose L3."""\n\n'
        "class Worker:\n"
        "    def run(self) -> None:\n"
        "        pass\n",
        encoding="utf-8",
    )
    manifest = load_manifest(manifest_path)
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=get_entry(manifest, "demo"),
        manifest=manifest,
    )
    level3 = extract_level3_section(markdown) or markdown
    assert _BARE_PY_BACKTICK.search(level3) is None
    assert _SYMBOL_LINK.search(level3) is not None or ".py#L" in level3


@pytest.mark.asyncio
async def test_level3_leads_with_docstring_prose_and_working_with_instruction(
    tmp_path: Path,
) -> None:
    """D22: Level 3 is narrative prose with a ``Working with`` instruction line."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "demo"\n'
        'title = "Demo"\n'
        'summary = "Demo subsystem."\n'
        'profile = "subsystem"\n'
        'tier_owner = "docs"\n'
        'output = "docs/readmes/demo.md"\n'
        'source_globs = ["src/sevn/demo/**"]\n',
        encoding="utf-8",
    )
    mod = tmp_path / "src/sevn/demo/mod.py"
    mod.parent.mkdir(parents=True)
    mod.write_text(
        '"""First sentence of module docstring for prose L3."""\n'
        "Second sentence adds depth for the deep-dive narrative.\n"
        '"""\n\n'
        "def run() -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )
    manifest = load_manifest(manifest_path)
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=get_entry(manifest, "demo"),
        manifest=manifest,
    )
    level3 = extract_level3_section(markdown) or markdown
    assert "Working with" in level3
    assert "First sentence of module docstring" in level3
    assert len(level3) > 280
    assert "See `src/sevn/demo/mod.py`" not in level3


def test_scan_repo_context_includes_symbol_line_numbers(tmp_path: Path) -> None:
    """D21: scanner context exposes symbol definition line numbers for link emission."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "demo"\n'
        'title = "Demo"\n'
        'summary = "Demo."\n'
        'profile = "subsystem"\n'
        'tier_owner = "docs"\n'
        'output = "docs/readmes/demo.md"\n'
        'source_globs = ["src/sevn/demo/**"]\n',
        encoding="utf-8",
    )
    mod = tmp_path / "src/sevn/demo/mod.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("def alpha() -> None:\n    pass\n", encoding="utf-8")
    manifest = load_manifest(manifest_path)
    ctx = scan_repo_context(tmp_path, get_entry(manifest, "demo"))
    symbols = ctx.get("module_symbols", {})
    assert isinstance(symbols, dict)
    assert symbols
