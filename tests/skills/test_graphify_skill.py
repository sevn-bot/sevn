"""Bundled ``graphify`` skill script subprocess tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "graphify"
)
_SCRIPTS = _SKILL_ROOT / "scripts"
_BUILD_SCRIPT = _SCRIPTS / "build.py"


def _install_fake_graphify(tmp_path: Path, *, stdout: bytes = b"graphify build complete") -> Path:
    """Write a stub ``graphify`` executable under ``tmp_path/bin`` for subprocess tests."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    graphify = bin_dir / "graphify"
    graphify.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if len(sys.argv) < 2 or sys.argv[1] != 'build':\n"
        "    sys.stderr.write('graphify: expected build subcommand\\n')\n"
        "    raise SystemExit(2)\n"
        f"sys.stdout.buffer.write({stdout!r})\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    graphify.chmod(0o755)
    return bin_dir


def _run_build(
    workspace: Path,
    cli_args: list[str],
    *,
    path_prefix: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    """Run ``build.py`` and parse its JSON stdout envelope."""
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    env.pop("SEVN_GRAPHIFY_DRY_RUN", None)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(_BUILD_SCRIPT), *cli_args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def test_build_dry_run_flag_returns_argv_plan(tmp_path: Path) -> None:
    """``build.py --dry-run`` returns argv plan without invoking graphify."""
    code, payload = _run_build(
        tmp_path,
        [
            "--dry-run",
            "--profile-id",
            "default",
            "--root",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
        ],
        path_prefix=Path(),
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "dry_run"
    argv = data.get("argv")
    assert isinstance(argv, list)
    assert argv[:4] == ["graphify", "build", "--root", str(tmp_path)]


def test_build_dry_run_via_env(tmp_path: Path) -> None:
    """``SEVN_GRAPHIFY_DRY_RUN=1`` selects dry-run without ``--dry-run``."""
    code, payload = _run_build(
        tmp_path,
        [
            "--profile-id",
            "alpha",
            "--root",
            str(tmp_path),
            "--output",
            str(tmp_path / ".index" / "graphify"),
        ],
        path_prefix=Path(),
        extra_env={"SEVN_GRAPHIFY_DRY_RUN": "1"},
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "dry_run"
    assert data.get("profile_id") == "alpha"


def test_build_live_with_fake_graphify(tmp_path: Path) -> None:
    """Live mode runs stub ``graphify build`` when present on PATH."""
    fake_bin = _install_fake_graphify(tmp_path)
    out_dir = tmp_path / ".index" / "graphify"
    code, payload = _run_build(
        tmp_path,
        [
            "--profile-id",
            "default",
            "--root",
            str(tmp_path),
            "--output",
            str(out_dir),
        ],
        path_prefix=fake_bin,
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "live"
    assert "graphify build complete" in str(data.get("stdout", ""))


def test_build_missing_graphify_returns_dependency_envelope(tmp_path: Path) -> None:
    """Live mode without ``graphify`` on PATH returns ``DEPENDENCY_MISSING``."""
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(tmp_path)
    env["PATH"] = ""
    env.pop("SEVN_GRAPHIFY_DRY_RUN", None)
    proc = subprocess.run(
        [
            sys.executable,
            str(_BUILD_SCRIPT),
            "--root",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    assert proc.returncode != 0
    assert payload.get("ok") is False
    assert payload.get("code") == "DEPENDENCY_MISSING"
    assert "graphify" in str(payload.get("error", ""))


@pytest.mark.integration
def test_build_live_real_graphify(tmp_path: Path) -> None:
    """Optional live smoke when ``SEVN_GRAPHIFY_LIVE=1`` and real CLI is installed."""
    if os.environ.get("SEVN_GRAPHIFY_LIVE", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("set SEVN_GRAPHIFY_LIVE=1 to run real graphify build smoke")

    from shutil import which

    if which("graphify") is None:
        pytest.skip("graphify CLI not installed")

    out_dir = tmp_path / ".index" / "graphify"
    code, payload = _run_build(
        tmp_path,
        [
            "--profile-id",
            "default",
            "--root",
            str(tmp_path),
            "--output",
            str(out_dir),
            "--flag",
            "--no-viz",
        ],
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "live"
