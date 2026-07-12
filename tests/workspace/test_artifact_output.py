"""Artifact output directory confinement (`live-session-2026-06-05` P10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig, WorkspaceOutputSectionConfig
from sevn.pdf.paths import resolve_path_under_workspace
from sevn.workspace.artifact_output import (
    artifact_output_prefix,
    is_protected_structured_root_path,
    rebase_artifact_relative_path,
)


def test_rebase_bare_relative_path_under_prefix() -> None:
    assert rebase_artifact_relative_path("report.pdf", "out/sess") == "out/sess/report.pdf"


def test_rebase_keeps_path_already_under_prefix() -> None:
    assert rebase_artifact_relative_path("out/sess/a.pdf", "out/sess") == "out/sess/a.pdf"


def test_rebase_rejects_parent_traversal() -> None:
    with pytest.raises(ValueError, match="escapes workspace root"):
        rebase_artifact_relative_path("../report.pdf", "out/sess")


def test_rebase_rejects_absolute_path() -> None:
    with pytest.raises(ValueError, match="must be workspace-relative"):
        rebase_artifact_relative_path("/tmp/report.pdf", "out/sess")


def test_protected_structured_root_paths() -> None:
    assert is_protected_structured_root_path("SOUL.md")
    assert not is_protected_structured_root_path("memory/2026-06-05.md")
    assert not is_protected_structured_root_path("openclaw.md")


def test_artifact_output_prefix_per_session_default() -> None:
    assert artifact_output_prefix(None, "web:abc") == "out/web_abc"


def test_artifact_output_prefix_flat_when_disabled(tmp_path: Path) -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace=WorkspaceOutputSectionConfig(output_dir="artifacts", per_session=False),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert artifact_output_prefix(cfg, "web:abc") == "artifacts"


def test_resolve_path_under_workspace_artifact_mode(tmp_path: Path) -> None:
    resolved = resolve_path_under_workspace(
        tmp_path,
        "page.pdf",
        artifact=True,
        output_prefix="out/sess",
    )
    assert resolved == tmp_path.resolve() / "out" / "sess" / "page.pdf"
