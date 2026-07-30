"""CI tier ↔ ``CI_STEPS`` parity (#61 / D18 — green after W2)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

_TIER_ORDER = ("ci-core", "ci-infra", "ci-docs", "ci-skills", "ci-parity")


def _makefile_text() -> str:
    return (REPO / "Makefile").read_text(encoding="utf-8")


def _tier_prerequisites(makefile: str, tier: str) -> list[str]:
    match = re.search(rf"^{tier}:\s*(.+)$", makefile, re.MULTILINE)
    assert match is not None, f"missing Makefile tier {tier!r}"
    return match.group(1).split()


def _flattened_tier_steps(makefile: str) -> list[str]:
    steps: list[str] = []
    for tier in _TIER_ORDER:
        steps.extend(_tier_prerequisites(makefile, tier))
    return steps


def _ci_steps_from_makefile(makefile: str) -> list[str]:
    match = re.search(
        r"^CI_STEPS :=\s*(.+?)(?:\n(?![ \t])|\Z)",
        makefile,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "CI_STEPS variable missing from Makefile"
    raw = re.sub(r"\\\n\s*", " ", match.group(1))
    return raw.split()


def _make_ci_steps() -> list[str]:
    proc = subprocess.run(
        ["make", "-s", "ci-steps"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip().split()


@pytest.mark.xfail(reason="green after W2: CI_STEPS matches flattened tiers", strict=False)
def test_ci_steps_matches_flattened_tier_prerequisites() -> None:
    """W1.1: ``make ci-steps`` must equal flattened ci-* tier lists from the Makefile."""
    makefile = _makefile_text()
    expected = _flattened_tier_steps(makefile)
    actual = _make_ci_steps()
    assert actual == expected


@pytest.mark.xfail(reason="green after W2: mergecraft-ref-check in CI_STEPS", strict=False)
def test_mergecraft_ref_check_reachable_from_ci_resume() -> None:
    """W1.2: pin gate must appear in ``CI_STEPS`` so ``ci-resume`` cannot skip it."""
    makefile = _makefile_text()
    ci_steps = _ci_steps_from_makefile(makefile)
    assert "mergecraft-ref-check" in ci_steps
    assert "mergecraft-ref-check" in _make_ci_steps()
