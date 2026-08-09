"""Recorded W0 evidence for Batch A — gating is real.

The recorded ruleset JSON in this directory is the verbatim output of the W0
``gh api repos/sevn-bot/sevn/rulesets/{id}`` capture (see
``ci-architecture-w0-anchor-freeze.md`` §W0.1). Tests under
``tests/infra/test_ci_architecture_gating_w1_red.py`` read these files rather
than calling the live API — **in-repo assertions go in pytest, live-API
assertions go in A-Verify** (plan D4).
"""

from __future__ import annotations

from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
ANCHOR_FREEZE = FIXTURE_DIR / "ci-architecture-w0-anchor-freeze.md"
PREFLIGHT_SHA = FIXTURE_DIR / "ci-architecture-preflight.sha"
RULESET_PROTECT_MAIN = FIXTURE_DIR / "ruleset-protect-main.before.json"
RULESET_REQUIRE_MERGECRAFT = FIXTURE_DIR / "ruleset-require-mergecraft-review.before.json"

__all__ = [
    "ANCHOR_FREEZE",
    "FIXTURE_DIR",
    "PREFLIGHT_SHA",
    "RULESET_PROTECT_MAIN",
    "RULESET_REQUIRE_MERGECRAFT",
]
