"""RED contract tests for spec status honesty (D3/D5). Green after W8/W10.

Exports:
    test_done_status_with_scaffold_body_fails_check — done + scaffold body fails check.
    test_scaffold_status_with_scaffold_body_passes_check — scaffold status allows scaffold body.
    test_done_status_with_authored_body_passes_check — done + authored body passes check.

Examples:
    >>> len(SCAFFOLD_PHRASES)
    2
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sevn.docs.about.check import check_about_docs
from sevn.docs.about.loader import dump_doc
from sevn.docs.about.model import AboutDoc, Interface

SCAFFOLD_PHRASES = (
    "Offline scaffold for",
    "Initial draft for",
)


def _scaffold_body(phrase: str = "Offline scaffold for") -> str:
    """Build a seven-section spec body containing a scaffold phrase.

    Args:
        phrase (str, optional): Scaffold phrase to repeat. Defaults to
            ``"Offline scaffold for"``.

    Returns:
        str: Markdown body with seven required H2 sections.

    Examples:
        >>> "## Purpose" in _scaffold_body()
        True
    """
    return "\n\n".join(
        [
            "## Purpose",
            f"{phrase} gateway.",
            "## Public Interface",
            f"{phrase} gateway.",
            "## Data Model",
            f"{phrase} gateway.",
            "## Internal Architecture",
            f"{phrase} gateway.",
            "## Behavior",
            f"{phrase} gateway.",
            "## Failure Modes",
            f"{phrase} gateway.",
            "## Test Strategy",
            f"{phrase} gateway.",
        ]
    )


def _minimal_spec(*, status: str, body: str) -> AboutDoc:
    """Return a minimal gateway spec model for status-honesty tests.

    Args:
        status (str): Frontmatter status value under test.
        body (str): Markdown body paired with the status.

    Returns:
        AboutDoc: Spec model with gateway metadata.

    Examples:
        >>> doc = _minimal_spec(status="scaffold", body="## Purpose\\n")
        >>> doc.id.startswith("spec-")
        True
    """
    return AboutDoc(
        id="spec-17-gateway",
        kind="spec",
        title="Gateway",
        status=status,  # type: ignore[arg-type]
        owner="Alex",
        summary="Gateway turn spine.",
        last_updated=date(2026, 7, 14),
        parent_prd="prd-01-conversational-experience",
        sources=["src/sevn/gateway/**"],
    )


def _write_repo_spec(tmp_path: Path, *, status: str, body: str) -> Path:
    """Write a gateway spec file into a synthetic repository tree.

    Args:
        tmp_path (Path): pytest temporary directory fixture.
        status (str): Frontmatter status value under test.
        body (str): Markdown body paired with the status.

    Returns:
        Path: Written spec markdown path.

    Examples:
        >>> _write_repo_spec.__name__
        '_write_repo_spec'
    """
    docs_dir = tmp_path / "about-sevn.bot" / "specs"
    docs_dir.mkdir(parents=True)
    allowlist_dir = tmp_path / "about-sevn.bot" / "_docsys"
    allowlist_dir.mkdir(parents=True)
    allowlist_dir.joinpath("allowed-refs.txt").write_text("src/**\n", encoding="utf-8")
    module_dir = tmp_path / "src" / "sevn" / "gateway"
    module_dir.mkdir(parents=True)
    (module_dir / "agent_turn.py").write_text(
        "def run_turn() -> None:\n    pass\n", encoding="utf-8"
    )
    doc = _minimal_spec(status=status, body=body)
    path = docs_dir / "17-gateway.md"
    path.write_text(
        dump_doc(
            doc.model_copy(
                update={
                    "fingerprint": "sha256:placeholder",
                    "interfaces": [
                        Interface(
                            name="run_turn",
                            file="src/sevn/gateway/agent_turn.py",
                            symbol="run_turn",
                        )
                    ],
                }
            ),
            body,
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("phrase", SCAFFOLD_PHRASES)
def test_done_status_with_scaffold_body_fails_check(tmp_path: Path, phrase: str) -> None:
    """D3/D5: ``status: done`` cannot coexist with scaffold placeholder prose.

    Args:
        tmp_path (Path): pytest temporary directory fixture.
        phrase (str): Scaffold phrase embedded in the body.

    Examples:
        >>> SCAFFOLD_PHRASES[0]
        'Offline scaffold for'
    """
    _write_repo_spec(tmp_path, status="done", body=_scaffold_body(phrase))
    issues = check_about_docs(tmp_path)
    assert any(
        "status" in issue.lower() and ("scaffold" in issue.lower() or "honest" in issue.lower())
        for issue in issues
    ), f"expected status-honesty violation, got: {issues}"


def test_scaffold_status_with_scaffold_body_passes_check(tmp_path: Path) -> None:
    """Happy path: honest ``status: scaffold`` with placeholder body is allowed.

    Args:
        tmp_path (Path): pytest temporary directory fixture.

    Examples:
        >>> "scaffold" in {"draft", "scaffold", "done"}
        True
    """
    _write_repo_spec(tmp_path, status="scaffold", body=_scaffold_body())
    issues = check_about_docs(tmp_path)
    assert not any("status" in issue.lower() and "scaffold" in issue.lower() for issue in issues)


def test_done_status_with_authored_body_passes_check(tmp_path: Path) -> None:
    """Happy path: ``status: done`` is allowed when the body is fully authored.

    Args:
        tmp_path (Path): pytest temporary directory fixture.

    Examples:
        >>> "done" in {"draft", "scaffold", "done"}
        True
    """
    body = (
        "## Purpose\n\n"
        "Routes inbound channel messages through the gateway turn spine.\n\n"
        "## Public Interface\n\n"
        "``run_turn`` in ``agent_turn.py``.\n\n"
        "## Data Model\n\n"
        "Turn state persisted per session.\n\n"
        "## Internal Architecture\n\n"
        "Triage then tier-B/C executors.\n\n"
        "## Behavior\n\n"
        "One turn per inbound message.\n\n"
        "## Failure Modes\n\n"
        "Provider errors surface to the operator.\n\n"
        "## Test Strategy\n\n"
        "Gateway unit tests under ``tests/gateway/``."
    )
    _write_repo_spec(tmp_path, status="done", body=body)
    issues = check_about_docs(tmp_path)
    assert not any("status honesty" in issue.lower() for issue in issues)
