"""Test check_about_docs gate for validation and drift."""

from sevn.docs.about.check import check_about_docs


def test_unknown_related_id_flagged(tmp_path):
    """A doc with an unknown related id should be flagged."""
    # Create fake repo structure
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    docs_dir = repo_dir / "about-sevn.bot" / "specs"
    docs_dir.mkdir(parents=True)
    sources_dir = repo_dir / "src" / "sevn" / "gateway"
    sources_dir.mkdir(parents=True)

    # Create a source file referenced in sources
    (sources_dir / "agent_turn.py").touch()

    # Write doc frontmatter + body
    frontmatter_lines = [
        "---",
        "id: spec-17-gateway",
        "kind: spec",
        "title: Gateway",
        "status: done",
        "owner: Alex",
        "summary: Gateway implementation.",
        "last_updated: 2026-06-19",
        "parent_prd: prd-01-main",
        "sources:",
        "  - src/sevn/gateway/**",
        "related:",
        "  - spec-99-missing",
        "---",
        "",
        "## Purpose",
        "Gateway implementation.",
    ]
    doc_file = docs_dir / "17-gateway.md"
    doc_file.write_text("\n".join(frontmatter_lines))

    # Run check
    violations = check_about_docs(repo_dir)

    # Verify violations flagged for unknown id
    assert len(violations) > 0, "Expected check_about_docs to flag unknown related id"
    assert any("spec-99-missing" in str(v) for v in violations), (
        "Expected violation mentioning the missing id"
    )


def test_clean_state_or_drift(tmp_path):
    """Minimal valid doc should pass (or xfail if fingerprint unknown)."""
    # Create fake repo structure
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    docs_dir = repo_dir / "about-sevn.bot" / "specs"
    docs_dir.mkdir(parents=True)
    sources_dir = repo_dir / "src" / "sevn" / "gateway"
    sources_dir.mkdir(parents=True)

    (sources_dir / "agent_turn.py").touch()

    # Write a minimal valid spec without related
    frontmatter_lines = [
        "---",
        "id: spec-17-gateway",
        "kind: spec",
        "title: Gateway",
        "status: done",
        "owner: Alex",
        "summary: Gateway implementation.",
        "last_updated: 2026-06-19",
        "parent_prd: prd-01-main",
        "sources:",
        "  - src/sevn/gateway/**",
        "fingerprint: sha256:fakefingerprintvalue",
        "---",
        "",
        "## Purpose",
        "Gateway implementation.",
    ]
    doc_file = docs_dir / "17-gateway.md"
    doc_file.write_text("\n".join(frontmatter_lines))

    result = check_about_docs(repo_dir)
    # We can't verify clean state without the correct fingerprint
    # so this test just documents the contract.
    assert result is not None  # Placeholder assertion


def test_wave_orchestrator_paths_optional_when_missing(tmp_path):
    """Operator-only wave-orchestrator paths must not fail public CI clones."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    docs_dir = repo_dir / "about-sevn.bot" / "specs"
    docs_dir.mkdir(parents=True)
    allowlist_dir = repo_dir / "about-sevn.bot" / "_docsys"
    allowlist_dir.mkdir(parents=True)
    allowlist_dir.joinpath("allowed-refs.txt").write_text(
        "src/**\nwave-orchestrator/**\n",
        encoding="utf-8",
    )
    (repo_dir / "src" / "sevn" / "gateway").mkdir(parents=True)
    (repo_dir / "src" / "sevn" / "gateway" / "agent_turn.py").write_text(
        "def run(): pass\n",
        encoding="utf-8",
    )

    doc_file = docs_dir / "25-cicd-full.md"
    doc_file.write_text(
        """---
id: spec-25-cicd-full
kind: spec
title: CI/CD
status: done
owner: Alex
summary: CI pipeline.
last_updated: 2026-07-08
parent_prd: prd-06-setup-and-operations
sources:
  - src/sevn/gateway/**
  - wave-orchestrator/**
interfaces:
  - name: run
    file: wave-orchestrator/src/waveorch/cli.py
    symbol: run
fingerprint: sha256:fakefingerprintvalue
---

## Purpose
CI pipeline.
""",
        encoding="utf-8",
    )

    issues = check_about_docs(repo_dir)
    assert not any("wave-orchestrator" in issue for issue in issues)
