"""Tests for README source_glob → slug mapping."""

from __future__ import annotations

from sevn.docs.readme.fingerprint import path_matches_source_glob, slugs_for_changed_paths
from sevn.docs.readme.manifest import ReadmeEntry


def _entry(slug: str, *globs: str) -> ReadmeEntry:
    return ReadmeEntry(
        slug=slug,
        title=slug,
        summary="summary",
        profile="freeform",
        tier_owner="docs",
        output=f"docs/readmes/{slug}.md",
        source_globs=globs,
        specs=(),
    )


def test_path_matches_tree_glob() -> None:
    assert path_matches_source_glob("src/sevn/gateway/x.py", "src/sevn/gateway/**")
    assert not path_matches_source_glob("src/sevn/channels/x.py", "src/sevn/gateway/**")


def test_path_matches_exact_file() -> None:
    assert path_matches_source_glob("infra/sevn.schema.json", "infra/sevn.schema.json")
    assert not path_matches_source_glob("infra/other.json", "infra/sevn.schema.json")


def test_slugs_for_changed_paths_returns_sorted_unique() -> None:
    entries = (
        _entry("gateway", "src/sevn/gateway/**"),
        _entry("channels", "src/sevn/channels/**"),
        _entry("config-workspace", "infra/sevn.schema.json"),
    )
    slugs = slugs_for_changed_paths(
        __import__("pathlib").Path("."),
        entries=entries,
        changed_paths=[
            "src/sevn/gateway/http_server.py",
            "infra/sevn.schema.json",
        ],
    )
    assert slugs == ("config-workspace", "gateway")
