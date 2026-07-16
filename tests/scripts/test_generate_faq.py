"""Tests for scripts/generate_faq.py (docs/FAQ.md generator/checker)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_faq.py"


def _load_generate_faq_main():
    if not SCRIPT_PATH.is_file():
        pytest.fail("scripts/generate_faq.py not implemented")
    spec = importlib.util.spec_from_file_location("generate_faq", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.main


def _valid_input() -> dict:
    return {
        "title": "FAQ",
        "sections": [
            {
                "id": "general",
                "title": "General",
                "questions": [
                    {
                        "id": "q1",
                        "question": "What is this project?",
                        "answer": (
                            "This is a small demo project used only to exercise the FAQ "
                            "generator's validation and rendering logic end to end here. "
                            "See {{ref:r}} for more detail."
                        ),
                        "references": {"r": {"path": "docs/target.md", "text": "target doc"}},
                    },
                ],
            },
        ],
    }


def _repo_with_input(raw: dict, repo: Path) -> Path:
    target = repo / "docs" / "target.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Target\n", encoding="utf-8")
    input_path = repo / "docs" / "faq" / "qa_input.json"
    input_path.parent.mkdir(parents=True)
    input_path.write_text(json.dumps(raw), encoding="utf-8")
    return repo


def test_main_writes_faq_when_valid(tmp_path: Path) -> None:
    """Default invocation writes docs/FAQ.md when the input JSON validates."""
    main = _load_generate_faq_main()
    repo = _repo_with_input(_valid_input(), tmp_path)
    exit_code = main([], repo_root=repo)
    assert exit_code == 0
    output = repo / "docs" / "FAQ.md"
    assert output.is_file()
    assert "What is this project?" in output.read_text(encoding="utf-8")


def test_main_check_fails_when_output_missing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    """--check fails (exit 1) when docs/FAQ.md has not been generated yet."""
    main = _load_generate_faq_main()
    repo = _repo_with_input(_valid_input(), tmp_path)
    exit_code = main(["--check"], repo_root=repo)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "stale" in captured.err.lower()


def test_main_check_passes_after_generate(tmp_path: Path) -> None:
    """--check succeeds once docs/FAQ.md matches the freshly rendered content."""
    main = _load_generate_faq_main()
    repo = _repo_with_input(_valid_input(), tmp_path)
    assert main([], repo_root=repo) == 0
    assert main(["--check"], repo_root=repo) == 0


def test_main_reports_validation_errors(
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    """An answer missing a reference placeholder fails with a clear error."""
    main = _load_generate_faq_main()
    raw = _valid_input()
    raw["sections"][0]["questions"][0]["answer"] = "Too short."
    repo = _repo_with_input(raw, tmp_path)
    exit_code = main([], repo_root=repo)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "validation failed" in captured.err.lower()


def test_main_missing_input_file(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """A missing qa_input.json fails with a clear error instead of a traceback."""
    main = _load_generate_faq_main()
    exit_code = main([], repo_root=tmp_path)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "input not found" in captured.err.lower()


def test_main_rejects_input_path_escaping_repo_root(
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    """An --input path that resolves outside the repo root is rejected, not read."""
    main = _load_generate_faq_main()
    repo = _repo_with_input(_valid_input(), tmp_path)
    outside = tmp_path.parent / "outside.json"
    outside.write_text(json.dumps(_valid_input()), encoding="utf-8")
    exit_code = main(["--input", f"../{outside.name}"], repo_root=repo)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "must resolve within the repository root" in captured.err.lower()


def test_main_rejects_output_path_escaping_repo_root(
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    """An --output path that resolves outside the repo root is rejected, not written."""
    main = _load_generate_faq_main()
    repo = _repo_with_input(_valid_input(), tmp_path)
    exit_code = main(["--output", "../outside.md"], repo_root=repo)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "must resolve within the repository root" in captured.err.lower()
    assert not (tmp_path.parent / "outside.md").exists()
