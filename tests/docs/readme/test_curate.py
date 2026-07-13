"""Tests for the agent-driven curation driver (`sevn.docs.readme.curate`)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sevn.docs.readme import curate as curate_mod
from sevn.docs.readme.curate import (
    RunnerKind,
    _glob_to_pathspec,
    _sanitize_runner_output,
    build_prompt,
    curate_entry,
    diff_for_globs,
    resolve_runner,
)
from sevn.docs.readme.manifest import ReadmeEntry

if TYPE_CHECKING:
    import pytest

REPO = Path(__file__).resolve().parents[3]


def _curated_entry(output: str, template: str) -> ReadmeEntry:
    return ReadmeEntry(
        slug="gateway",
        title="Gateway",
        summary="control plane",
        profile="subsystem",
        tier_owner="gateway",
        output=output,
        source_globs=("src/sevn/gateway/**",),
        specs=(),
        curated=True,
        template=template,
    )


def test_glob_to_pathspec_strips_wildcards() -> None:
    assert _glob_to_pathspec("src/sevn/gateway/**") == "src/sevn/gateway"
    assert _glob_to_pathspec("src/sevn/config/sections/x.py") == "src/sevn/config/sections/x.py"


def test_runner_command_shapes() -> None:
    claude = RunnerKind("claude", "claude").command()
    assert claude[:2] == ["claude", "-p"]
    assert "acceptEdits" in claude
    cursor = RunnerKind("cursor", "cursor-agent").command(model="sonnet")
    assert cursor[0] == "cursor-agent"
    assert "--force" in cursor
    assert "--model" in cursor
    assert "sonnet" in cursor


def test_resolve_runner_none_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(curate_mod.shutil, "which", lambda _bin: None)
    monkeypatch.delenv("SEVN_README_RUNNER", raising=False)
    assert resolve_runner("auto") is None


def test_resolve_runner_prefers_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(curate_mod.shutil, "which", lambda binary: "/usr/bin/" + binary)
    runner = resolve_runner("claude")
    assert runner is not None
    assert runner.name == "claude"


def test_sanitize_runner_output_redacts_secrets() -> None:
    assert _sanitize_runner_output("token=abc123") == "<redacted>"
    assert _sanitize_runner_output("Bearer sk-live-abc123xyz") == "<redacted>"
    assert _sanitize_runner_output("") == "(no output)"


def test_build_prompt_contains_contract_and_diff() -> None:
    prompt = build_prompt(
        slug="gateway",
        output="docs/readmes/gateway.md",
        template_text="# <Title>\n## References\n",
        diff="diff --git a b",
        summary="control plane",
    )
    assert "Edit exactly ONE file" in prompt
    assert "docs/readmes/gateway.md" in prompt
    assert "Template outline" in prompt
    assert "diff --git" in prompt
    assert "control plane" in prompt


def test_diff_for_globs_returns_str() -> None:
    assert isinstance(diff_for_globs(REPO, ("pyproject.toml",)), str)


def test_curate_entry_dry_run() -> None:
    entry = _curated_entry("docs/readmes/gateway.md", "docs/readmes/_templates/gateway.md")
    result = curate_entry(REPO, entry, dry_run=True)
    assert result.status == "dry-run"
    assert result.ok
    assert "Template outline" in result.prompt


def test_curate_entry_non_curated_skips() -> None:
    entry = ReadmeEntry(
        slug="storage",
        title="Storage",
        summary="s",
        profile="subsystem",
        tier_owner="t",
        output="docs/readmes/storage.md",
        source_globs=("src/sevn/storage/**",),
        specs=(),
        curated=False,
    )
    result = curate_entry(REPO, entry, dry_run=True)
    assert result.status == "skipped"
    assert "not curated" in result.detail


def test_curate_entry_no_runner_skips(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    template = tmp_path / "t.md"
    template.write_text("# <T>\n## References\n", encoding="utf-8")
    readme = tmp_path / "r.md"
    readme.write_text("# G\n## References\n", encoding="utf-8")
    entry = _curated_entry("r.md", "t.md")
    monkeypatch.setattr(curate_mod, "resolve_runner", lambda _p=None: None)
    result = curate_entry(tmp_path, entry)
    assert result.status == "skipped"
    assert "no agent runner" in result.detail


def test_curate_entry_updated_and_validated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template = tmp_path / "t.md"
    template.write_text("# <T>\n## Level 1 — Overview (non-technical)\n## References\n", "utf-8")
    readme = tmp_path / "r.md"
    readme.write_text("# G\n## Level 1 — Overview (non-technical)\n## References\n", "utf-8")
    entry = _curated_entry("r.md", "t.md")

    def fake_invoke(_runner, _prompt, **_kw):  # type: ignore[no-untyped-def]
        readme.write_text(
            "# G\n## Level 1 — Overview (non-technical)\nnew prose\n## References\n", "utf-8"
        )
        return True, ""

    monkeypatch.setattr(
        curate_mod, "resolve_runner", lambda _p=None: RunnerKind("claude", "claude")
    )
    monkeypatch.setattr(curate_mod, "invoke_runner", fake_invoke)
    result = curate_entry(tmp_path, entry)
    assert result.status == "updated"
    assert result.template_errors == []


def test_curate_entry_invalid_on_template_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template = tmp_path / "t.md"
    template.write_text("# <T>\n## Level 2 — How it works (technical)\n## References\n", "utf-8")
    readme = tmp_path / "r.md"
    readme.write_text("# G\n## Level 2 — How it works (technical)\n## References\n", "utf-8")
    entry = _curated_entry("r.md", "t.md")

    def fake_invoke(_runner, _prompt, **_kw):  # type: ignore[no-untyped-def]
        readme.write_text("# G\n## References\n", "utf-8")  # dropped a required heading
        return True, ""

    monkeypatch.setattr(
        curate_mod, "resolve_runner", lambda _p=None: RunnerKind("claude", "claude")
    )
    monkeypatch.setattr(curate_mod, "invoke_runner", fake_invoke)
    result = curate_entry(tmp_path, entry)
    assert result.status == "invalid"
    assert not result.ok
    assert any("Level 2" in e for e in result.template_errors)
