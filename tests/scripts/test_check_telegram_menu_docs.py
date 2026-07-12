"""Telegram Menu.html docs drift gate."""

from __future__ import annotations

from pathlib import Path

from scripts.check_telegram_menu_docs import collect_doc_gaps, scaffold_dev_catalog
from scripts.telegram_menu_catalog import parse_dev_root_tiles
from scripts.telegram_menu_snapshot import LiveButton, LiveSection


def _minimal_dev_html(*, with_logs_tile: bool) -> str:
    root = (
        '      ["session", "📦 Session"], ["logs", "📜 Logs"],\n'
        if with_logs_tile
        else '      ["session", "📦 Session"],\n'
    )
    return f"""<!DOCTYPE html>
<html><body><script>
    const SECTIONS = {{
      session: {{
        title: "Session",
        status: "Ready",
        short: "Session short.",
        long: "Session long.",
        buttons: [
          btn("Regen", "Ready",
            "Toggle regen.",
            "Long regen."),
        ],
      }},
      logs: {{
        title: "Logs",
        status: "WIP",
        short: "Logs short.",
        long: "Logs long.",
        buttons: [
          btn("Tail gateway", "WIP",
            "Tail gateway short.",
            "Tail gateway long."),
        ],
      }},
    }};

    const ROOT_TILES = [
{root}    ];
</script></body></html>
"""


def test_collect_doc_gaps_flags_missing_root_tile(tmp_path: Path) -> None:
    html = tmp_path / "Telegram Menu.html"
    html.write_text(_minimal_dev_html(with_logs_tile=False), encoding="utf-8")
    live = {
        "session": LiveSection("session", "📦 Session", "cfg:section:session", ()),
        "logs": LiveSection(
            "logs",
            "📜 Logs",
            "cfg:section:logs",
            (
                LiveButton(
                    "Tail gateway",
                    "cfg:logs:tail:gateway:0",
                    True,
                ),
            ),
        ),
    }
    hard, _warnings = collect_doc_gaps(html_path=html, live=live)
    kinds = {g.kind for g in hard}
    assert "missing_root_tile" in kinds
    assert any(g.section_id == "logs" for g in hard)


def test_collect_doc_gaps_flags_missing_button(tmp_path: Path) -> None:
    html = tmp_path / "Telegram Menu.html"
    html.write_text(_minimal_dev_html(with_logs_tile=True), encoding="utf-8")
    live = {
        "logs": LiveSection(
            "logs",
            "📜 Logs",
            "cfg:section:logs",
            (
                LiveButton("Tail gateway", "cfg:logs:tail:gateway:0", True),
                LiveButton("Tail proxy", "cfg:logs:tail:proxy:0", True),
            ),
        ),
    }
    hard, _warnings = collect_doc_gaps(html_path=html, live=live)
    assert any(g.kind == "missing_button" and g.section_id == "logs" for g in hard)


def test_scaffold_adds_root_tile_without_clobbering_btn(tmp_path: Path) -> None:
    html = tmp_path / "Telegram Menu.html"
    html.write_text(_minimal_dev_html(with_logs_tile=False), encoding="utf-8")
    live = {
        "session": LiveSection("session", "📦 Session", "cfg:section:session", ()),
        "logs": LiveSection(
            "logs",
            "📜 Logs",
            "cfg:section:logs",
            (
                LiveButton(
                    "Tail gateway",
                    "cfg:logs:tail:gateway:0",
                    True,
                ),
            ),
        ),
    }
    inserted = scaffold_dev_catalog(html_path=html, live=live)
    assert inserted >= 1
    text = html.read_text(encoding="utf-8")
    assert '["logs", "📜 Logs"]' in text
    assert "Tail gateway short." in text
    hard, _warnings = collect_doc_gaps(html_path=html, live=live)
    assert not any(g.kind == "missing_root_tile" for g in hard)


def test_repo_dev_catalog_includes_logs_root_tile() -> None:
    tiles = parse_dev_root_tiles()
    assert any(sid == "logs" for sid, _label in tiles)
