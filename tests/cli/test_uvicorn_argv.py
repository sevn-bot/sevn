"""``sevn.cli.uvicorn_argv`` — launch from the running sevn env, not ambient PATH."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sevn.cli.uvicorn_argv import uvicorn_program_argv

if TYPE_CHECKING:
    import pytest


def test_uvicorn_argv_uses_running_interpreter_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The uvicorn binary is the sibling of ``sys.executable`` (the running sevn env).

    Guards the multi-checkout regression: a stray dev-tree ``uvicorn`` on ``PATH`` must not
    be baked into the launchd/systemd unit instead of the install env's uvicorn.
    """
    env_bin = tmp_path / "tool-env" / "bin"
    env_bin.mkdir(parents=True)
    py = env_bin / "python3"
    py.write_text("", encoding="utf-8")
    uvicorn_bin = env_bin / "uvicorn"
    uvicorn_bin.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(py))

    argv = uvicorn_program_argv(
        module="sevn.gateway.http_server:create_app", port=3001, factory=True
    )

    assert argv[0] == str(py.resolve().parent / "uvicorn")
    assert argv[1] == "sevn.gateway.http_server:create_app"
    assert "--factory" in argv
    assert argv[-2:] == ["--port", "3001"]
    assert "run" not in argv


def test_uvicorn_argv_falls_back_to_python_m_uvicorn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no sibling uvicorn, fall back to ``python -m uvicorn`` on the same interpreter."""
    py = tmp_path / "python3"
    py.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(py))

    argv = uvicorn_program_argv(module="m:app", port=8787)

    assert argv[:3] == [str(py), "-m", "uvicorn"]
