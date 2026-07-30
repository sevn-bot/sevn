"""Fail when the mergeCraft pin drifts between the running workflow and the Makefile.

The CI review action pins ``alexhawat/mergeCraft@<sha>``; the ``Makefile``'s
``MERGECRAFT_REF`` default must match it so local ``make review`` runs the same
reviewed code as CI. Nothing else enforces that invariant, so a one-sided bump
would silently break it — this gate makes such drift fail CI (wired into
``make ci-parity``).

The workflow side is read from **``origin/main``**, not from the working tree.
``mergecraft.yml`` lives only on the default branch: GitHub resolves
``pull_request_target`` definitions from the repository default branch (Nov 2025
policy), so ``main``'s copy is the one that actually runs for every PR regardless
of the base branch. A trunk-side copy would be inert, and comparing it here would
check two files that do not matter against each other while the executing pin went
unchecked. Override the ref with ``SEVN_MERGECRAFT_WORKFLOW_REF`` (e.g. to compare
against a companion PR branch before it merges to ``main``).

Ref *equality* is all this checks — it does not require a SHA. GitHub does: the
``sevn-bot`` org enforces Actions SHA pinning, so a branch ref in the workflow is
rejected at action-resolution time regardless of what this gate says. The ref
grammar here stays permissive so a local ``SEVN_MERGECRAFT_REF`` branch override
and any future policy change need no edit.

When the workflow ref cannot be read (offline, no ``origin`` remote), the gate
**skips** locally and **fails** under ``CI`` — a parity check should not block work
on a plane, but a silent skip in CI would make it decorative.

Module: scripts.check_mergecraft_ref_parity
Depends: os, re, subprocess, pathlib, sys

Exports:
    read_workflow — read ``mergecraft.yml`` out of a git ref, fetching it if absent.
    main — CLI entry; compares the two pinned refs and reports drift.

Examples:
    >>> from pathlib import Path
    >>> REPO_ROOT == Path(__file__).resolve().parents[1]
    True
    >>> WORKFLOW_PATH
    '.github/workflows/mergecraft.yml'
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"

# Path *inside the default-branch tree* — this file is intentionally absent from
# the trunk working tree, so it is a git path, never a filesystem path.
WORKFLOW_PATH = ".github/workflows/mergecraft.yml"
DEFAULT_WORKFLOW_REF = "origin/main"

# `uses: alexhawat/mergeCraft@<ref>` in the workflow. CI must carry a full SHA (org
# SHA-pinning policy), but match any git ref characters up to the trailing
# ` # <branch>` comment rather than hex only, so the gate still reports real drift
# instead of "no pin found" if the ref is ever something else.
_WORKFLOW_RE = re.compile(r"uses:\s*alexhawat/mergeCraft@(?P<ref>[^\s#]+)")
# `MERGECRAFT_REF ?= $(if $(SEVN_MERGECRAFT_REF),$(SEVN_MERGECRAFT_REF),<ref>)`
# in the Makefile — the default (third) argument is the pinned ref.
_MAKEFILE_RE = re.compile(
    r"MERGECRAFT_REF\s*\?=\s*\$\(if\s*\$\(SEVN_MERGECRAFT_REF\)\s*,\s*"
    r"\$\(SEVN_MERGECRAFT_REF\)\s*,\s*(?P<ref>[^),\s]+)\s*\)"
)
# `origin/main` -> ("origin", "main"), so a missing ref can be fetched on demand.
_REMOTE_REF_RE = re.compile(r"^(?P<remote>[^/]+)/(?P<branch>.+)$")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``git`` in the repo root and capture its output.

    Args:
        args (str): Arguments passed to ``git``.

    Returns:
        subprocess.CompletedProcess[str]: The completed process (never raises on
        a non-zero exit — callers branch on ``returncode``).

    Examples:
        >>> _git("rev-parse", "--is-inside-work-tree").returncode
        0
    """
    return subprocess.run(
        # Fixed argv, no shell. `git` resolves from PATH so the repo's own guard
        # wrapper (bin/git) stays in the loop.
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def read_workflow(ref: str) -> str | None:
    """Read ``mergecraft.yml`` out of ``ref``, fetching the ref when it is absent.

    A shallow CI checkout has no ``origin/main``, so a missing remote-tracking ref
    is fetched once before giving up.

    Args:
        ref (str): Git ref holding the workflow (e.g. ``origin/main``).

    Returns:
        str | None: The workflow text, or ``None`` when the ref cannot be read.

    Examples:
        >>> read_workflow("refs/nope/definitely-missing") is None
        True
    """
    show = _git("show", f"{ref}:{WORKFLOW_PATH}")
    if show.returncode == 0:
        return show.stdout

    remote_ref = _REMOTE_REF_RE.match(ref)
    if remote_ref is None:
        return None
    remote, branch = remote_ref.group("remote"), remote_ref.group("branch")
    fetch = _git(
        "fetch",
        "--no-tags",
        "--depth=1",
        remote,
        f"{branch}:refs/remotes/{remote}/{branch}",
    )
    if fetch.returncode != 0:
        return None
    retry = _git("show", f"{ref}:{WORKFLOW_PATH}")
    return retry.stdout if retry.returncode == 0 else None


def main() -> int:
    """Compare the default-branch workflow pin against the Makefile pin.

    Returns:
        int: ``0`` when the two refs match (or the workflow ref is unreadable
        outside CI), ``1`` on drift or a missing pin.

    Examples:
        >>> main() in (0, 1)
        True
    """
    ref = os.environ.get("SEVN_MERGECRAFT_WORKFLOW_REF") or DEFAULT_WORKFLOW_REF

    workflow_text = read_workflow(ref)
    if workflow_text is None:
        message = (
            f"mergecraft-ref-check: cannot read {WORKFLOW_PATH} from {ref} "
            "(no such ref, or fetch failed)"
        )
        if os.environ.get("CI"):
            print(f"{message} — required under CI.", file=sys.stderr)
            return 1
        print(f"{message} — skipping parity check (offline?).", file=sys.stderr)
        return 0

    workflow_match = _WORKFLOW_RE.search(workflow_text)
    if workflow_match is None:
        print(
            f"mergecraft-ref-check: no workflow action pin found in {ref}:{WORKFLOW_PATH}",
            file=sys.stderr,
        )
        return 1
    workflow_ref = workflow_match.group("ref")

    try:
        makefile_text = MAKEFILE.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"mergecraft-ref-check: cannot read {MAKEFILE}: {exc}", file=sys.stderr)
        return 1
    makefile_match = _MAKEFILE_RE.search(makefile_text)
    if makefile_match is None:
        print(
            f"mergecraft-ref-check: no MERGECRAFT_REF default pin found in {MAKEFILE}",
            file=sys.stderr,
        )
        return 1
    makefile_ref = makefile_match.group("ref")

    if workflow_ref != makefile_ref:
        print(
            "mergecraft-ref-check: mergeCraft pin drift —\n"
            f"  workflow ({ref}:{WORKFLOW_PATH}): {workflow_ref}\n"
            f"  Makefile (MERGECRAFT_REF default): {makefile_ref}\n"
            "Set both to the same ref so local `make review` matches CI. The workflow\n"
            "lives only on the default branch — bump it in a PR against `main`.",
            file=sys.stderr,
        )
        return 1
    print(f"mergecraft-ref-check: ok — {ref} and Makefile both on {workflow_ref}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
