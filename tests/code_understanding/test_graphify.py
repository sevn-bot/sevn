"""Tests for Graphify profile helpers."""

from __future__ import annotations

from pathlib import Path

from sevn.code_understanding.graphify import (
    active_profiles_with_report,
    graph_json_path,
    graph_report_path,
    profile_covers,
    resolve_profiles,
    search_tool_prefix,
)
from sevn.code_understanding.models import GraphifyProfile, GraphifySettings


def test_resolve_profiles_disabled_returns_empty(tmp_path: Path) -> None:
    assert resolve_profiles(GraphifySettings(enabled=False), tmp_path) == []


def test_resolve_profiles_bootstrap_when_enabled_and_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sevn.code_understanding.graphify.try_resolve_sevn_repo_root",
        lambda _hint: None,
    )
    profiles = resolve_profiles(GraphifySettings(enabled=True), tmp_path)
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.id == "default"
    assert profile.root_path == str(tmp_path.resolve())
    assert profile.output_dir.endswith(".index/graphify")


def test_resolve_profiles_bootstrap_sevn_when_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "sevn.bot"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "sevn"\n', encoding="utf-8")
    profiles = resolve_profiles(GraphifySettings(enabled=True), repo)
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.id == "sevn"
    assert profile.root_path == str(repo.resolve())
    assert profile.output_dir.endswith(".index/graphify")


def test_resolve_profiles_explicit_passthrough(tmp_path: Path) -> None:
    settings = GraphifySettings(
        enabled=True,
        profiles=[GraphifyProfile(id="x", root_path="/r", output_dir="/o")],
    )
    profiles = resolve_profiles(settings, tmp_path)
    assert len(profiles) == 1
    assert profiles[0].id == "x"


def test_profile_covers_under_root(tmp_path: Path) -> None:
    inside = tmp_path / "sub" / "file.py"
    inside.parent.mkdir()
    inside.write_text("x", encoding="utf-8")
    profile = GraphifyProfile(
        id="d",
        root_path=str(tmp_path),
        output_dir=str(tmp_path / "out"),
    )
    assert profile_covers(profile, inside) is True


def test_profile_covers_outside_root(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    profile = GraphifyProfile(
        id="d",
        root_path=str(tmp_path / "root"),
        output_dir=str(tmp_path / "out"),
    )
    (tmp_path / "root").mkdir()
    assert profile_covers(profile, other) is False


def test_search_tool_prefix_matches_spec_2_5() -> None:
    profile = GraphifyProfile(id="alpha", root_path="/r", output_dir="/out/dir")
    text = search_tool_prefix(profile)
    expected = (
        "Graphify profile alpha: knowledge graph present. "
        "Read /out/dir/GRAPH_REPORT.md for god nodes and community structure "
        "before expanding raw search."
    )
    assert text == expected


def test_graph_report_and_json_paths() -> None:
    profile = GraphifyProfile(id="d", root_path="/r", output_dir="/o")
    assert graph_report_path(profile) == Path("/o/GRAPH_REPORT.md")
    assert graph_json_path(profile) == Path("/o/graph.json")


def test_active_profiles_with_report_filters(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    out_a.mkdir()
    out_b.mkdir()
    (out_a / "GRAPH_REPORT.md").write_text("# report\n", encoding="utf-8")

    profile_a = GraphifyProfile(id="a", root_path=str(tmp_path), output_dir=str(out_a))
    profile_b = GraphifyProfile(id="b", root_path=str(tmp_path), output_dir=str(out_b))

    active = active_profiles_with_report([profile_a, profile_b])
    ids = [p.id for p in active]
    assert ids == ["a"]
