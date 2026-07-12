"""User help site build (`about-sevn.bot/`)."""

from __future__ import annotations

from pathlib import Path

from scripts.build_about_site import USER_PAGES, build_site, check_purity


def test_user_pages_exist_after_build(tmp_path: Path) -> None:
    out = tmp_path / "site"
    build_site(out)
    for rel in USER_PAGES:
        assert (out / rel).is_file()


def test_purity_rejects_spec_marker(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text("<p>see specs/17-gateway.md</p>", encoding="utf-8")
    for rel in USER_PAGES[1:]:
        (root / rel).write_text("<p>ok</p>", encoding="utf-8")
    assert any("forbidden" in v for v in check_purity(root))


def test_purity_allows_standards_markdown(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    for rel in USER_PAGES:
        (root / rel).write_text("<p>hello</p>", encoding="utf-8")
    standards = root / "_standards"
    standards.mkdir(parents=True)
    (standards / "NOTE.md").write_text("# ok", encoding="utf-8")
    assert check_purity(root) == []
