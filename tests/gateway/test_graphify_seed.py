"""Graphify mirror seeding: staleness gate, graceful-missing, and build paths."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from sevn.code_understanding.graphify_seed import (
    build_graphify_index,
    graphify_needs_refresh,
    graphify_report_mirror_path,
    seed_graphify_mirror,
)


def _mirror_with_py(root: Path) -> Path:
    """Create a ``source_code/`` mirror with one Python file under ``root``."""
    src = root / "source_code" / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    return root


def _write_report(root: Path, *, body: str = "# report\n") -> Path:
    report = graphify_report_mirror_path(root)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(body, encoding="utf-8")
    return report


def test_report_mirror_path_is_agent_read_path() -> None:
    assert (
        graphify_report_mirror_path(Path("/ws")).as_posix()
        == "/ws/source_code/.index/graphify/GRAPH_REPORT.md"
    )


def test_needs_refresh_missing_report(tmp_path: Path) -> None:
    _mirror_with_py(tmp_path)
    assert graphify_needs_refresh(tmp_path) is True


def test_needs_refresh_no_python_is_false(tmp_path: Path) -> None:
    # Report present, mirror exists but has no .py to graph -> nothing to rebuild.
    (tmp_path / "source_code").mkdir(parents=True)
    _write_report(tmp_path)
    assert graphify_needs_refresh(tmp_path) is False


def test_needs_refresh_report_older_than_source(tmp_path: Path) -> None:
    _mirror_with_py(tmp_path)
    report = _write_report(tmp_path)
    # Make the report older than the .py source.
    py = tmp_path / "source_code" / "src" / "a.py"
    old = 1_000.0
    new = 2_000.0
    os.utime(report, (old, old))
    os.utime(py, (new, new))
    assert graphify_needs_refresh(tmp_path) is True


def test_needs_refresh_report_newer_than_source(tmp_path: Path) -> None:
    _mirror_with_py(tmp_path)
    report = _write_report(tmp_path)
    py = tmp_path / "source_code" / "src" / "a.py"
    os.utime(py, (1_000.0, 1_000.0))
    os.utime(report, (2_000.0, 2_000.0))
    assert graphify_needs_refresh(tmp_path) is False


def test_seed_mirror_graceful_when_cli_missing(tmp_path: Path) -> None:
    _mirror_with_py(tmp_path)
    with patch("sevn.code_understanding.graphify_seed.shutil.which", return_value=None):
        assert seed_graphify_mirror(tmp_path) is False
    # No report was produced.
    assert not graphify_report_mirror_path(tmp_path).exists()


def test_seed_mirror_no_source_dir(tmp_path: Path) -> None:
    # No source_code/ mirror at all -> skip without touching graphify.
    with patch(
        "sevn.code_understanding.graphify_seed.shutil.which",
        return_value="/usr/bin/graphify",
    ) as which:
        assert seed_graphify_mirror(tmp_path) is False
    which.assert_not_called()


def test_seed_mirror_build_path_writes_report_and_symlink(tmp_path: Path) -> None:
    _mirror_with_py(tmp_path)
    source_root = tmp_path / "source_code"

    def _fake_update(argv, **_kwargs):
        # Emulate `graphify update <source_root>` writing graphify-out/.
        out = Path(argv[2]) / "graphify-out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "GRAPH_REPORT.md").write_text("# graph\n", encoding="utf-8")
        (out / "graph.json").write_text("{}", encoding="utf-8")

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Proc()

    with (
        patch(
            "sevn.code_understanding.graphify_seed.shutil.which",
            return_value="/usr/bin/graphify",
        ),
        patch(
            "sevn.code_understanding.graphify_seed.subprocess.run",
            side_effect=_fake_update,
        ),
    ):
        assert seed_graphify_mirror(tmp_path) is True

    link = source_root / ".index" / "graphify"
    assert link.is_symlink()
    assert link.readlink() == Path("..") / "graphify-out"
    # The agent-visible report resolves through the symlink.
    report = graphify_report_mirror_path(tmp_path)
    assert report.is_file()
    assert report.read_text(encoding="utf-8") == "# graph\n"


def test_seed_mirror_skips_when_current(tmp_path: Path) -> None:
    _mirror_with_py(tmp_path)
    report = _write_report(tmp_path)
    py = tmp_path / "source_code" / "src" / "a.py"
    os.utime(py, (1_000.0, 1_000.0))
    os.utime(report, (2_000.0, 2_000.0))
    with patch(
        "sevn.code_understanding.graphify_seed.shutil.which",
        return_value="/usr/bin/graphify",
    ) as which:
        assert seed_graphify_mirror(tmp_path) is False
    which.assert_not_called()


def test_build_index_returns_false_on_nonzero_exit(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "boom"

    with (
        patch(
            "sevn.code_understanding.graphify_seed.shutil.which",
            return_value="/usr/bin/graphify",
        ),
        patch(
            "sevn.code_understanding.graphify_seed.subprocess.run",
            return_value=_Proc(),
        ),
    ):
        assert build_graphify_index(tmp_path) is False


def test_build_index_missing_cli(tmp_path: Path) -> None:
    with patch("sevn.code_understanding.graphify_seed.shutil.which", return_value=None):
        assert build_graphify_index(tmp_path) is False
