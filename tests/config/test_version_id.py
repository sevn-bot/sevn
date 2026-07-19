"""RED suite for ``version_id`` resolve+persist (plan D1-D3 / issue #30).

Pins ``sevn.config.version_id`` public API expected after W2:

- :func:`resolve_version_id` — env ``SEVN_VERSION_ID`` > git short SHA >
  ``importlib.metadata.version("sevn")`` > ``"unknown"``
- :func:`ensure_version_id` — resolve then persist into ``sevn.json`` top-level
  ``"version_id"`` when missing or when boot resolves a different non-``unknown``
  value (do not thrash on ``unknown``).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_XFAIL_W2 = pytest.mark.xfail(
    reason="green after W2: version_id resolve+persist (D2)",
    strict=False,
)


def _minimal_sevn_doc(**extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    doc.update(extra)
    return doc


def _write_sevn_json(path: Path, **extra: Any) -> Path:
    path.write_text(json.dumps(_minimal_sevn_doc(**extra)), encoding="utf-8")
    return path


def _init_git_repo(root: Path, *, commit_message: str = "init") -> str:
    """Create a tiny git repo and return its short HEAD SHA."""
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    (root / "README").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", commit_message],
        cwd=root,
        check=True,
        capture_output=True,
    )
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


@_XFAIL_W2
def test_resolve_prefers_nonempty_env_over_git_and_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2 step (1): non-empty ``SEVN_VERSION_ID`` wins over git and package."""
    from sevn.config.version_id import resolve_version_id

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    monkeypatch.setenv("SEVN_VERSION_ID", "env-build-42")
    with patch("importlib.metadata.version", return_value="9.9.9"):
        assert resolve_version_id(repo_root=repo) == "env-build-42"


@_XFAIL_W2
def test_resolve_ignores_empty_env_and_uses_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2 step (1)/(2): empty env falls through to ``git rev-parse --short HEAD``."""
    from sevn.config.version_id import resolve_version_id

    repo = tmp_path / "repo"
    repo.mkdir()
    short = _init_git_repo(repo)
    monkeypatch.setenv("SEVN_VERSION_ID", "")
    with patch("importlib.metadata.version", return_value="9.9.9"):
        assert resolve_version_id(repo_root=repo) == short


@_XFAIL_W2
def test_resolve_falls_back_to_package_version_when_git_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2 step (3): package metadata when env empty and git unavailable."""
    from sevn.config.version_id import resolve_version_id

    monkeypatch.delenv("SEVN_VERSION_ID", raising=False)
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    with patch("importlib.metadata.version", return_value="1.2.3") as meta:
        assert resolve_version_id(repo_root=bare) == "1.2.3"
        meta.assert_called()


@_XFAIL_W2
def test_resolve_unknown_when_all_sources_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2 step (4): ``\"unknown\"`` when env/git/package all fail."""
    from sevn.config.version_id import resolve_version_id

    monkeypatch.delenv("SEVN_VERSION_ID", raising=False)
    bare = tmp_path / "not-a-repo"
    bare.mkdir()

    from importlib.metadata import PackageNotFoundError

    with patch(
        "importlib.metadata.version",
        side_effect=PackageNotFoundError("sevn"),
    ):
        assert resolve_version_id(repo_root=bare) == "unknown"


@_XFAIL_W2
def test_ensure_persists_resolved_value_into_sevn_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ensure_version_id`` writes top-level ``version_id`` into ``sevn.json``."""
    from sevn.config.version_id import ensure_version_id

    sevn_json = _write_sevn_json(tmp_path / "sevn.json")
    monkeypatch.setenv("SEVN_VERSION_ID", "persist-me")
    got = ensure_version_id(sevn_json, repo_root=tmp_path)
    assert got == "persist-me"
    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    assert doc["version_id"] == "persist-me"
    # Orthogonal to TE-1 deployment_id (D1).
    assert "deployment_id" not in doc


@_XFAIL_W2
def test_ensure_overwrites_when_boot_resolves_different_non_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist when boot resolves a different non-``unknown`` value (D2)."""
    from sevn.config.version_id import ensure_version_id

    sevn_json = _write_sevn_json(tmp_path / "sevn.json", version_id="old-sha")
    monkeypatch.setenv("SEVN_VERSION_ID", "new-sha")
    assert ensure_version_id(sevn_json, repo_root=tmp_path) == "new-sha"
    doc = json.loads(sevn_json.read_text(encoding="utf-8"))
    assert doc["version_id"] == "new-sha"


@_XFAIL_W2
def test_ensure_does_not_thrash_unknown_over_existing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not replace a stored value when resolve returns ``unknown`` (D2)."""
    from sevn.config.version_id import ensure_version_id

    sevn_json = _write_sevn_json(tmp_path / "sevn.json", version_id="kept-sha")
    before = sevn_json.read_text(encoding="utf-8")
    mtime = sevn_json.stat().st_mtime_ns
    monkeypatch.delenv("SEVN_VERSION_ID", raising=False)
    bare = tmp_path / "not-a-repo"
    bare.mkdir()

    from importlib.metadata import PackageNotFoundError

    with patch(
        "importlib.metadata.version",
        side_effect=PackageNotFoundError("sevn"),
    ):
        got = ensure_version_id(sevn_json, repo_root=bare)
    assert got == "kept-sha"
    assert sevn_json.read_text(encoding="utf-8") == before
    assert sevn_json.stat().st_mtime_ns == mtime


@_XFAIL_W2
def test_ensure_idempotent_when_value_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running with the same resolved value does not rewrite ``sevn.json``."""
    from sevn.config.version_id import ensure_version_id

    sevn_json = _write_sevn_json(tmp_path / "sevn.json", version_id="same")
    monkeypatch.setenv("SEVN_VERSION_ID", "same")
    mtime = sevn_json.stat().st_mtime_ns
    assert ensure_version_id(sevn_json, repo_root=tmp_path) == "same"
    assert sevn_json.stat().st_mtime_ns == mtime
