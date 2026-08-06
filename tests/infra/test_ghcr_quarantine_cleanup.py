"""Behavioral coverage for quarantine cleanup and curl|sh gate fail-closed paths."""

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


def _run_cleanup(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    script = textwrap.dedent(
        f"""\
        set -euo pipefail
        # shellcheck disable=SC1091
        source "{_CLEANUP}"
        delete_quarantine_tags "owner/repo" "abc123" "99"
        """
    )
    return subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


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
            # Ownership probes use ``gh api -i``; answer 200 for package existence.
            if [[ "$*" == *"-i"* ]]; then
              printf 'HTTP/2.0 200 OK\\r\\n\\r\\n{{"id":1}}\\n'
              exit 0
            fi
            exit 0
            """
        ),
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "test-token",
    }
    proc = _run_cleanup(env)
    assert proc.returncode != 0, (
        "cleanup must fail closed when listing package versions fails; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "failed to list versions" in proc.stderr
    assert log.is_file()
    assert "/versions" in log.read_text(encoding="utf-8")


def test_ghcr_quarantine_cleanup_fails_on_non_404_package_probe(tmp_path: Path) -> None:
    """Auth/rate-limit/5xx package probes must not be treated as 'not found'."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "gh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "$*" == *"-i"* ]]; then
              printf 'HTTP/2.0 403 Forbidden\\r\\n\\r\\n{"message":"forbidden"}\\n'
              exit 0
            fi
            exit 1
            """
        ),
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "test-token",
    }
    proc = _run_cleanup(env)
    assert proc.returncode != 0, (
        "cleanup must fail closed on non-404 package probe; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "failed with HTTP 403" in proc.stderr
    assert "package not found" not in proc.stdout


def test_ghcr_quarantine_cleanup_skips_true_404(tmp_path: Path) -> None:
    """Expected 404 on org and user package probes remains a soft skip."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "gh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "$*" == *"-i"* ]]; then
              printf 'HTTP/2.0 404 Not Found\\r\\n\\r\\n{"message":"Not Found"}\\n'
              exit 0
            fi
            exit 1
            """
        ),
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "test-token",
    }
    proc = _run_cleanup(env)
    assert proc.returncode == 0, (
        f"true 404 must soft-skip; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "package not found" in proc.stdout


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


def test_check_no_curl_pipe_sh_scans_non_allowlisted_shell_filename(tmp_path: Path) -> None:
    """``.github/install.bash`` (outside the old extension allowlist) must be scanned."""
    root = tmp_path / "repo"
    (root / ".github").mkdir(parents=True)
    (root / "Makefile").write_text("# clean\n", encoding="utf-8")
    offender = root / ".github" / "install.bash"
    offender.write_text(
        "curl -LsSf https://example.invalid/install.sh | sh\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "SEVN_CURL_PIPE_SCAN_ROOT": str(root),
    }
    proc = subprocess.run(
        ["bash", str(_CURL_GATE)],
        check=False,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
    )
    assert proc.returncode != 0, (
        f"gate must catch curl|sh in install.bash; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "install.bash" in proc.stderr


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
