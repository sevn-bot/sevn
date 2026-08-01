"""Smoke-test the mergeCraft ref parity script (``specs/25-cicd-full.md``).

The script reads ``mergecraft.yml`` from the default branch rather than the working
tree (the trunk carries no copy), so the drift fixtures build a throwaway git repo
with a ``main`` branch instead of writing a file next to the Makefile.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_mergecraft_ref_parity.py"
WORKFLOW_PATH = ".github/workflows/mergecraft.yml"

# A minimal stand-in for main's workflow: the gate only reads the `uses:` pin.
WORKFLOW_STUB = """name: mergecraft
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: alexhawat/mergeCraft@a7510af0ab4d7deb863c043e85f8e5365082f07d # pre-0.0.1 (Codex harness)
"""


def _run(cwd: Path, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the parity script in ``cwd`` with an isolated environment."""
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(cwd),
        **(env_extra or {}),
    }
    return subprocess.run(
        [sys.executable, "scripts/check_mergecraft_ref_parity.py"],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _seed_repo(root: Path, *, makefile_ref: str | None = None, with_workflow: bool = True) -> None:
    """Build a git repo whose ``main`` branch carries the workflow stub.

    Args:
        root: Directory to initialise as a git repo.
        makefile_ref: Ref to force into the Makefile pin; ``None`` keeps the real one.
        with_workflow: Whether ``main`` should carry ``mergecraft.yml`` at all.
    """
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    if makefile_ref is not None:
        makefile, count = re.subn(
            r"(MERGECRAFT_REF\s*\?=\s*\$\(if\s*\$\(SEVN_MERGECRAFT_REF\)\s*,\s*"
            r"\$\(SEVN_MERGECRAFT_REF\)\s*,\s*)[^),\s]+(\s*\))",
            rf"\g<1>{makefile_ref}\g<2>",
            makefile,
        )
        assert count == 1, "test fixture must match exactly one MERGECRAFT_REF default"
    (root / "Makefile").write_text(makefile, encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "check_mergecraft_ref_parity.py").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    if with_workflow:
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / ".github" / "workflows" / "mergecraft.yml").write_text(
            WORKFLOW_STUB, encoding="utf-8"
        )

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
            cwd=root,
            check=True,
            capture_output=True,
        )

    git("init", "-b", "main")
    git("add", "-A")
    git("commit", "-m", "seed")


def test_check_mergecraft_ref_parity_exits_zero() -> None:
    """Against the real repo, main's workflow and the Makefile ref match → exit 0."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_check_mergecraft_ref_parity_detects_drift(tmp_path: Path) -> None:
    """A Makefile pin that differs from the default-branch workflow → exit 1."""
    _seed_repo(tmp_path, makefile_ref="definitely-not-the-workflow-ref")
    proc = _run(tmp_path, {"SEVN_MERGECRAFT_WORKFLOW_REF": "main"})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "drift" in proc.stderr.lower()


def test_check_mergecraft_ref_parity_reads_default_branch_not_worktree(tmp_path: Path) -> None:
    """The pin is read from the ref, not the checkout — a drifted worktree still passes."""
    _seed_repo(tmp_path)
    # Corrupt the working-tree copy: if the gate read the file from disk it would
    # report drift. It reads `main:` instead, so this must stay green.
    (tmp_path / ".github" / "workflows" / "mergecraft.yml").write_text(
        WORKFLOW_STUB.replace("a7510af0ab4d7deb863c043e85f8e5365082f07d", "worktree-only-ref"),
        encoding="utf-8",
    )
    proc = _run(tmp_path, {"SEVN_MERGECRAFT_WORKFLOW_REF": "main"})
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_check_mergecraft_ref_parity_skips_when_ref_unreadable(tmp_path: Path) -> None:
    """No workflow on the ref and no CI → skip (exit 0) rather than block local work."""
    _seed_repo(tmp_path, with_workflow=False)
    proc = _run(tmp_path, {"SEVN_MERGECRAFT_WORKFLOW_REF": "main"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "skipping" in proc.stderr.lower()


def test_check_mergecraft_ref_parity_fails_when_ref_unreadable_in_ci(tmp_path: Path) -> None:
    """The same unreadable ref is a hard failure under CI, so the gate is not decorative."""
    _seed_repo(tmp_path, with_workflow=False)
    proc = _run(tmp_path, {"SEVN_MERGECRAFT_WORKFLOW_REF": "main", "CI": "true"})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "required under ci" in proc.stderr.lower()
