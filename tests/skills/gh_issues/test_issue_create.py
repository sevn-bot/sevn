"""RED suite for templated GitHub issue create via ``gh`` (D12; green after W5)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest  # noqa: TC002 — annotations for MonkeyPatch/CaptureFixture after W5 un-xfail

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GH_ISSUES_ROOT = _REPO_ROOT / "src" / "sevn" / "data" / "bundled_skills" / "core" / "gh-issues"
_CREATE_SCRIPT = _GH_ISSUES_ROOT / "scripts" / "issue_create.py"


def _load_issue_create() -> Any:
    spec = importlib.util.spec_from_file_location("gh_issues_issue_create", _CREATE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _workspace_with_repo(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gateway": {"token": "a" * 64},
                "my_sevn": {"repo_url": "https://github.com/sevn-bot/sevn"},
            }
        ),
        encoding="utf-8",
    )
    return workspace


def test_d12_templates_exist_with_placeholders() -> None:
    """D12: ``templates/{feature,bug,chore}.md`` exist with required placeholders."""
    templates = _GH_ISSUES_ROOT / "templates"
    for name in ("feature", "bug", "chore"):
        path = templates / f"{name}.md"
        assert path.is_file(), f"missing {path}"
        text = path.read_text(encoding="utf-8")
        for placeholder in (
            "{{title}}",
            "{{summary}}",
            "{{context}}",
            "{{acceptance_criteria}}",
            "{{source}}",
            "{{labels}}",
        ):
            assert placeholder in text, f"{name}.md missing {placeholder}"


def test_d12_single_call_template_invokes_gh_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D12: one templated create → ``gh issue create --repo sevn-bot/sevn --body-file …`` once."""
    workspace = _workspace_with_repo(tmp_path)
    monkeypatch.setenv("SEVN_WORKSPACE", str(workspace))
    monkeypatch.delenv("SEVN_PROXY_URL", raising=False)

    gh_calls: list[list[str]] = []

    def _fake_run(cmd: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = [str(c) for c in cmd] if isinstance(cmd, (list, tuple)) else [str(cmd)]
        if argv and (argv[0] == "gh" or argv[0].endswith("/gh")):
            gh_calls.append(argv)
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="https://github.com/sevn-bot/sevn/issues/99\n",
                stderr="",
            )
        raise AssertionError(f"unexpected subprocess: {argv}")

    mod = _load_issue_create()
    with patch("subprocess.run", side_effect=_fake_run):
        code = mod.main(
            [
                "--template",
                "feature",
                "--title",
                "Feature X",
                "--summary",
                "do the thing",
                "--context",
                "from session",
                "--acceptance",
                "- green",
                "--source",
                "telegram:test",
            ]
        )
    assert code == 0
    assert len(gh_calls) == 1
    cmd = gh_calls[0]
    assert "issue" in cmd
    assert "create" in cmd
    assert "--repo" in cmd
    assert cmd[cmd.index("--repo") + 1] == "sevn-bot/sevn"
    assert "--body-file" in cmd
    assert "--title" in cmd


def test_d12_omitted_repo_defaults_from_my_sevn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D12/D9: ``--repo`` omitted → default from ``my_sevn.repo_url``."""
    workspace = _workspace_with_repo(tmp_path)
    monkeypatch.setenv("SEVN_WORKSPACE", str(workspace))

    captured: list[list[str]] = []

    def _fake_run(cmd: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = [str(c) for c in cmd] if isinstance(cmd, (list, tuple)) else [str(cmd)]
        captured.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="https://github.com/sevn-bot/sevn/issues/42\n",
            stderr="",
        )

    mod = _load_issue_create()
    with patch("subprocess.run", side_effect=_fake_run):
        code = mod.main(["--template", "feature", "--title", "T", "--summary", "S"])
    assert code == 0
    assert any("--repo" in c and "sevn-bot/sevn" in c for c in captured)


def test_d12_gh_auth_error_is_precise_not_proxy_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D12: map gh auth failures to precise text — never bare ``proxy status 404``."""
    workspace = _workspace_with_repo(tmp_path)
    monkeypatch.setenv("SEVN_WORKSPACE", str(workspace))

    def _fake_run(cmd: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = [str(c) for c in cmd] if isinstance(cmd, (list, tuple)) else [str(cmd)]
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout="",
            stderr="To get started with GitHub CLI, please run: gh auth login\n",
        )

    mod = _load_issue_create()
    with patch("subprocess.run", side_effect=_fake_run):
        code = mod.main(["sevn-bot/sevn", "--template", "bug", "--title", "B", "--summary", "S"])
    assert code != 0
    out = capsys.readouterr().out
    payload = json.loads(out.strip() or "{}")
    err = str(payload.get("error") or payload)
    assert "proxy status 404" not in err.lower()
    assert "gh not authenticated" in err.lower() or "gh auth login" in err.lower()


def test_d12_gh_absent_falls_back_to_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D12: when ``gh`` binary is absent, fall back to the existing proxy backend."""
    workspace = _workspace_with_repo(tmp_path)
    monkeypatch.setenv("SEVN_WORKSPACE", str(workspace))
    monkeypatch.setenv("SEVN_PROXY_URL", "http://127.0.0.1:9")

    def _no_gh(cmd: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = [str(c) for c in cmd] if isinstance(cmd, (list, tuple)) else [str(cmd)]
        if argv and (argv[0] == "gh" or argv[0].endswith("/gh")):
            raise FileNotFoundError(argv[0])
        raise AssertionError(f"unexpected subprocess: {argv}")

    mod = _load_issue_create()
    with patch("subprocess.run", side_effect=_no_gh):
        # Proxy may fail to connect; the important contract is that we attempted fallback
        # rather than crashing on missing ``gh``.
        code = mod.main(["sevn-bot/sevn", "--template", "chore", "--title", "C", "--summary", "S"])
    out = capsys.readouterr().out
    payload = json.loads(out.strip() or "{}")
    assert code in (0, 1)
    assert "No such file or directory" not in str(payload)
    # Envelope is present either way.
    assert "ok" in payload or "error" in payload or payload.get("url")
