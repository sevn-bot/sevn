"""RED suite - Batch B "Default-branch reachability" (CI architecture wave plan).

Source contracts (plan Contract inventory, A2.1-A2.6 + A5.2 precondition):
- A2.1 — Every scheduled workflow is reachable — a caller exists on the
  default branch and an **observed run** succeeded.
- A2.2 — Workflow bodies are no longer mirrored: ``main`` holds thin
  ``workflow_call`` callers, the trunk holds implementations.
- A2.3 — ``dependabot.yml`` runs, targets the trunk, and groups
  ``github-actions`` updates.
- A2.5 — ``mergecraft.yml`` is ≤ 200 lines of invariants; incident
  archaeology relocated; ``wait-for-ci`` polling replaced.
- A2.6 — ``style-guide-pages.yml`` is deleted or made reachable — no
  workflow that cannot fire.
- A5.2 (precondition) — Every ``on: workflow_call`` workflow's
  ``actions/checkout`` steps pass an explicit ``ref:`` (audit §8 trap 1:
  without it a scheduler on ``main`` checks out the stub and the fix is
  vacuous).

Source of truth:
- ``about-sevn.bot/specs/25-cicd-full.md`` (Workflow matrix).
- W0 anchor freeze: ``.ignorelocal/waves/ci-architecture-w0-anchor-freeze.md``
  (committed-as-fixture in Batch A's fixture package, by copy).

Per plan **D4**, in-repo assertions go in pytest, live-API assertions go
in the B-Verify gate. These tests therefore read the recorded W0 fixture
via ``git show origin/main:.github/workflows/<file>`` and parse the YAML
directly, **not** the live GitHub API. A pytest test that needs a token
is a broken test (D4 invariant).

Implementation waves (W5, W6, W7, W8) are the only ones allowed to remove
the ``xfail`` markers — never an implementation agent; the test-creator
reconciles per the wave plan.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

# Trunk-side workflow file names — the canonical anchor list (W0.7 §"Pre-
# renamed workflow files"). The path ``.github/workflows/<name>`` is
# always relative to the trunk (we ``git show origin/pre-0.0.1:...``).
TRUNK_WORKFLOW_FILES: tuple[str, ...] = (
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    ".github/workflows/docker.yml",
    ".github/workflows/ci-cd.yml",
    ".github/workflows/ci-supplementary.yml",  # W6.1 renames to scheduled-impl.yml
    ".github/workflows/style-guide-pages.yml",
)

# W0.4 confirmed ``origin/main`` is a 3-file stub: LICENSE, README.md,
# ``.github/workflows/mergecraft.yml``. A pytest test that reads other
# paths from ``origin/main`` will see "fatal: path ... does not exist".
MAIN_STUB_FILES: tuple[str, ...] = (
    "LICENSE",
    "README.md",
    ".github/workflows/mergecraft.yml",
)

# W6.4 introduces this caller on ``main``; W5.3 introduces ``dependabot.yml``.
# W5.2 introduces ISSUE_TEMPLATE/ and PULL_REQUEST_TEMPLATE.md. These
# define the post-W5/W6 surface — tests assert each is present on main.
POST_W5_W6_MAIN_FILES: tuple[str, ...] = (
    ".github/dependabot.yml",
    ".github/ISSUE_TEMPLATE/",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/scheduled.yml",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _git_show(ref_path: str) -> str:
    """``git show origin/<ref>:<path>`` returning a clean string.

    Returns the empty string when the path is absent on the ref. We
    intentionally swallow the exit code here so the per-test assertions
    can phrase the failure in the contract's terms
    ("``dependabot.yml`` is missing on origin/main"), not in git's
    ("fatal: invalid object").
    """
    proc = subprocess.run(
        ["git", "show", ref_path],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _origin_main_blob(path: str) -> str:
    """Read ``path`` from ``origin/main`` — D4 in-repo assertion pattern."""
    return _git_show(f"origin/main:{path}")


def _origin_trunk_blob(path: str) -> str:
    """Read ``path`` from ``origin/pre-0.0.1`` — D4 in-repo assertion pattern."""
    return _git_show(f"origin/pre-0.0.1:{path}")


def _load_yaml_blob(text: str) -> dict | None:
    """Parse a YAML blob into a dict; ``None`` on parse failure."""
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def _workflow_on(doc: dict) -> dict:
    """Return the ``on:`` block of a parsed workflow, regardless of YAML 1.1
    literal-``on`` quirks (PyYAML treats ``on`` as boolean ``True`` since
    YAML 1.1; ``workflows.yml`` specify it as a string for clarity)."""
    return doc.get("on", doc.get(True, {})) or {}


def _ref_in_checkout_usage(checkout_with: dict) -> bool:
    """True if the checkout's ``with:`` declares a ``ref:`` key.

    Note: We do **not** test against a literal string here — the spec
    demands an explicit ``ref:`` field. Some workflows use ``ref:
    github.event.pull_request.base.ref`` (PR context) or
    ``ref: pre-0.0.1`` (always-trunk). Both are valid; the field just
    must be present.
    """
    return "ref" in (checkout_with or {})


def _has_workflow_call_on(on_block: dict) -> bool:
    """True if the trigger block declares ``workflow_call``.

    Accepts any of the documented shapes:
    ``on: workflow_call`` (bare string), ``on: workflow_call: {}`` (dict),
    or ``on: [workflow_call, workflow_dispatch]`` (list form).
    """
    if "workflow_call" in on_block:
        return True
    return on_block.get(True) == "workflow_call"


def _has_schedule_on(on_block: dict) -> bool:
    """True if the trigger block declares ``schedule:``."""
    if "schedule" in on_block:
        return True
    return on_block.get(True) == "schedule"


def _branch_list_from_on(on_block: dict, key: str) -> list[str]:
    """Extract a flat list of branch names from ``on.<key>.branches``.

    Supports the three YAML shapes:
    - ``branches: [main, develop]`` (list)
    - ``branches: {main: {}, develop: {}}`` (dict)
    - ``branches: main`` (single string)
    """
    val = on_block.get(key)
    if val is None:
        return []
    inner = val.get("branches") if isinstance(val, dict) else None
    if inner is None:
        return []
    if isinstance(inner, list):
        return [str(b) for b in inner]
    if isinstance(inner, dict):
        return [str(b) for b in inner]
    if isinstance(inner, str):
        return [inner]
    return []


def _all_step_checkout_with_refs(steps: list[dict]) -> list[bool]:
    """Return a list of booleans — one per ``actions/checkout`` step — whose
    ``with:`` declares an explicit ``ref:``.

    Also returns the same for nested ``steps:`` blocks (jobs containing
    ``actions/checkout`` in a sub-step are reachable). The audit §8 trap
    1 is precisely: a called workflow silently checks out the wrong
    ref. We test every ``uses: actions/checkout@<sha>`` step regardless
    of nesting.
    """
    flags: list[bool] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        uses = step.get("uses", "")
        if "actions/checkout" in uses:
            flags.append(_ref_in_checkout_usage(step.get("with", {}) or {}))
        nested = step.get("steps")
        if isinstance(nested, list):
            flags.extend(_all_step_checkout_with_refs(nested))
    return flags


# ---------------------------------------------------------------------------
# W4.1 — Every scheduled workflow has a caller on origin/main (A2.1)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "W4.1 — green after W6 (A2.1): scheduled workflows on the trunk "
        "(e.g. ci-supplementary.yml) declare `schedule:` but no caller "
        "exists on origin/main. Until W6.4 lands, the daily/weekly cron "
        "block is unreachable from the default branch — the rule that "
        "catches C17 from the parser side."
    ),
    strict=False,
)
def test_workflow_with_schedule_has_caller_on_origin_main() -> None:
    """Every workflow declaring ``schedule:`` must have a caller on
    ``origin/main``.

    Plan W4.1: parse ``git show origin/main:.github/workflows/*.yml``,
    no network. A scheduled workflow on the trunk fires only when a
    caller on ``main`` triggers it — ``schedule`` workflows on the
    trunk alone are dead (C17's class). The caller name is documented
    in W6.4: ``scheduled.yml``.
    """
    # 1. Trunk side: walk every workflow file and collect those that
    # declare ``schedule:`` (renamed or otherwise). W6.1 will rename
    # the file — we accept either name as the same scheduled impl.
    trunk_scheduled: list[str] = []
    for path in TRUNK_WORKFLOW_FILES:
        blob = _origin_trunk_blob(path)
        doc = _load_yaml_blob(blob)
        if doc is None:
            continue
        on_block = _workflow_on(doc)
        if _has_schedule_on(on_block):
            trunk_scheduled.append(path)

    # Sanity: the recorded W0 anchor freeze lists ``ci-supplementary.yml``
    # as the only scheduled workflow on the trunk (cron docs at :35-37).
    # If the parser sees zero, the test is wired wrong; an empty list
    # can never be the property under test.
    assert trunk_scheduled, (
        "no `schedule:` workflows found on the trunk — W0.7 anchor freeze "
        "documents ci-supplementary.yml as the daily/weekly cron job. "
        "Either the parse path is wrong or the workflow was deleted."
    )

    # 2. ``main`` side: confirm a caller exists. The W6.4 caller is
    # ``scheduled.yml``; the file absence is the xfail-RED under W4.1.
    caller_path = ".github/workflows/scheduled.yml"
    caller_blob = _origin_main_blob(caller_path)
    assert caller_blob, (
        f"scheduled caller `{caller_path}` is absent on origin/main — "
        "every scheduled workflow on the trunk is dead until W6.4 lands. "
        "C17 (the prod-ready-f-evidence cron that never fires) is the "
        "exact shape this rule catches."
    )

    # 3. The caller must itself declare a ``uses:`` referencing the
    # trunk impl. Without the `uses:` line the caller is decorative.
    caller_doc = _load_yaml_blob(caller_blob)
    assert caller_doc is not None, f"could not parse {caller_path} on origin/main"
    caller_jobs = caller_doc.get("jobs", {})
    assert isinstance(caller_jobs, dict)
    assert caller_jobs, (
        f"{caller_path} on origin/main declares no jobs — a caller without "
        "a `uses:` is a green file that does nothing."
    )
    # Find at least one step that uses a workflow from this repo.
    uses_self = False
    for job in caller_jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses", "")
            if uses.startswith(("sevn-bot/sevn/", "./")):
                uses_self = True
                break
        if uses_self:
            break
    assert uses_self, (
        f"{caller_path} on origin/main has no `uses: sevn-bot/sevn/.github/...` "
        "step — the caller must reference the trunk impl. A bare `on: schedule` "
        "would reproduce the same defect."
    )


# ---------------------------------------------------------------------------
# W4.2 — Called workflows have an explicit `ref:` in actions/checkout (A5.2)
# ---------------------------------------------------------------------------


def test_called_workflow_checkout_declare_explicit_ref() -> None:
    """Every ``on: workflow_call`` workflow must pass an explicit ``ref:``
    to its ``actions/checkout`` steps.

    Plan W4.2 / audit §8 trap 1: a scheduler on ``main`` that calls a
    trunk workflow without an explicit ``ref:`` silently checks out the
    3-file stub on ``main`` — every job runs against nothing. The fix
    is vacuous unless the checkout has ``ref: pre-0.0.1`` (or similar).

    **Not xfailed.** Today no workflow declares ``workflow_call`` on the
    trunk (only ``pull_request`` / ``push`` / ``schedule`` shapes), so
    the assertion is vacuously satisfied. The test is the **gate**
    that fires red the moment W6.1 introduces the ``workflow_call``
    shape without an explicit ``ref:`` — this is the precondition
    audit §8 trap 1 documents as the "fix is vacuous, in a new
    disguise" failure mode. The compile-time contract is:
    introducing the shape without ``ref:`` must fail the suite.
    """
    offenders: list[str] = []
    for path in TRUNK_WORKFLOW_FILES:
        blob = _origin_trunk_blob(path)
        if not blob:
            continue
        doc = _load_yaml_blob(blob)
        if doc is None:
            continue
        on_block = _workflow_on(doc)
        if not _has_workflow_call_on(on_block):
            continue
        # Walk every job's steps and check every actions/checkout usage.
        for job_id, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            flags = _all_step_checkout_with_refs(job.get("steps", []) or [])
            if not flags:
                # The job has no checkout at all — also a defect for a
                # called workflow (must check out the trunk).
                offenders.append(f"{path}:job:{job_id}:no_checkout")
                continue
            if not all(flags):
                offenders.append(
                    f"{path}:job:{job_id}:missing_ref_on:{flags.count(False)}_checkouts"
                )

    assert not offenders, (
        "every `on: workflow_call` workflow must pass an explicit `ref:` to "
        "each `actions/checkout` step — otherwise a scheduler on `main` checks "
        "out the 3-file stub and the fix is vacuous. Violations: " + ", ".join(offenders)
    )


# ---------------------------------------------------------------------------
# W4.3 — No unreachable branch triggers (A2.6, audit §1.3 finding)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "W4.3 — green after W6/W8 (A2.6): style-guide-pages.yml on the trunk "
        "declares `push.branches: [main]` with `paths: styles/sevn/style/**` "
        "but main has no `styles/` directory — the trigger cannot fire. W8.1 "
        "deletes or moves the workflow. Until then the violation is RED."
    ),
    strict=False,
)
def test_no_dead_workflow_paths_filter() -> None:
    """Every workflow's ``on.push.paths`` / ``on.pull_request.paths``
    filter must reference paths that exist on each branch it claims
    to fire on.

    Plan W4.3: this is what catches every dead ``main:`` entry. Today
    ``style-guide-pages.yml`` and the (now-closed) ``codeql`` weekly
    cron are the known offenders — ``codeql.yml` still has a
    reachable cron via its caller (W8.3), but
    ``style-guide-pages.yml`` lists ``paths: styles/sevn/style/**``
    on a branch where the directory is absent.

    We check each declared (branch, paths) pair against the live tree
    via ``git ls-tree``. Wildcards are not implemented for the
    purposes of this test — we treat the path as a literal prefix
    and assert at least one matching blob exists on the branch.
    """
    # Inventory of branches we actually have ruleset / workflow
    # coverage on (W0.1 + W0.7):
    inventory: set[str] = {"main", "pre-0.0.1", "test-pre", "develop"}

    offenders: list[str] = []
    for path in TRUNK_WORKFLOW_FILES:
        blob = _origin_trunk_blob(path)
        if not blob:
            continue
        doc = _load_yaml_blob(blob)
        if doc is None:
            continue
        on_block = _workflow_on(doc)
        for key in ("push", "pull_request"):
            val = on_block.get(key)
            if not isinstance(val, dict):
                continue
            branches = _branch_list_from_on(on_block, key)
            paths = val.get("paths")
            if not paths:
                continue
            if not isinstance(paths, list):
                paths = [paths]

            for branch in branches:
                if branch not in inventory:
                    # Unknown branch — would be a violation on its own
                    # but that test belongs to W4.3 (shape variant).
                    continue
                for p in paths:
                    if not isinstance(p, str):
                        continue
                    # Strip trailing /** for a literal-prefix check.
                    # The directory must exist on the branch.
                    prefix = p.split("**", 1)[0].rstrip("/")
                    if not prefix:
                        continue
                    # ``git ls-tree -r origin/<branch> -- <prefix>``
                    # returns "" if the prefix is missing entirely.
                    ls = subprocess.run(
                        ["git", "ls-tree", "-r", f"origin/{branch}", "--", prefix],
                        cwd=REPO,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if not ls.stdout.strip():
                        offenders.append(f"{path}:{key}.branches:{branch}:paths:{p}:no_match")

    assert not offenders, (
        "every workflow `paths:` filter must reference paths that exist on "
        "the branch it claims to fire on. Today style-guide-pages.yml names "
        "`styles/sevn/style/**` on `main` where the directory is absent — "
        "W8.1 deletes or moves the workflow. Violations: " + ", ".join(offenders)
    )


def test_no_unknown_branch_in_on_branches() -> None:
    """Every branch in ``on.push.branches`` / ``on.pull_request.branches``
    must be one of the known inventory branches.

    Plan W4.3 — the variant of the dead-trigger rule that catches
    unrecognised branch names rather than dead `paths:` filters.

    **Not xfailed.** The current trunk inventory is clean (no
    unknown branch names found). The test is the regression anchor:
    anyone introducing a new branch trigger must extend the
    inventory — the assertion itself is the gate.
    """
    inventory: set[str] = {"main", "pre-0.0.1", "test-pre", "develop"}

    offenders: list[str] = []
    for path in TRUNK_WORKFLOW_FILES:
        blob = _origin_trunk_blob(path)
        if not blob:
            continue
        doc = _load_yaml_blob(blob)
        if doc is None:
            continue
        on_block = _workflow_on(doc)
        for key in ("push", "pull_request"):
            for branch in _branch_list_from_on(on_block, key):
                if "*" in branch:
                    prefix = branch.split("*", 1)[0]
                    if any(b.startswith(prefix) for b in inventory):
                        continue
                    offenders.append(f"{path}:{key}.branches:{branch}:no_match_in_known_inventory")
                    continue
                if branch not in inventory:
                    offenders.append(f"{path}:{key}.branches:{branch}:unknown_branch")

    assert not offenders, (
        "every branch in `on.push.branches` / `on.pull_request.branches` must "
        "exist on the repo or be a wildcard pattern over known branches. "
        "Violations: " + ", ".join(offenders)
    )


# ---------------------------------------------------------------------------
# W4.4 — dependabot.yml on origin/main has target-branch + groups (A2.3)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "W4.4 — green after W5 (A2.3): dependabot.yml currently lives on the "
        "trunk only — `git show origin/main:.github/dependabot.yml` exits 128 "
        "today. W5.3 moves it to `main` with `target-branch: pre-0.0.1` and a "
        "`groups:` entry for `github-actions`. Until then the assertion is RED."
    ),
    strict=False,
)
def test_dependabot_target_branch_and_groups_on_origin_main() -> None:
    """``.github/dependabot.yml`` on ``origin/main`` must:

    1. Set ``target-branch:`` to the trunk (``pre-0.0.1``).
    2. Declare a ``groups:`` entry for ``github-actions`` updates.
    3. Exist at all (the W0.4 anchor-freeze confirms it is absent on main).

    Without (1) every dependabot PR lands on the stub (3-file `main`)
    and cannot be reviewed. Without (2) a weekly cycle on 15 pinned
    actions is a review-load DoS.
    """
    path = ".github/dependabot.yml"
    blob = _origin_main_blob(path)
    assert blob, (
        f"`{path}` is absent on origin/main — Dependabot cannot run from "
        "the default branch. W0.4 anchor freeze records `git pr list "
        "--author app/dependabot` as `[]` today. A2.3 closes when W5.3 "
        "moves the file to main."
    )

    doc = _load_yaml_blob(blob)
    assert doc is not None, f"could not parse {path} on origin/main"
    assert doc.get("version") == 2, (
        f"`{path}` on origin/main must declare `version: 2` — the only "
        "Dependabot manifest schema the GitHub API surfaces."
    )

    updates = doc.get("updates")
    assert isinstance(updates, list)
    assert updates, (
        f"`{path}` on origin/main has no `updates:` list - the file must "
        "declare at least one ecosystem to be a valid Dependabot manifest."
    )

    # 1. target-branch must be the trunk. W0.7 anchor freeze:
    # `pre-0.0.1` is the operational trunk; `test-pre` is the post-0.0.1
    # staging. Either is acceptable here per the plan (W5.3 picks one).
    trunk_targets = {"pre-0.0.1", "test-pre"}
    target_branches = {u.get("target-branch") for u in updates if isinstance(u, dict)}
    missing = trunk_targets.isdisjoint(target_branches)
    assert not missing, (
        f"dependabot.yml on origin/main must set `target-branch:` to one of "
        f"{sorted(trunk_targets)} on at least one ecosystem; got "
        f"{sorted(target_branches)}."
    )

    # 2. groups.github-actions must be present on the `github-actions`
    # ecosystem entry. The plan docs about 15 pinned actions per weekly cycle.
    github_actions_entry = next(
        (
            u
            for u in updates
            if isinstance(u, dict) and u.get("package-ecosystem") == "github-actions"
        ),
        None,
    )
    assert github_actions_entry is not None, (
        f"`{path}` on origin/main has no `github-actions` ecosystem entry - "
        "A2.3 explicitly demands the grouped github-actions updates."
    )
    groups = github_actions_entry.get("groups")
    assert isinstance(groups, dict)
    assert "github-actions" in groups, (
        f"`{path}` on origin/main `github-actions` entry must declare "
        f"`groups: {{ github-actions: {{ ... }} }}`; got {groups!r}."
    )


# ---------------------------------------------------------------------------
# W4.5 — mergecraft.yml on origin/main is ≤ 200 lines; review body on trunk
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "W4.5 - green after W7 (A2.5): mergecraft.yml on origin/main is 537 "
        "lines today (audit paragraph 5 anchor). W7.1-W7.3 split the file "
        "into a <= 200 line caller on main and the impl on the trunk. "
        "Until then the line count is RED."
    ),
    strict=False,
)
def test_mergecraft_caller_on_origin_main_is_at_most_200_lines() -> None:
    """``.github/workflows/mergecraft.yml`` on ``origin/main`` must be
    ≤ 200 total lines.

    Plan W4.5: today the file is 537 lines (audit §5). W7.3 prunes it
    to invariants (trigger + concurrency + permissions + ``uses:`` +
    ``secrets: inherit``). The impl moves to trunk
    ``mergecraft-impl.yml`` (W7.1).

    The line cap is enforced on the on-`main` copy because that's the
    file the trigger resolves against (GitHub Nov 2025 policy).
    """
    path = ".github/workflows/mergecraft.yml"
    blob = _origin_main_blob(path)
    assert blob, (
        f"`{path}` is absent on origin/main — without it no PR can be "
        "reviewed. W0.4 confirmed the file is present; if this assertion "
        "fails in CI, the stub was somehow deleted."
    )

    # Count lines the same way GitHub's UI does: split on '\n', exclude
    # a trailing empty line ('last \n' is not counted as a line).
    line_count = len(blob.split("\n"))
    if blob.endswith("\n"):
        line_count -= 1
    assert line_count <= 200, (
        f"mergecraft.yml on origin/main is {line_count} lines (audit §5 "
        "anchor: 537 today). W7.3 target: ≤ 200 lines of invariants only. "
        "Anything beyond the trigger + concurrency + permissions + uses + "
        "secrets: inherit is archaeology that belongs in the mergeCraft "
        "repo or .ignorelocal/."
    )

    # The review body must live on the trunk. W7.1 moves the review
    # logic to mergecraft-impl.yml on the trunk with `on: workflow_call`.
    # The test asserts the post-W7 surface: the trunk impl file exists
    # and the on-main caller references it.
    impl_path = ".github/workflows/mergecraft-impl.yml"
    impl_blob = _origin_trunk_blob(impl_path)
    assert impl_blob, (
        f"`{impl_path}` is absent on the trunk — W7.1 must move the review "
        "body to the trunk under `on: workflow_call`. Until then the caller's "
        "`uses:` has nothing to invoke."
    )
    impl_doc = _load_yaml_blob(impl_blob)
    assert impl_doc is not None, f"could not parse {impl_path} on trunk"
    impl_on = _workflow_on(impl_doc)
    assert _has_workflow_call_on(impl_on), (
        f"`{impl_path}` on the trunk must declare `on: workflow_call` — "
        "it is the impl, not a callable runnable on `main`."
    )


# ---------------------------------------------------------------------------
# W4.6 — Guard: mergecraft invariants survive the split (highest blast radius)
# ---------------------------------------------------------------------------


def test_mergecraft_invariants_survive_split_on_origin_main() -> None:
    """W4.6 guard: the mergecraft split must preserve the invariants.

    Plan W4.6 + audit §4.3 + Bateson findings: the highest-blast-radius
    change in the program. This batch **moves** the reviewer; it must
    not weaken it. The guard pins:

    1. ``on: pull_request_target`` trigger (not ``pull_request`` —
       GitHub skips pull_request with merge conflicts, leaving the
       ruleset missing-check).
    2. Same-repo ``HAS_AUTH`` / ``HAS_NOUS`` / ``HAS_CODEX`` guards on
       the caller's job env. These ensure forks skip the reviewer
       rather than leak secrets.
    3. The action uses ``push: disabled`` / ``shell: disabled`` (the
       caller's uses-with passes these to the mergeCraft action).
    4. Fail-closed enforce path: at least one ``if: env.HAS_AUTH …``
       branch where the absence of auth skips the whole review step
       (not a silent no-op).

    This is a **non-xfailed** test. It must pass on the current
    caller-shaped file and remain green after W7. A reviewer edit that
    weakens any of these is `changes_required` per the audit-escape
    rubric (P3 + B-Thermos).
    """
    path = ".github/workflows/mergecraft.yml"
    blob = _origin_main_blob(path)
    assert blob, (
        f"`{path}` is absent on origin/main — the mergeCraft reviewer is "
        "the ruleset-required check; without this file the PR gate has no "
        "review signal."
    )

    doc = _load_yaml_blob(blob)
    assert doc is not None, f"could not parse {path} on origin/main"
    on_block = _workflow_on(doc)

    # 1. pull_request_target trigger.
    pr_target = on_block.get("pull_request_target")
    assert pr_target is not None, (
        "mergecraft.yml on origin/main must declare `on: pull_request_target` "
        "(audit §4.3 + W0.7 anchor: `pull_request` skips on merge conflicts "
        "and leaves the ruleset required check permanently missing). "
        "`pull_request` triggers must not be added back — the W0 file "
        "documents why it was removed."
    )

    # 2. Same-repo HAS_* guards. The pattern is documented at
    # mergecraft.yml:228-230 (W0.7 anchor). We assert the three
    # env-vars are declared on at least one job's env block.
    jobs = doc.get("jobs") or {}
    assert isinstance(jobs, dict)
    assert jobs, "mergecraft.yml has no jobs"
    required_envs = {"HAS_AUTH", "HAS_NOUS", "HAS_CODEX"}
    job_envs: list[dict] = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        env = job.get("env")
        if isinstance(env, dict):
            job_envs.append(env)
    combined = {k: v for env in job_envs for k, v in env.items()}
    missing = required_envs - set(combined.keys())
    assert not missing, (
        "mergecraft.yml jobs must declare HAS_AUTH / HAS_NOUS / HAS_CODEX env "
        "vars (same-repo guards; forks skip). Missing: " + ", ".join(sorted(missing))
    )

    # 2b. The HAS_* guard clauses must include the same-repo check
    # pattern (W0.7 anchor: `github.event.pull_request.head.repo.full_name ==
    # github.repository`). Without it the guard is decorative on forks.
    has_same_repo_check = False
    for value in combined.values():
        if not isinstance(value, str):
            continue
        if "github.repository" in value and "head.repo.full_name" in value:
            has_same_repo_check = True
            break
    assert has_same_repo_check, (
        "at least one HAS_* env declaration must include the same-repo "
        "substring `github.event.pull_request.head.repo.full_name == "
        "github.repository` — the guard that keeps forks from invoking the "
        "reviewer with the bot's secrets."
    )

    # 3. push: disabled / shell: disabled on at least one of the
    # `uses: alexhawat/mergeCraft@...` step's `with:` block.
    push_shell_disabled = False
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in _walk_steps(job.get("steps", []) or []):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses", "")
            if "alexhawat/mergeCraft" not in uses:
                continue
            with_block = step.get("with", {}) or {}
            if with_block.get("push") == "disabled" and with_block.get("shell") == "disabled":
                push_shell_disabled = True
                break
        if push_shell_disabled:
            break
    assert push_shell_disabled, (
        "every `uses: alexhawat/mergeCraft@...` step must declare "
        "`with: { push: disabled, shell: disabled }` — the action's "
        "subprocess safety net. The pattern is at mergecraft.yml:355-356 "
        "and :444-445 (W0.7 anchor)."
    )

    # 4. Fail-closed enforce path: at least one step whose `if:` keys
    # on `env.HAS_AUTH` and routes the review step accordingly. Test
    # the `if:` strings (we don't replay the full job flow).
    fail_closed_branch = False
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in _walk_steps(job.get("steps", []) or []):
            if not isinstance(step, dict):
                continue
            if_clause = step.get("if", "")
            if not isinstance(if_clause, str):
                continue
            if "HAS_AUTH" in if_clause:
                fail_closed_branch = True
                break
        if fail_closed_branch:
            break
    assert fail_closed_branch, (
        "mergecraft.yml must contain at least one step whose `if:` keys on "
        "`env.HAS_AUTH` — the fail-closed enforce path that turns the "
        "secret-absence branch into a deterministic skip rather than a "
        "silent no-op."
    )


def _walk_steps(steps: list[dict]) -> Iterator[dict]:
    """Yield each step and any nested ``steps:`` block — iterative, not
    recursive, to keep the assertion readable.
    """
    queue: list[dict] = list(steps)
    while queue:
        step = queue.pop(0)
        if isinstance(step, dict):
            yield step
            nested = step.get("steps")
            if isinstance(nested, list):
                queue.extend(nested)


# ---------------------------------------------------------------------------
# W4.7 — Guard: W0 anchor freeze survives this batch's edits
# ---------------------------------------------------------------------------


def test_w0_anchor_freeze_unchanged_after_w4() -> None:
    """The W0 anchor freeze must still exist and reference the findings
    this batch depends on.

    Counterpart to Batch A's ``test_anchor_freeze_records_required_w0_findings``.
    This batch's assertions read from the freeze when their document
    evidence is needed (caller-exists, dependabot target-branch, etc.);
    the freeze MUST survive W4's edits (W4 does not touch it).

    The W0 freeze lives in the primary-checkout-only
    ``.ignorelocal/waves/`` tree (gitignored). The fixture copy
    Batch A committed under ``tests/infra/fixtures/ci_architecture_batch_a/``
    is the durable mirror — when present, the test reads the mirror
    rather than the local-only freeze.
    """
    # 1. Try the fixture copy (Batch A's fixture package).
    fixture_freeze = (
        REPO / "tests/infra/fixtures/ci_architecture_batch_a/ci-architecture-w0-anchor-freeze.md"
    )
    if fixture_freeze.exists():
        text = fixture_freeze.read_text(encoding="utf-8")
    else:
        # 2. Fall back to the primary-checkout live freeze.
        freeze_path = REPO / ".ignorelocal" / "waves" / "ci-architecture-w0-anchor-freeze.md"
        if not freeze_path.exists():
            pytest.skip(
                "W0 anchor freeze not present on this checkout — neither fixture nor primary tree"
            )
        text = freeze_path.read_text(encoding="utf-8")

    must_contain = [
        # Section ids referenced by the batch.
        "W0.1",
        "W0.4",
        "W0.5",
        "W0.6",
        "W0.7",
        # The scheduled-workflow finding, naming the only scheduled
        # workflow on the trunk (W4.1 anchor).
        "ci-supplementary",
        # The mergecraft line-count anchor (W4.5).
        "mergecraft.yml",
        # The dependabot anchor (W4.4).
        "dependabot",
        # The blast-radius anchors of the rename (W4.1 / W6.1).
        "scheduled-impl",
        # The dead-style-guide trigger (W4.3).
        "style-guide-pages",
    ]
    missing = [token for token in must_contain if token not in text]
    assert not missing, (
        "W0 anchor freeze is missing required tokens for Batch B's "
        "assertions: " + ", ".join(missing)
    )
