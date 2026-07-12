"""Tests for README source fingerprinting."""

from __future__ import annotations

from pathlib import Path

from sevn.docs.readme.fingerprint import (
    compute_digest,
    expand_source_globs,
    load_fingerprints,
    save_fingerprints,
    upsert_entry,
)


def test_compute_digest_is_deterministic(tmp_path: Path) -> None:
    """Same tree yields the same digest."""
    src = tmp_path / "src/sevn/x"
    src.mkdir(parents=True)
    (src / "a.py").write_text("x = 1\n", encoding="utf-8")
    (src / "b.py").write_text("y = 2\n", encoding="utf-8")
    globs = ("src/sevn/x/**",)
    assert compute_digest(tmp_path, globs) == compute_digest(tmp_path, globs)


def test_compute_digest_changes_when_source_changes(tmp_path: Path) -> None:
    """Editing a matched file changes the digest."""
    src = tmp_path / "pkg"
    src.mkdir()
    path = src / "mod.py"
    path.write_text("v1\n", encoding="utf-8")
    before = compute_digest(tmp_path, ("pkg/**",))
    path.write_text("v2\n", encoding="utf-8")
    after = compute_digest(tmp_path, ("pkg/**",))
    assert before != after


def test_fingerprint_round_trip(tmp_path: Path) -> None:
    """Load/upsert/save preserves slug digest rows."""
    store_path = tmp_path / "_fingerprints.json"
    store = load_fingerprints(store_path)
    digest = "a" * 64
    upsert_entry(store, slug="gateway", digest=digest, source_globs=["src/sevn/gateway/**"])
    save_fingerprints(store_path, store)
    reloaded = load_fingerprints(store_path)
    row = reloaded["entries"]["gateway"]
    assert row["digest"] == digest
    assert row["algorithm"] == "sha256_glob_aggregate"
    assert row["source_globs"] == ["src/sevn/gateway/**"]


def test_expand_source_globs_skips_pycache(tmp_path: Path) -> None:
    """__pycache__ files are excluded from fingerprint expansion."""
    pkg = tmp_path / "pkg"
    cache = pkg / "__pycache__"
    cache.mkdir(parents=True)
    (pkg / "ok.py").write_text("1\n", encoding="utf-8")
    (cache / "ok.cpython-312.pyc").write_bytes(b"\x00")
    files = expand_source_globs(tmp_path, ("pkg/**",))
    rels = [p.relative_to(tmp_path).as_posix() for p in files]
    assert rels == ["pkg/ok.py"]
