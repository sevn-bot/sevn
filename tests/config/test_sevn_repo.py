"""``sevn.config.sevn_repo`` helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sevn.config.sevn_repo import (
    _editable_sevn_repo_root,
    resolve_mycode_default_root,
    resolve_sevn_checkout_with_origin,
    try_resolve_sevn_repo_root,
)

if TYPE_CHECKING:
    import pytest


def _write_sevn_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    (path / "pyproject.toml").write_text('[project]\nname = "sevn"\n', encoding="utf-8")


def test_editable_sevn_repo_root_walks_up_from_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns the checkout enclosing an editable ``sevn`` package (``sevn.__file__``)."""
    repo = tmp_path / "sevn.bot"
    _write_sevn_repo(repo)
    pkg_init = repo / "src" / "sevn" / "__init__.py"
    pkg_init.parent.mkdir(parents=True)
    pkg_init.write_text("", encoding="utf-8")
    import sevn as pkg

    monkeypatch.setattr(pkg, "__file__", str(pkg_init))
    assert _editable_sevn_repo_root() == repo.resolve()


def test_resolve_origin_prefers_editable_over_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The editable install checkout (deterministic) outranks a ``$HOME`` folder scan."""
    monkeypatch.delenv("SEVN_REPO_ROOT", raising=False)
    monkeypatch.delenv("SEVN_SOURCE_ROOT", raising=False)
    install = tmp_path / "install"
    _write_sevn_repo(install)
    stray = tmp_path / "stray-clone"
    _write_sevn_repo(stray)
    monkeypatch.setattr("sevn.config.sevn_repo._editable_sevn_repo_root", lambda: install.resolve())
    monkeypatch.setattr(
        "sevn.config.sevn_repo._search_common_dev_locations",
        lambda *a, **k: stray.resolve(),
    )
    checkout, origin = resolve_sevn_checkout_with_origin(content_root=tmp_path / "ws")
    assert origin == "editable"
    assert checkout == install.resolve()


def test_try_resolve_sevn_repo_root_from_hint(tmp_path: Path) -> None:
    repo = tmp_path / "sevn.bot"
    _write_sevn_repo(repo)
    assert try_resolve_sevn_repo_root(repo) == repo.resolve()


def test_resolve_mycode_default_root_prefers_sevn_checkout(tmp_path: Path) -> None:
    sevn_repo = tmp_path / "sevn.bot"
    _write_sevn_repo(sevn_repo)
    assert resolve_mycode_default_root(sevn_repo) == sevn_repo.resolve()


def test_resolve_mycode_default_root_falls_back_to_primary(tmp_path: Path, monkeypatch) -> None:
    # Assert the fallback path: clear any checkout env (incl. the autouse fixture's
    # SEVN_REPO_ROOT) so resolution finds nothing and returns ``primary``.
    monkeypatch.delenv("SEVN_REPO_ROOT", raising=False)
    monkeypatch.delenv("SEVN_SOURCE_ROOT", raising=False)
    primary = tmp_path / "project"
    primary.mkdir()
    assert resolve_mycode_default_root(primary) == primary.resolve()
