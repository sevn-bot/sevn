"""W1.6 — never-regress Ready snapshot (green from W1 onward)."""

from __future__ import annotations

from tests.gateway.telegram_menu_redesign_helpers import (
    collect_live_ready_spec_ids,
    load_baseline_ready_spec_ids,
)


def test_baseline_ready_spec_ids_subset_of_live_ready() -> None:
    """W1.6 / convention §6 — W0 Ready set must remain Ready on every wave."""
    baseline_ready = load_baseline_ready_spec_ids()
    live_ready = collect_live_ready_spec_ids()
    regressed = sorted(baseline_ready - live_ready)
    assert not regressed, f"Ready rows regressed: {regressed}"
