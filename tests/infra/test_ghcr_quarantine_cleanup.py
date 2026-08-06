"""Behavioral coverage for quarantine cleanup exit-status handling.

mergeCraft finding: ``gh api`` inside a process substitution does not propagate
failure under ``set -euo pipefail``, so a failed list call looked like success.
"""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLEANUP = _REPO_ROOT / "scripts" / "ghcr_quarantine_cleanup.sh"
_CURL_GATE = _REPO_ROOT / "scripts" / "check_no_curl_pipe_sh.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_ghcr_quarantine_cleanup_fails_when_version_list_fails(tmp_path: Path) -> None:
    """A failing ``gh api --paginate …/versions`` must fail the cleanup function."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gh.log"
    _write_executable(
        bin_dir / "gh",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s\\n' "$*" >> "{log}"
            if [[ "$*" == *"/versions"* ]]; then
              echo "simulated versions list failure" >&2
              exit 22
            fi
            # Package existence probes succeed so we reach the versions call.
            exit 0
            """
        ),
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "test-token",
    }
    script = textwrap.dedent(
        f"""\
        set -euo pipefail
        # shellcheck disable=SC1091
        source "{_CLEANUP}"
        delete_quarantine_tags "owner/repo" "abc123" "99"
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode != 0, (
        "cleanup must fail closed when listing package versions fails; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "failed to list versions" in proc.stderr
    assert log.is_file()
    assert "/versions" in log.read_text(encoding="utf-8")


def test_check_no_curl_pipe_sh_self_test_passes() -> None:
    """The gate's embedded self-test (including backslash continuations) must pass."""
    proc = subprocess.run(
        ["bash", str(_CURL_GATE)],
        check=False,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


@pytest.mark.parametrize(
    "sample",
    [
        "curl -LsSf https://example.invalid/install.sh | sh\n",
        "curl -LsSf https://example.invalid/install.sh \\\n| sh\n",
    ],
)
def test_check_no_curl_pipe_sh_detects_samples(tmp_path: Path, sample: str) -> None:
    """Direct sample detection mirrors the gate's logical-line join."""
    probe = tmp_path / "probe.sh"
    probe.write_text(sample, encoding="utf-8")
    pattern = r"(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b"
    proc = subprocess.run(
        [
            "python3",
            "-c",
            "import re,sys; from pathlib import Path\n"
            "p=re.compile(sys.argv[1], re.I)\n"
            "t=re.sub(r'\\\\\\r?\\n','',Path(sys.argv[2]).read_text())\n"
            "sys.exit(0 if p.search(t) else 1)",
            pattern,
            str(probe),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"sample not detected: {sample!r}"
