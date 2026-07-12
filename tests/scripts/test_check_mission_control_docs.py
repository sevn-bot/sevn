"""Mission Control.html docs drift gate."""

from __future__ import annotations

from pathlib import Path

from scripts.check_mission_control_docs import collect_doc_gaps, scaffold_dev_catalog
from scripts.mission_control_catalog import parse_dev_group_nav
from scripts.mission_control_snapshot import LiveGroup, LiveTab


def _minimal_dev_html(*, with_ops_group: bool) -> str:
    ops_block = (
        """
      ops: {
        title: "Ops",
        status: "WIP",
        short: "Ops short.",
        long: "Ops long.",
        tabs: [
          TAB("Cron", "Ready",
            "Cron short.",
            "Cron long."),
        ],
      },"""
        if with_ops_group
        else ""
    )
    nav_ops = '\n      ["ops", "Ops"],' if with_ops_group else ""
    return f"""<!DOCTYPE html>
<html><body><script>
    const GROUPS = {{
      core: {{
        title: "Core",
        status: "Ready",
        short: "Core short.",
        long: "Core long.",
        tabs: [
          TAB("Overview", "Ready",
            "Overview short.",
            "Overview long."),
        ],
      }},{ops_block}
    }};

    const GROUP_NAV = [
      ["core", "Core"],{nav_ops}
    ];
</script></body></html>
"""


def test_collect_doc_gaps_flags_missing_group_nav(tmp_path: Path) -> None:
    html = tmp_path / "Mission Control.html"
    html.write_text(_minimal_dev_html(with_ops_group=False), encoding="utf-8")
    live = {
        "core": LiveGroup("core", "Core", (LiveTab("overview", "Overview", "wired"),)),
        "ops": LiveGroup("ops", "Ops", (LiveTab("cron", "Cron", "wired"),)),
    }
    hard, _warnings = collect_doc_gaps(html_path=html, live=live)
    kinds = {g.kind for g in hard}
    assert "missing_group_nav" in kinds
    assert any(g.group_id == "ops" for g in hard)


def test_collect_doc_gaps_flags_missing_tab(tmp_path: Path) -> None:
    html = tmp_path / "Mission Control.html"
    html.write_text(_minimal_dev_html(with_ops_group=True), encoding="utf-8")
    live = {
        "ops": LiveGroup(
            "ops",
            "Ops",
            (
                LiveTab("cron", "Cron", "wired"),
                LiveTab("security", "Security", "wired"),
            ),
        ),
    }
    hard, _warnings = collect_doc_gaps(html_path=html, live=live)
    assert any(g.kind == "missing_tab" and g.group_id == "ops" for g in hard)


def test_scaffold_adds_group_nav_without_clobbering_tab(tmp_path: Path) -> None:
    html = tmp_path / "Mission Control.html"
    html.write_text(_minimal_dev_html(with_ops_group=False), encoding="utf-8")
    live = {
        "core": LiveGroup("core", "Core", (LiveTab("overview", "Overview", "wired"),)),
        "ops": LiveGroup("ops", "Ops", (LiveTab("cron", "Cron", "wired"),)),
    }
    inserted = scaffold_dev_catalog(html_path=html, live=live)
    assert inserted >= 1
    text = html.read_text(encoding="utf-8")
    assert '["ops", "Ops"]' in text
    assert "ops:" in text
    assert 'TAB("Cron"' in text
    hard, _warnings = collect_doc_gaps(html_path=html, live=live)
    assert not hard


def test_repo_dev_catalog_includes_self_improve_group() -> None:
    nav = parse_dev_group_nav()
    assert any(gid == "self-improve" for gid, _label in nav)
