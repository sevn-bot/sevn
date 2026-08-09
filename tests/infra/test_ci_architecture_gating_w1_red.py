"""RED suite - Batch A "Gating is real" (CI architecture wave plan).

Source contracts (plan Contract inventory, A1.1-A1.5):
- A1.1 - Trunk branches (``pre-0.0.1``, ``test-pre``, ``pre-*``) carry
  ``deletion`` + ``non_fast_forward`` protection.
- A1.3 - CI checks are required on trunk + ``main`` with
  ``strict_required_status_checks_policy: true``.
- A1.5 - ``CODEOWNERS`` exists on the default branch (so
  ``protect-main``'s code-owner rule is no longer a no-op).

Source of truth:
- ``about-sevn.bot/specs/25-cicd-full.md`` (required-check contract).
- W0 anchor freeze: ``tests/infra/fixtures/ci_architecture_batch_a/ci-architecture-w0-anchor-freeze.md``.
- W0 ruleset JSON (verbatim ``gh api`` capture): the ``*.before.json``
  fixtures next to this file.

Per plan **D4**, in-repo assertions go in pytest, live-API assertions go
in the A-Verify gate. These tests therefore read the recorded W0 fixture
via ``git show origin/main:.github/CODEOWNERS`` and the ruleset JSON
fixtures, **not** the live GitHub API.

Implementation waves (W2, W3) are the only ones allowed to remove the
``xfail`` markers — never an implementation agent; the test-creator
reconciles per the wave plan.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from tests.infra.fixtures.ci_architecture_batch_a import (
    ANCHOR_FREEZE,
    RULESET_PROTECT_MAIN,
    RULESET_REQUIRE_MERGECRAFT,
)

REPO = Path(__file__).resolve().parents[2]
CODEOWNERS_PATH = ".github/CODEOWNERS"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _load_ruleset(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _required_status_checks(ruleset: dict) -> list[dict]:
    checks: list[dict] = []
    for rule in ruleset.get("rules", []):
        if rule.get("type") == "required_status_checks":
            params = rule.get("parameters", {}) or {}
            checks.extend(params.get("required_status_checks", []) or [])
    return checks


def _rule_types(ruleset: dict) -> set[str]:
    return {rule.get("type") for rule in ruleset.get("rules", [])}


def _rule(ruleset: dict, rule_type: str) -> dict | None:
    for rule in ruleset.get("rules", []):
        if rule.get("type") == rule_type:
            return rule
    return None


def _include_patterns(ruleset: dict) -> list[str]:
    return ruleset.get("conditions", {}).get("ref_name", {}).get("include", [])


# ---------------------------------------------------------------------------
# W1.1 — CODEOWNERS exists on origin/main (A1.5, xfail → W3)
# ---------------------------------------------------------------------------


def _codeowners_blob_via_git_show() -> str | None:
    """Read ``.github/CODEOWNERS`` from ``origin/main`` via the same pattern
    ``scripts/check_mergecraft_ref_parity.py`` uses for a ref-side file
    (subprocess ``git show`` so a missing blob is a clean 128, not a
    Python exception swallowed in a fixture loader).
    """
    proc = subprocess.run(
        ["git", "show", f"origin/main:{CODEOWNERS_PATH}"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


@pytest.mark.xfail(
    reason=(
        "W1.1 — green after W3 (A1.5): W3.1 puts .github/CODEOWNERS on the "
        "default branch via the Contents API. Until that lands, "
        "`git show origin/main:.github/CODEOWNERS` exits 128 (fatal: "
        "invalid object). Today the file is read from the trunk only, so "
        "`protect-main`'s `require_code_owner_review` is vacuously satisfied."
    ),
    strict=False,
)
def test_codeowners_exists_on_origin_main() -> None:
    """``.github/CODEOWNERS`` must resolve on the default branch.

    The plan's W1.1 deliverable: same ``git show origin/main:...`` pattern
    ``scripts/check_mergecraft_ref_parity.py`` uses for a ref-side file.
    """
    blob = _codeowners_blob_via_git_show()
    assert blob is not None, (
        f"`{CODEOWNERS_PATH}` is absent on origin/main — see "
        ".ignorelocal/waves/ci-architecture-w0-anchor-freeze.md §W0.4 (404 "
        "on contents API). A1.5 closes when W3.1 lands."
    )
    assert blob.strip(), "CODEOWNERS on origin/main is empty"
    # Spot-check the on-disk trunk version so a delete-and-paste is
    # caught: at least one non-comment owner line must be present.
    assert re.search(r"^\S+\s+\S+", blob, re.MULTILINE), (
        "CODEOWNERS on origin/main has no owner pattern; the file must list "
        "at least one owner before `protect-main`'s code-owner rule stops "
        "being a no-op."
    )


# ---------------------------------------------------------------------------
# W1.2 — Recorded fixture: required status checks on the trunk (A1.3, xfail → W2)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "W1.2 — green after W2 (A1.3): the recorded W0 fixture shows the "
        "trunk has `required_status_checks: [mergecraft review]` only and "
        "`strict_required_status_checks_policy: false`. W2.3 adds the CI "
        "checks with `strict: true` and re-records the after-JSON."
    ),
    strict=False,
)
def test_required_status_checks_present_and_strict_on_trunk() -> None:
    """The W0-recorded ``require-mergecraft-review`` fixture must declare
    required status checks with ``strict_required_status_checks_policy: true``
    on every protected trunk ref.

    Per D4, this is a **fixture** assertion (the live read belongs to
    A-Verify). Once W2 records the after-JSON, the same test is the gate.
    """
    ruleset = _load_ruleset(RULESET_REQUIRE_MERGECRAFT)

    rsc_rule = _rule(ruleset, "required_status_checks")
    assert rsc_rule is not None, (
        "required_status_checks rule missing from "
        "require-mergecraft-review — A1.3 demands it on the trunk."
    )
    params = rsc_rule.get("parameters", {}) or {}
    assert params.get("strict_required_status_checks_policy") is True, (
        "strict_required_status_checks_policy must be true so a stale-base "
        "PR cannot merge without a fresh run (audit §4.1 finding)."
    )
    contexts = [
        check["context"]
        for check in params.get("required_status_checks", [])
        if isinstance(check, dict) and "context" in check
    ]
    # W2's interim set is documented in D9 first-swap. We assert the
    # shape, not the verbatim list — the after-record lands by W2.5.
    expected_minimum = {
        "Verify (static + build)",
        "Verify (drift gates)",
        "Verify (security audit)",
        "Verify (tests 1/4)",
        "Verify (tests 4/4)",
        "Analyze (python)",
    }
    missing = expected_minimum - set(contexts)
    assert not missing, "trunk required_status_checks missing contexts: " + ", ".join(
        sorted(missing)
    )
    # ``mergecraft review`` must still be required (W1.4 guard test below
    # also asserts this — repeated here so W1.2 fails for a clear reason).
    assert "mergecraft review" in contexts, (
        "Batch A adds gates; it must never drop the mergecraft review gate."
    )


@pytest.mark.xfail(
    reason=(
        "W1.2 — green after W2 (A1.3): the recorded fixture's `main` ruleset "
        "(`protect-main`) currently has **no** `required_status_checks` rule "
        "at all (W0.1 verbatim). W2.3 adds a status-check rule on `main` so "
        "the fork hole is closed (A1.4)."
    ),
    strict=False,
)
def test_required_status_checks_present_on_main_ruleset() -> None:
    """``protect-main`` must also gain a required-status-checks rule.

    The non-secret gates (ci.yml, codeql.yml, docker.yml) are the only ones
    that run on fork PRs; without this rule the fork hole is open (audit §4.3).
    """
    ruleset = _load_ruleset(RULESET_PROTECT_MAIN)
    rsc_rule = _rule(ruleset, "required_status_checks")
    assert rsc_rule is not None, (
        "protect-main has no required_status_checks rule — A1.4 requires "
        "the non-secret gates (ci/codeql/docker) on `main` so a fork PR "
        "with zero review is blocked."
    )
    params = rsc_rule.get("parameters", {}) or {}
    assert params.get("strict_required_status_checks_policy") is True
    contexts = {
        check["context"]
        for check in params.get("required_status_checks", [])
        if isinstance(check, dict) and "context" in check
    }
    # A1.4 demands the non-secret gates; this is the gate the fork path
    # actually runs.
    expected = {"Verify (static + build)", "Analyze (python)"}
    assert expected.issubset(contexts), (
        f"protect-main must require the fork-runnable checks {expected}; got {sorted(contexts)}."
    )


# ---------------------------------------------------------------------------
# W1.3 — Recorded fixture: trunk `deletion` + `non_fast_forward` (A1.1, xfail → W2)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "W1.3 — green after W2 (A1.1): the W0 fixture shows the existing "
        "`protect-main` only targets `~DEFAULT_BRANCH` (i.e. `main`) — the "
        "trunk branches `pre-0.0.1`, `test-pre`, and `pre-*` are unprotected. "
        "W2.2 adds a `protect-trunk` ruleset with `deletion` + "
        "`non_fast_forward` on those refs."
    ),
    strict=False,
)
def test_protect_trunk_ruleset_covers_pre_branches() -> None:
    """A new ``protect-trunk`` ruleset (A1.1) must protect the trunk branches.

    Implementation contract (W2.2): a ruleset that targets
    ``refs/heads/pre-0.0.1``, ``refs/heads/test-pre``, ``refs/heads/pre-*``
    and declares ``deletion`` + ``non_fast_forward``. Until W2 lands, the
    only ``branch``-targeted ruleset is ``protect-main``, which targets
    ``~DEFAULT_BRANCH`` only.
    """
    # Walk every ruleset fixture in this directory; a protect-trunk fixture
    # is the W2 after-record. Until it is added, the only branch ruleset is
    # protect-main and its include list is exactly [~DEFAULT_BRANCH].
    rulesets = sorted(REPO.glob("tests/infra/fixtures/ci_architecture_batch_a/ruleset-*.json"))
    assert rulesets, "no ruleset fixtures present — W0 evidence missing"

    trunk_patterns = {
        "refs/heads/pre-0.0.1",
        "refs/heads/test-pre",
        "refs/heads/pre-*",
    }
    protected: set[str] = set()
    for path in rulesets:
        ruleset = _load_ruleset(path)
        if ruleset.get("target") != "branch":
            continue
        if ruleset.get("name") == "protect-trunk":
            # The post-W2 fixture must declare both rules and the trunk
            # ref patterns. The test stays RED until W2 records it.
            types = _rule_types(ruleset)
            assert {"deletion", "non_fast_forward"}.issubset(types), (
                "protect-trunk must declare deletion and non_fast_forward "
                f"rules; got {sorted(types)}."
            )
            assert trunk_patterns.issubset(set(_include_patterns(ruleset))), (
                f"protect-trunk must include {sorted(trunk_patterns)}; got "
                f"{_include_patterns(ruleset)}."
            )
            protected |= trunk_patterns
        else:
            # Any pre-existing branch ruleset contributes its includes to
            # the protected set. protect-main today only includes
            # ~DEFAULT_BRANCH.
            protected |= set(_include_patterns(ruleset))

    missing = trunk_patterns - protected
    assert not missing, "trunk branches missing deletion+non_fast_forward protection: " + ", ".join(
        sorted(missing)
    )


# ---------------------------------------------------------------------------
# W1.4 — Guard test: mergecraft review must remain required.
# ---------------------------------------------------------------------------


def test_mergecraft_review_remain_required_in_before_fixture() -> None:
    """W1.4 guard test: this batch adds gates; it never drops the review gate.

    A negative test against the **before** fixture. This test must stay
    green throughout the batch — if anyone weakens the ruleset, it fails
    immediately. The companion positive assertion is the W2
    after-fixture check; this one is the regression anchor.
    """
    ruleset = _load_ruleset(RULESET_REQUIRE_MERGECRAFT)
    contexts = [check.get("context") for check in _required_status_checks(ruleset)]
    assert "mergecraft review" in contexts, (
        "W1.4 guard: 'mergecraft review' was removed from "
        "require-mergecraft-review. Batch A only adds gates; removing the "
        "review gate is a regression and the test is intentionally not "
        "xfailed so the suite fails closed."
    )


def test_anchor_freeze_records_required_w0_findings() -> None:
    """The W0 freeze must reference the live-state findings this batch
    depends on. Without it, future waves cannot tell what "before" means.
    """
    text = ANCHOR_FREEZE.read_text(encoding="utf-8")
    must_contain = [
        "W0.1",
        "W0.2",
        "W0.3",
        "W0.4",
        "W0.5",
        "W0.6",
        "W0.7",
        # The exact before ruleset ids and names.
        "18631367",
        "19238611",
        "protect-main",
        "require-mergecraft-review",
        # The bypass and code-owner facts that drive A1.2 / A1.5.
        "bypass_actors",
        "actor_id",
        "require_code_owner_review",
    ]
    missing = [token for token in must_contain if token not in text]
    assert not missing, "W0 anchor freeze is missing required tokens: " + ", ".join(missing)
