"""Tests for Level 3 path and symbol reference checks."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sevn.docs.readme.check import check_readme_tree
from sevn.docs.readme.fingerprint import (
    compute_digest,
    load_fingerprints,
    save_fingerprints,
    upsert_entry,
)
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest
from sevn.docs.readme.symbol_refs import (
    extract_level3_section,
    function_defined_in_file,
    symbol_defined_in_file,
    validate_path_refs,
    validate_symbol_refs,
)


def test_extract_level3_section() -> None:
    text = "## Level 1 — Overview\n\n## Level 3 — Deep dive\n\nBody\n\n## References\n"
    assert "Body" in extract_level3_section(text)


def test_validate_path_refs_ok() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        py = repo / "src/sevn/demo/a.py"
        py.parent.mkdir(parents=True)
        py.write_text("x = 1\n", encoding="utf-8")
        assert not validate_path_refs("See `src/sevn/demo/a.py`.", repo)


def test_validate_path_refs_missing() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        assert validate_path_refs("See `src/sevn/missing/a.py`.", repo)


def test_validate_symbol_refs_ok() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        py = repo / "src/sevn/demo/a.py"
        py.parent.mkdir(parents=True)
        py.write_text("class Foo:\n    def bar(self): pass\n", encoding="utf-8")
        text = "In `src/sevn/demo/a.py`, entry point `Foo.bar`."
        assert not validate_symbol_refs(text, repo)


def test_symbol_defined_in_file_nested_class_method() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "m.py"
        path.write_text(
            "class Foo:\n    class Bar:\n        def baz(self): pass\n",
            encoding="utf-8",
        )
        assert symbol_defined_in_file(path, "Foo.Bar.baz")
        assert not symbol_defined_in_file(path, "Foo.Bar.missing")


def test_validate_symbol_refs_flags_bare_function_drift() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        py = repo / "src/sevn/gateway/channel_router.py"
        py.parent.mkdir(parents=True)
        py.write_text(
            "class ChannelRouter:\n    async def route_incoming(self) -> None: pass\n",
            encoding="utf-8",
        )
        l2 = "In `src/sevn/gateway/channel_router.py`, inbound messages reach `route_inbound`.\n"
        errors = validate_symbol_refs(l2, repo)
        assert any("route_inbound" in err for err in errors)


def test_function_defined_in_file_top_level() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "m.py"
        path.write_text("def run(): pass\n", encoding="utf-8")
        assert function_defined_in_file(path, "run")
        assert not function_defined_in_file(path, "missing")


def test_validate_symbol_refs_ignores_file_like_backticks() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        py = repo / "src/sevn/channels/markdown_safe.py"
        py.parent.mkdir(parents=True)
        py.write_text('"""Escape (`PROBLEMS.md` §9)."""\n', encoding="utf-8")
        text = "- `src/sevn/channels/markdown_safe.py` — (`PROBLEMS.md` §9)."
        assert not validate_symbol_refs(text, repo)


def _gateway_router_fixture(repo: Path) -> None:
    router = repo / "src/sevn/gateway/channel_router.py"
    router.parent.mkdir(parents=True)
    router.write_text(
        "class ChannelRouter:\n"
        "    async def route_incoming(self, msg: object) -> None:\n"
        "        pass\n",
        encoding="utf-8",
    )


def _curated_l2_body(*, symbol: str) -> str:
    return (
        "> **Summary.** Gateway summary.\n\n"
        "## Level 1 — Overview (non-technical)\n\nOverview.\n\n"
        "## Level 2 — How it works (technical)\n\n"
        f"Inbound messages reach `ChannelRouter.{symbol}`.\n\n"
        "## Level 3 — Deep dive (low-level, technical)\n\n"
        "Deep dive body.\n\n"
        "## References\n"
    )


def test_check_readme_tree_flags_curated_l2_route_inbound_drift() -> None:
    """D9: ``make readme-check`` flags ``route_inbound`` cited in curated Level 2."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_dir = repo / "docs/readmes"
        manifest_dir.mkdir(parents=True)
        _gateway_router_fixture(repo)
        entry = ReadmeEntry(
            slug="gateway",
            title="Gateway",
            summary="Gateway summary.",
            profile="subsystem",
            tier_owner="gateway",
            output="docs/readmes/gateway.md",
            source_globs=("src/sevn/gateway/**",),
            specs=(),
            curated=True,
            template="docs/readmes/_templates/gateway.md",
        )
        manifest = ReadmeManifest(version=1, entries=(entry,))
        manifest_dir.joinpath("gateway.md").write_text(
            _curated_l2_body(symbol="route_inbound"),
            encoding="utf-8",
        )
        fp_path = manifest_dir / "_fingerprints.json"
        store = load_fingerprints(fp_path)
        upsert_entry(
            store,
            slug="gateway",
            digest=compute_digest(repo, entry.source_globs),
            source_globs=entry.source_globs,
        )
        save_fingerprints(fp_path, store)
        result = check_readme_tree(repo, manifest)
        assert not result.ok
        assert any("route_inbound" in err for err in result.errors)


def test_validate_symbol_refs_accepts_l2_present_symbol_direct_call() -> None:
    """D9 baseline: direct L2 scan accepts ``route_incoming`` when defined in source."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _gateway_router_fixture(repo)
        l2 = (
            "## Level 2 — How it works (technical)\n\n"
            "In `src/sevn/gateway/channel_router.py`, inbound messages reach "
            "`ChannelRouter.route_incoming`.\n"
        )
        assert not validate_symbol_refs(l2, repo)
