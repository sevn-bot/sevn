"""Bundled ``roam_code`` skill script subprocess tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "roam_code"
)
_SCRIPTS = _SKILL_ROOT / "scripts"


def _install_fake_roam(tmp_path: Path, *, stdout: bytes = b"auth lives in src/auth.py") -> Path:
    """Write a stub ``roam`` executable under ``tmp_path/bin`` for subprocess tests."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    roam = bin_dir / "roam"
    roam.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "cmd = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if cmd not in {'understand', 'retrieve'}:\n"
        "    sys.stderr.write('roam_code: disallowed subcommand\\n')\n"
        "    raise SystemExit(2)\n"
        f"sys.stdout.buffer.write({stdout!r})\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    roam.chmod(0o755)
    return bin_dir


def _run_script(
    script_name: str,
    workspace: Path,
    cli_args: list[str] | None = None,
    *,
    path_prefix: Path | None = None,
) -> tuple[int, dict[str, object]]:
    script = _SCRIPTS / script_name
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        [sys.executable, str(script), *(cli_args or [])],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def test_query_runs_retrieve_with_fake_roam(tmp_path: Path) -> None:
    """``query.py`` wraps ``roam retrieve`` when ``--query`` is set."""
    fake_bin = _install_fake_roam(tmp_path)
    code, payload = _run_script(
        "query.py",
        tmp_path,
        ["--query", "where is auth?"],
        path_prefix=fake_bin,
    )

    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert "auth lives" in str(data.get("text", ""))


def test_query_runs_understand_without_query(tmp_path: Path) -> None:
    """``query.py`` wraps ``roam understand`` when ``--query`` is omitted."""
    fake_bin = _install_fake_roam(tmp_path, stdout=b"repo briefing")
    code, payload = _run_script("query.py", tmp_path, path_prefix=fake_bin)

    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert "repo briefing" in str(data.get("text", ""))


def test_query_fails_when_roam_missing(tmp_path: Path) -> None:
    """``query.py`` returns failure envelope when ``roam`` is absent from PATH."""
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(tmp_path)
    env["PATH"] = ""
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "query.py"), "--query", "x"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    assert proc.returncode != 0
    assert payload.get("ok") is False
    assert "roam_code:" in str(payload.get("error", ""))
