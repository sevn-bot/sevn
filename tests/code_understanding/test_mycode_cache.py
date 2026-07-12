"""MYCODE scan cache (`specs/28-code-understanding.md` §11)."""

from __future__ import annotations

import time
from pathlib import Path

from sevn.code_understanding.mycode_cache import cache_path_for_root, scan_repo_cached


def test_scan_repo_cached_hits_cache(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    first = scan_repo_cached(root, [])
    cache = cache_path_for_root(root)
    assert cache.is_file()
    second = scan_repo_cached(root, [])
    assert second.files == first.files
    (root / "b.py").write_text("y = 2\n", encoding="utf-8")
    time.sleep(0.01)
    third = scan_repo_cached(root, [])
    assert len(third.files) == 2
