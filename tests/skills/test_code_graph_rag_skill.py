"""Bundled ``code_graph_rag`` skill script subprocess tests."""

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
    / "code_graph_rag"
)
_SCRIPTS = _SKILL_ROOT / "scripts"


def _install_fake_cgr(tmp_path: Path, *, stdout: bytes = b'{"fresh":true}') -> Path:
    """Write a stub ``cgr`` executable under ``tmp_path/bin`` for subprocess tests."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    cgr = bin_dir / "cgr"
    cgr.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.buffer.write({stdout!r})\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    cgr.chmod(0o755)
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


def test_read_export_reads_cached_file(tmp_path: Path) -> None:
    """``read_export.py`` returns a capped preview from ``.index/code_graph_rag/export.json``."""
    export_dir = tmp_path / ".index" / "code_graph_rag"
    export_dir.mkdir(parents=True)
    export_path = export_dir / "export.json"
    export_path.write_text('{"nodes":[{"id":"a"}]}', encoding="utf-8")

    code, payload = _run_script("read_export.py", tmp_path, ["--max-bytes", "4096"])
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("bytes", 0) > 0
    assert "nodes" in str(data.get("preview", ""))


def test_cgr_cli_rejects_disallowed_subcommand(tmp_path: Path) -> None:
    """``cgr_cli.py`` rejects argv outside the allowlist before subprocess."""
    script = _SCRIPTS / "cgr_cli.py"
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(script), "shell"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode != 0


def test_cgr_cli_runs_allowlisted_subcommand(tmp_path: Path) -> None:
    """``cgr_cli.py`` wraps allowlisted ``cgr`` subcommands (stub ``cgr`` on PATH)."""
    fake_bin = _install_fake_cgr(tmp_path, stdout=b'{"exported":true}')
    code, payload = _run_script(
        "cgr_cli.py",
        tmp_path,
        ["export"],
        path_prefix=fake_bin,
    )

    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("subcommand") == "export"
    assert "exported" in str(data.get("stdout", ""))


def test_read_export_invokes_cgr_when_cache_missing(tmp_path: Path) -> None:
    """``read_export.py`` runs ``cgr export`` when no cached export exists."""
    fake_bin = _install_fake_cgr(tmp_path, stdout=b'{"fresh":true}')
    code, payload = _run_script("read_export.py", tmp_path, path_prefix=fake_bin)

    assert code == 0
    assert payload.get("ok") is True
    cached = tmp_path / ".index" / "code_graph_rag" / "export.json"
    assert cached.is_file()
    data = payload.get("data")
    assert isinstance(data, dict)
    assert "fresh" in str(data.get("preview", ""))
