"""CLI tests for ``sevn second-brain`` and ``sevn config second-brain``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def _install_home(tmp_path: Path, doc: dict[str, object]) -> Path:
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(json.dumps(doc), encoding="utf-8")
    return home


def test_second_brain_setup_creates_custom_vault(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_home(
        tmp_path,
        {"schema_version": 1, "gateway": {"token": "test-token-1234567890"}},
    )
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(
        get_command(app),
        ["second-brain", "setup", "--vault", "obsidian/test", "--no-model"],
    )
    assert result.exit_code == 0, result.stdout
    sj = home / "workspace" / "sevn.json"
    doc = json.loads(sj.read_text(encoding="utf-8"))
    assert doc["second_brain"]["enabled"] is True
    assert doc["second_brain"]["paths"]["vault"] == "obsidian/test"
    assert (home / "workspace" / "obsidian" / "test" / "wiki" / "index.md").is_file()


def test_config_second_brain_shows_vault_line(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_home(
        tmp_path,
        {
            "schema_version": 1,
            "gateway": {"token": "test-token-1234567890"},
            "second_brain": {
                "enabled": True,
                "paths": {"vault": "obsidian/alex_AI"},
            },
        },
    )
    ws = home / "workspace"
    (ws / "obsidian" / "alex_AI" / "wiki").mkdir(parents=True)
    (ws / "obsidian" / "alex_AI" / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(get_command(app), ["config", "second-brain"])
    assert result.exit_code == 0, result.stdout
    assert "obsidian/alex_AI" in result.stdout


def test_second_brain_setup_layout_para(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_home(
        tmp_path,
        {"schema_version": 1, "gateway": {"token": "test-token-1234567890"}},
    )
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(
        get_command(app),
        ["second-brain", "setup", "--vault", "obsidian/x", "--layout", "para", "--no-model"],
    )
    assert result.exit_code == 0, result.stdout
    doc = json.loads((home / "workspace" / "sevn.json").read_text(encoding="utf-8"))
    assert doc["second_brain"]["layout"] == "para"
    assert "para" in doc["second_brain"]
    vault = home / "workspace" / "obsidian" / "x"
    assert (vault / "00_Inbox").is_dir()
    assert (vault / "index.md").is_file()
    assert "00_Inbox" in result.stdout or "capture" in result.stdout.lower()


def test_second_brain_setup_layout_auto_detects_para(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_home(
        tmp_path,
        {"schema_version": 1, "gateway": {"token": "test-token-1234567890"}},
    )
    ws = home / "workspace"
    vault = ws / "obsidian" / "alex_AI"
    (vault / "00_Inbox").mkdir(parents=True)
    (vault / "10_Projects").mkdir()
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(
        get_command(app),
        ["second-brain", "setup", "--vault", "obsidian/alex_AI", "--layout", "auto", "--no-model"],
    )
    assert result.exit_code == 0, result.stdout
    doc = json.loads((ws / "sevn.json").read_text(encoding="utf-8"))
    assert doc["second_brain"]["layout"] == "para"


def test_config_second_brain_json_includes_layout_roles(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_home(
        tmp_path,
        {
            "schema_version": 1,
            "gateway": {"token": "test-token-1234567890"},
            "second_brain": {
                "enabled": True,
                "layout": "para",
                "paths": {"vault": "obsidian/alex_AI"},
                "para": {
                    "inbox": "00_Inbox",
                    "projects": "10_Projects",
                    "areas": "20_Areas",
                    "resources": "30_Resources",
                },
            },
        },
    )
    ws = home / "workspace"
    (ws / "obsidian" / "alex_AI" / "00_Inbox").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(get_command(app), ["config", "second-brain", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    data = payload["data"]
    assert data["layout"] == "para"
    assert "roles" in data
    assert data["roles"]["capture"].endswith("00_Inbox")


def test_doctor_probe_para_layout_missing_dirs(tmp_path: Path) -> None:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.second_brain.layout_probe import probe_second_brain_vault_layout

    vault = tmp_path / "obsidian" / "alex_AI"
    (vault / "00_Inbox").mkdir(parents=True)
    cfg = WorkspaceConfig.minimal(
        second_brain={
            "enabled": True,
            "layout": "para",
            "paths": {"vault": "obsidian/alex_AI"},
        },
    )
    probe = probe_second_brain_vault_layout(config=cfg, content_root=tmp_path)
    assert probe is not None
    assert probe.ok is False
    assert probe.hint is not None
    assert "para" in probe.hint.lower()
    assert any("20_Areas" in m or "index.md" in m for m in probe.missing)


@pytest.mark.asyncio
async def test_wiki_apply_para_writes_under_resources(tmp_path: Path) -> None:
    import hashlib
    import json

    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.second_brain import wiki_apply_tool, wiki_get_tool
    from sevn.second_brain.bootstrap import ensure_second_brain_scope_layout
    from sevn.second_brain.frontmatter import compose_page
    from sevn.tools.context import ToolContext
    from sevn.tools.permissions import AllowAllPermissionPolicy

    vault = tmp_path / "obsidian" / "alex_AI"
    vault.mkdir(parents=True)
    (tmp_path / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gateway": {"token": "test-token-1234567890"},
                "second_brain": {
                    "enabled": True,
                    "layout": "para",
                    "paths": {"vault": "obsidian/alex_AI"},
                },
            },
        ),
        encoding="utf-8",
    )
    cfg = WorkspaceConfig.model_validate(json.loads((tmp_path / "sevn.json").read_text()))
    ensure_second_brain_scope_layout(vault, cfg=cfg.second_brain, copy_model=False)  # type: ignore[call-arg]
    resources = vault / "30_Resources"
    resources.mkdir(exist_ok=True)
    page = resources / "note.md"
    empty_hash = hashlib.sha256(b"").hexdigest()
    patch = compose_page({"title": "Note"}, "# Note\n")
    ctx = ToolContext(
        session_id="s",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        turn_id="t",
        executor_tier="B",
    )
    apply_out = json.loads(
        await wiki_apply_tool(ctx, path="note.md", patch=patch, base_hash=empty_hash),
    )
    assert apply_out["ok"] is True
    assert page.is_file()
    get_out = json.loads(await wiki_get_tool(ctx, path="note.md"))
    assert get_out["ok"] is True
    assert "Note" in get_out["data"]["body"]
