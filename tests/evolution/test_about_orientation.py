"""Evolution ARCHITECTURE orientation prepend (`specs/35-bot-evolution.md` EV-1)."""

from __future__ import annotations

from pathlib import Path

from sevn.code_understanding.triager_orientation import (
    infer_orientation_intent,
    orientation_block_for_workspace,
)
from sevn.config.workspace_config import MySevnWorkspaceConfig, WorkspaceConfig


def _write_sevn_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    (path / "pyproject.toml").write_text('[project]\nname = "sevn"\n', encoding="utf-8")


def test_about_architecture_prepended_for_coding_intent(tmp_path: Path) -> None:
    repo = tmp_path / "sevn.bot"
    _write_sevn_repo(repo)
    arch = repo / "evolution" / "ARCHITECTURE.md"
    arch.parent.mkdir(parents=True)
    arch.write_text("# architecture\n", encoding="utf-8")

    block = orientation_block_for_workspace(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        primary_repo_root=repo,
        intent="coding",
    )
    assert "evolution/ARCHITECTURE.md" in block
    assert block.index("evolution/ARCHITECTURE.md") < len(block)


def test_about_architecture_prepended_for_self_evolution_intent(tmp_path: Path) -> None:
    repo = tmp_path / "sevn.bot"
    _write_sevn_repo(repo)
    arch = repo / "evolution" / "ARCHITECTURE.md"
    arch.parent.mkdir(parents=True)
    arch.write_text("# architecture\n", encoding="utf-8")

    block = orientation_block_for_workspace(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        primary_repo_root=repo,
        intent="self_evolution",
    )
    assert "evolution/ARCHITECTURE.md" in block


def test_always_on_block_when_checkout_resolves(tmp_path: Path) -> None:
    repo = tmp_path / "sevn.bot"
    _write_sevn_repo(repo)
    arch = repo / "evolution" / "ARCHITECTURE.md"
    arch.parent.mkdir(parents=True)
    arch.write_text("# architecture\n", encoding="utf-8")
    block = orientation_block_for_workspace(
        WorkspaceConfig(
            schema_version=1,
            my_sevn=MySevnWorkspaceConfig(repo_path=str(repo)),
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        ),
        content_root=tmp_path / "operator-ws",
        intent=None,
    )
    assert "source_code/" in block
    assert "@repo/" not in block


def test_infer_orientation_intent_architecture_question() -> None:
    assert infer_orientation_intent("where is gateway dispatch") == "coding"


def test_about_architecture_prefers_about_tree(tmp_path: Path) -> None:
    repo = tmp_path / "sevn.bot"
    _write_sevn_repo(repo)
    about = repo / "about-sevn.bot" / "ARCHITECTURE.md"
    about.parent.mkdir(parents=True)
    about.write_text("# about\n", encoding="utf-8")
    block = orientation_block_for_workspace(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        content_root=repo,
        intent="coding",
    )
    assert "about-sevn.bot/ARCHITECTURE.md" in block
