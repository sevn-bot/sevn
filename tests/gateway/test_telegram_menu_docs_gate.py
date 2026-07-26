"""W1 RED: docs gate lifecycle hook (green after W9)."""

from __future__ import annotations

import pytest
from scripts.check_telegram_menu_docs import build_docs_gap_report
from scripts.telegram_menu_catalog import DEV_TELEGRAM_HTML, parse_dev_root_tiles


@pytest.mark.xfail(
    reason="green after W9: docs gate green on redesigned eight-tile tree", strict=False
)
def test_docs_gate_report_green_with_eight_root_tiles() -> None:
    """W1.14 — gate report shape + zero violations once catalog matches redesign."""
    report = build_docs_gap_report()
    assert "violations" in report
    assert "warnings" in report
    assert "hard_violation_count" in report
    assert report["hard_violation_count"] == 0
    root_tiles = parse_dev_root_tiles(DEV_TELEGRAM_HTML)
    assert len(root_tiles) == 8
