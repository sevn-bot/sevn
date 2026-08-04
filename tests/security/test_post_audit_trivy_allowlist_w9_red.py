"""Post-audit Batch C W9 RED — Trivy baseline (#173; D23).

Contracts (``about-sevn.bot/specs/25-cicd-full.md`` §3.2 / §10.3): ``security/trivy-allowlist.toml``
mirrors pip-audit allowlist shape; ``scripts/trivy_ignore_args.py`` emits ignore args and fails
on expired ``review_by`` rows; container scan runs trivy with ``--exit-code 1`` before cosign sign.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from datetime import date, timedelta
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRIVY_ALLOWLIST = _REPO_ROOT / "security" / "trivy-allowlist.toml"
_TRIVY_IGNORE_SCRIPT = _REPO_ROOT / "scripts" / "trivy_ignore_args.py"
_CI_CD = _REPO_ROOT / ".github" / "workflows" / "ci-cd.yml"


def _scan_image_body() -> str:
    text = _CI_CD.read_text(encoding="utf-8")
    match = re.search(r"scan_image\(\)\s*\{([^}]+)\}", text, re.DOTALL)
    assert match is not None, "scan_image() shell function missing from ci-cd.yml"
    return match.group(1)


def _run_trivy_ignore_args(*, allowlist: Path | None = None) -> subprocess.CompletedProcess[str]:
    assert _TRIVY_IGNORE_SCRIPT.is_file(), "scripts/trivy_ignore_args.py missing until W11"
    env = None
    if allowlist is not None:
        env = {**os.environ, "TRIVY_ALLOWLIST_PATH": str(allowlist)}
    return subprocess.run(
        [sys.executable, str(_TRIVY_IGNORE_SCRIPT)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.mark.xfail(reason="green after W11", strict=False)
def test_trivy_allowlist_file_exists_and_parses() -> None:
    """W9.4: allowlist is the single source of truth for time-boxed image CVE exceptions."""
    assert _TRIVY_ALLOWLIST.is_file(), "security/trivy-allowlist.toml missing until W11"
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    with _TRIVY_ALLOWLIST.open("rb") as fh:
        data = tomllib.load(fh)
    rows = data.get("ignore", [])
    assert isinstance(rows, list)


@pytest.mark.xfail(reason="green after W11", strict=False)
def test_trivy_ignore_args_emits_active_ignore_flags(tmp_path: Path) -> None:
    """W9.4: helper prints ignore args for non-expired rows (mirrors pip-audit helper)."""
    future = (date.today() + timedelta(days=30)).isoformat()
    allowlist = tmp_path / "trivy-allowlist.toml"
    allowlist.write_text(
        textwrap.dedent(
            f"""\
            [[ignore]]
            vuln_id = "CVE-2026-TEST-001"
            image = "ghcr.io/sevn-bot/sevn/gateway"
            reason = "Seeded baseline row for W9 RED"
            ticket = "https://github.com/sevn-bot/sevn/issues/173"
            review_by = "{future}"
            """
        ),
        encoding="utf-8",
    )
    proc = _run_trivy_ignore_args(allowlist=allowlist)
    assert proc.returncode == 0, proc.stderr
    assert "CVE-2026-TEST-001" in proc.stdout or "--ignorefile" in proc.stdout


@pytest.mark.xfail(reason="green after W11", strict=False)
def test_trivy_ignore_args_fails_on_expired_review_by(tmp_path: Path) -> None:
    """W9.4: expired ``review_by`` rows fail closed (mirrors pip-audit expiry enforcement)."""
    allowlist = tmp_path / "trivy-allowlist.toml"
    allowlist.write_text(
        textwrap.dedent(
            """\
            [[ignore]]
            vuln_id = "CVE-2026-EXPIRED"
            image = "ghcr.io/sevn-bot/sevn/proxy"
            reason = "Expired row must fail the helper"
            ticket = "https://github.com/sevn-bot/sevn/issues/173"
            review_by = "2020-01-01"
            """
        ),
        encoding="utf-8",
    )
    proc = _run_trivy_ignore_args(allowlist=allowlist)
    assert proc.returncode != 0
    assert "expired" in proc.stderr.lower() or "review_by" in proc.stderr.lower()


@pytest.mark.xfail(reason="green after W11", strict=False)
def test_scan_image_runs_trivy_before_cosign_sign() -> None:
    """W9.5 / D23: scan must block signing — trivy precedes ``cosign sign`` in ``scan_image()``."""
    body = _scan_image_body()
    trivy_pos = body.find("trivy")
    cosign_pos = body.find("cosign sign")
    assert trivy_pos != -1
    assert cosign_pos != -1
    assert trivy_pos < cosign_pos


@pytest.mark.xfail(reason="green after W11", strict=False)
def test_scan_image_trivy_uses_blocking_exit_code() -> None:
    """W9.5 / D23: trivy scan uses ``--exit-code 1`` for CRITICAL/HIGH findings."""
    body = _scan_image_body()
    assert "--exit-code 1" in body
    assert "--exit-code 0" not in body
