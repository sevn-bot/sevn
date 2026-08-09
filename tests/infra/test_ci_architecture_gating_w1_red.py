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
    RULESET_REQUIRE_MERGECRAFT,
)

REPO = Path(__file__).resolve().parents[2]
CODEOWNERS_PATH = ".github/CODEOWNERS"

# W2 reconcile: read the *after* JSON recorded by the W2 executor
# (ruleset state after D8 — Admin bypass removed, required status checks
# added with strict: true, protect-trunk created). W1.2/W1.3 consult these
# paths; W1.4 keeps reading the before-fixture (the mergecraft review
# regression anchor is independent of W2's W2.3 swap).
RULESET_PROTECT_MAIN_AFTER = (
    REPO / "tests/infra/fixtures/ci_architecture_batch_a/ruleset-protect-main.after.json"
)
RULESET_REQUIRE_MERGECRAFT_AFTER = (
    REPO
    / "tests/infra/fixtures/ci_architecture_batch_a/ruleset-require-mergecraft-review.after.json"
)


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
# W1.2 — Recorded fixture: required status checks on the trunk (A1.3)
# ---------------------------------------------------------------------------


def test_required_status_checks_present_and_strict_on_trunk() -> None:
    """W2 after-record: ``require-mergecraft-review`` must declare the
    full set of required status checks with ``strict_required_status_checks_policy: true``
    on every protected trunk ref.

    Per D4, this is a **fixture** assertion (the live read belongs to
    A-Verify). The W2 executor recorded the after-JSON
    (``ruleset-require-mergecraft-review.after.json``); this test is the
    gate that proves the recorded state matches the W2 contract.
    """
    ruleset = _load_ruleset(RULESET_REQUIRE_MERGECRAFT_AFTER)

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
    # D9 first-swap interim set — same eight names as protect-main,
    # plus ``mergecraft review`` which is what this ruleset was originally
    # created for. The full eight CI names plus mergecraft review is the
    # W2 contract; assert the set, not the order.
    expected_minimum = {
        "mergecraft review",
        "Verify (static + build)",
        "Verify (drift gates)",
        "Verify (security audit)",
        "Verify (tests 1/4)",
        "Verify (tests 2/4)",
        "Verify (tests 3/4)",
        "Verify (tests 4/4)",
        "Analyze (python)",
    }
    missing = expected_minimum - set(contexts)
    assert not missing, "trunk required_status_checks missing contexts: " + ", ".join(
        sorted(missing)
    )
    # D8 outcome: the Admin bypass is removed. A test that breaks when
    # the bypass is re-added (audit-escape-patterns rubric: a guard test
    # must fail when the guard is deleted). The before-fixture's
    # ``bypass_actors`` is intentionally NOT consulted here — that
    # belongs to the bypass-decision gate below; this test pins the
    # *after* state only.
    assert "mergecraft review" in contexts, (
        "Batch A adds gates; it must never drop the mergecraft review gate."
    )


def test_admin_bypass_removed_from_status_check_ruleset() -> None:
    """D8 outcome guard: the Admin bypass (``bypass_actors`` with
    ``actor_id: 5, RepositoryRole: admin, bypass_mode: always``) must be
    removed from ``require-mergecraft-review`` in the after-fixture.

    This is the contract from W2.1's chosen shape (a) Gated. A test
    that breaks if anyone re-adds the bypass — without this guard, the
    status-check rule is decorative for the only person who merges.
    """
    ruleset = _load_ruleset(RULESET_REQUIRE_MERGECRAFT_AFTER)
    bypass_actors = ruleset.get("bypass_actors", [])
    # Empty list, OR a list that does not contain the Admin RepositoryRole
    # bypass — both satisfy D8 (the GitHub shape writes an empty list
    # when Admin is removed).
    admin_bypass = [
        actor
        for actor in bypass_actors
        if actor.get("actor_type") == "RepositoryRole"
        and actor.get("actor_id") == 5
        and actor.get("bypass_mode") == "always"
    ]
    assert not admin_bypass, (
        "Admin bypass (actor_id: 5, RepositoryRole: admin, "
        "bypass_mode: always) is still present in "
        "require-mergecraft-review — D8 (a) Gated must hold: removing "
        "the bypass is what makes required checks block the operator."
    )
    assert ruleset.get("current_user_can_bypass") != "always", (
        "current_user_can_bypass must not be 'always' on the gated "
        "ruleset — D8 outcome (a) requires Admin to be removed."
    )


def test_required_status_checks_present_on_main_ruleset() -> None:
    """W2 after-record: ``protect-main`` must declare a required-status-checks
    rule on the default branch.

    The non-secret gates (ci.yml, codeql.yml, docker.yml) are the only ones
    that run on fork PRs; without this rule the fork hole is open (audit §4.3).
    The W2 executor recorded the after-JSON
    (``ruleset-protect-main.after.json``) which now contains the
    ``required_status_checks`` rule with the eight CI contexts.
    """
    ruleset = _load_ruleset(RULESET_PROTECT_MAIN_AFTER)
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
    # A1.4 demands the non-secret gates. The W2 after-record is the full
    # eight-context set; assert every name is present, then specifically
    # re-assert the two fork-runnable names so the failure message stays
    # focused on the fork-hole invariant if anyone drops one.
    expected_eight = {
        "Verify (static + build)",
        "Verify (drift gates)",
        "Verify (security audit)",
        "Verify (tests 1/4)",
        "Verify (tests 2/4)",
        "Verify (tests 3/4)",
        "Verify (tests 4/4)",
        "Analyze (python)",
    }
    missing = expected_eight - contexts
    assert not missing, (
        f"protect-main must require the eight CI contexts after W2.3; "
        f"missing: {sorted(missing)}; got: {sorted(contexts)}."
    )
    # A1.4 invariant — explicitly: the fork-runnable checks must be a
    # subset. If the message is hard to read on regression, this is the
    # single most important line.
    fork_runnable = {"Verify (static + build)", "Analyze (python)"}
    assert fork_runnable.issubset(contexts), (
        f"protect-main must require the fork-runnable checks {fork_runnable}; "
        f"got {sorted(contexts)}."
    )


# ---------------------------------------------------------------------------
# W1.3 — Recorded fixture: trunk `deletion` + `non_fast_forward` (A1.1)
# ---------------------------------------------------------------------------


def test_protect_trunk_ruleset_covers_pre_branches() -> None:
    """W2 after-record: a ``protect-trunk`` ruleset (A1.1) must protect the trunk branches.

    Implementation contract (W2.2): a ruleset that targets
    ``refs/heads/pre-0.0.1``, ``refs/heads/test-pre``, ``refs/heads/pre-*``
    and declares ``deletion`` + ``non_fast_forward``. The W2 executor
    recorded the after-JSON
    (``ruleset-protect-trunk.after.json``); this test is the gate that
    proves the recorded state matches the W2 contract.
    """
    # Walk every ruleset fixture in this directory. A protect-trunk fixture
    # is the W2 after-record; it must be present after W2.
    rulesets = sorted(REPO.glob("tests/infra/fixtures/ci_architecture_batch_a/ruleset-*.json"))
    assert rulesets, "no ruleset fixtures present — W0 evidence missing"

    trunk_patterns = {
        "refs/heads/pre-0.0.1",
        "refs/heads/test-pre",
        "refs/heads/pre-*",
    }
    protected: set[str] = set()
    protect_trunk_seen = False
    for path in rulesets:
        ruleset = _load_ruleset(path)
        if ruleset.get("target") != "branch":
            continue
        if ruleset.get("name") == "protect-trunk":
            protect_trunk_seen = True
            # The post-W2 fixture must declare both rules and the trunk
            # ref patterns.
            types = _rule_types(ruleset)
            assert {"deletion", "non_fast_forward"}.issubset(types), (
                "protect-trunk must declare deletion and non_fast_forward "
                f"rules; got {sorted(types)}."
            )
            # protect-trunk is the *only* place these two rules are
            # expected; the ruleset must NOT carry a `required_status_checks`
            # block — that would be a different ruleset's job and would
            # be a W11's stable-aggregator-names concern, not A1.1.
            assert "required_status_checks" not in types, (
                "protect-trunk must not carry a required_status_checks "
                "rule — that belongs to the status-check ruleset; "
                "A1.1 is deletion+non_fast_forward only."
            )
            assert trunk_patterns.issubset(set(_include_patterns(ruleset))), (
                f"protect-trunk must include {sorted(trunk_patterns)}; got "
                f"{_include_patterns(ruleset)}."
            )
            # D8 outcome also applies here: Admin bypass must be absent.
            bypass_actors = ruleset.get("bypass_actors", [])
            admin_bypass = [
                actor
                for actor in bypass_actors
                if actor.get("actor_type") == "RepositoryRole"
                and actor.get("actor_id") == 5
                and actor.get("bypass_mode") == "always"
            ]
            assert not admin_bypass, (
                "protect-trunk must not grant the Admin bypass — D8 (a) "
                "Gated removes the bypass from every ruleset created or "
                "edited by W2."
            )
            protected |= trunk_patterns
        else:
            # Any pre-existing branch ruleset contributes its includes to
            # the protected set. protect-main today only includes
            # ~DEFAULT_BRANCH.
            protected |= set(_include_patterns(ruleset))

    assert protect_trunk_seen, (
        "no protect-trunk ruleset found in "
        "tests/infra/fixtures/ci_architecture_batch_a/ — A1.1 demands a "
        "dedicated ruleset for the trunk branches. The W2 executor must "
        "have written ruleset-protect-trunk.after.json."
    )
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
