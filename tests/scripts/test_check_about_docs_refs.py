"""Test reference guard hook for about-docs system."""

from scripts.check_about_docs_refs import find_violations, load_allowlist


def test_load_allowlist_ignores_comments_and_blanks(tmp_path):
    """load_allowlist strips comments and blank lines."""
    allowlist_file = tmp_path / "allowed-refs.txt"
    allowlist_file.write_text(
        "# This is a comment\n"
        "src/**\n"
        "\n"
        "# Another comment\n"
        "wave-orchestrator/**\n"
        "about-sevn.bot/**\n"
    )

    result = load_allowlist(allowlist_file)
    assert len(result) == 3
    assert "src/**" in result
    assert "wave-orchestrator/**" in result
    assert "about-sevn.bot/**" in result
    assert not any("#" in pattern for pattern in result)


def test_real_source_path_allowed(tmp_path):
    """A doc citing a file that exists and matches allowlist should pass."""
    # Set up repo structure
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    src_dir = repo_dir / "src" / "sevn" / "gateway"
    src_dir.mkdir(parents=True)
    (src_dir / "agent_turn.py").touch()

    allowlist_file = repo_dir / "about-sevn.bot" / "_docsys" / "allowed-refs.txt"
    allowlist_file.parent.mkdir(parents=True)
    allowlist_file.write_text("src/**\nwave-orchestrator/**\n")

    doc_file = repo_dir / "about-sevn.bot" / "specs" / "17-gateway.md"
    doc_file.parent.mkdir(parents=True)
    doc_file.write_text(
        "---\nid: spec-17-gateway\nkind: spec\n---\n\nSee [code](src/sevn/gateway/agent_turn.py)\n"
    )

    violations = find_violations(doc_file, allowlist_file, repo_dir)
    assert violations == [], f"Unexpected violations: {violations}"


def test_path_outside_allowlist_flagged(tmp_path):
    """A doc citing a path not in allowlist should be flagged."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # Create the allowlist
    allowlist_file = repo_dir / "about-sevn.bot" / "_docsys" / "allowed-refs.txt"
    allowlist_file.parent.mkdir(parents=True)
    allowlist_file.write_text("src/**\nwave-orchestrator/**\n")

    # Create a doc that cites a path outside allowlist
    doc_file = repo_dir / "about-sevn.bot" / "specs" / "17-gateway.md"
    doc_file.parent.mkdir(parents=True)
    doc_file.write_text(
        "---\nid: spec-17-gateway\nkind: spec\n---\n\nSee [design](plan/secret.md)\n"
    )

    violations = find_violations(doc_file, allowlist_file, repo_dir)
    assert len(violations) > 0, "Expected violations for path outside allowlist"
    assert any("plan/secret.md" in str(v) for v in violations)


def test_allowed_root_but_missing_file_flagged(tmp_path):
    """A path in allowed root but missing on disk should be flagged."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    allowlist_file = repo_dir / "about-sevn.bot" / "_docsys" / "allowed-refs.txt"
    allowlist_file.parent.mkdir(parents=True)
    allowlist_file.write_text("src/**\nwave-orchestrator/**\n")

    # Doc cites a file in allowed root that does not exist
    doc_file = repo_dir / "about-sevn.bot" / "specs" / "17-gateway.md"
    doc_file.parent.mkdir(parents=True)
    doc_file.write_text(
        "---\nid: spec-17-gateway\nkind: spec\n---\n\nSee [code](src/sevn/does_not_exist.py)\n"
    )

    violations = find_violations(doc_file, allowlist_file, repo_dir)
    assert len(violations) > 0, "Expected violations for missing file"
    assert any("does_not_exist.py" in str(v) for v in violations)


def test_https_url_not_flagged(tmp_path):
    """https:// URLs should never be flagged."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    allowlist_file = repo_dir / "about-sevn.bot" / "_docsys" / "allowed-refs.txt"
    allowlist_file.parent.mkdir(parents=True)
    allowlist_file.write_text("src/**\n")

    doc_file = repo_dir / "about-sevn.bot" / "specs" / "17-gateway.md"
    doc_file.parent.mkdir(parents=True)
    doc_file.write_text(
        "---\n"
        "id: spec-17-gateway\n"
        "kind: spec\n"
        "---\n"
        "\n"
        "See [docs](https://example.com/page) for details\n"
    )

    violations = find_violations(doc_file, allowlist_file, repo_dir)
    assert violations == [], f"https URLs should not be flagged: {violations}"


def test_doc_id_link_not_flagged(tmp_path):
    """Doc-to-doc links by id (not path) should never be flagged."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    allowlist_file = repo_dir / "about-sevn.bot" / "_docsys" / "allowed-refs.txt"
    allowlist_file.parent.mkdir(parents=True)
    allowlist_file.write_text("src/**\n")

    doc_file = repo_dir / "about-sevn.bot" / "specs" / "17-gateway.md"
    doc_file.parent.mkdir(parents=True)
    doc_file.write_text(
        "---\n"
        "id: spec-17-gateway\n"
        "kind: spec\n"
        "---\n"
        "\n"
        "See [spec-18-channel-telegram](spec-18-channel-telegram) for related\n"
    )

    violations = find_violations(doc_file, allowlist_file, repo_dir)
    assert violations == [], f"Doc-id links should not be flagged: {violations}"


def test_editing_allowlist_changes_result(tmp_path):
    """Editing the allowlist file should affect future checks."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # Create an extra docs directory
    extra_dir = repo_dir / "docs" / "extra"
    extra_dir.mkdir(parents=True)
    (extra_dir / "x.md").touch()

    allowlist_file = repo_dir / "about-sevn.bot" / "_docsys" / "allowed-refs.txt"
    allowlist_file.parent.mkdir(parents=True)
    # Start with base allowlist (no docs/**)
    allowlist_file.write_text("src/**\n")

    doc_file = repo_dir / "about-sevn.bot" / "specs" / "17-gateway.md"
    doc_file.parent.mkdir(parents=True)
    doc_file.write_text(
        "---\nid: spec-17-gateway\nkind: spec\n---\n\nSee [docs](docs/extra/x.md)\n"
    )

    # Should be flagged initially (docs/** not in allowlist)
    violations_before = find_violations(doc_file, allowlist_file, repo_dir)
    assert len(violations_before) > 0, "docs/extra/x.md should be flagged before allowlist update"

    # Add docs/** to allowlist
    allowlist_file.write_text("src/**\ndocs/**\n")

    # Should now pass
    violations_after = find_violations(doc_file, allowlist_file, repo_dir)
    assert violations_after == [], (
        f"docs/extra/x.md should be allowed after allowlist update: {violations_after}"
    )
