"""Alembic graph lookups for K-MIG tests.

Tests compare against the script directory's single head instead of a literal revision id,
so the next plan's migration (or a K-MIG re-chain at merge) does not break them.
"""

from __future__ import annotations

from support.repo import repo_root


def _script() -> object:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config(str(repo_root() / "host" / "alembic.ini")))


def script_head() -> str:
    """The one head of the migration graph (fails when there are zero or several)."""
    heads = list(_script().get_heads())  # type: ignore[attr-defined]
    assert len(heads) == 1, heads
    return str(heads[0])


def down_revision_of(revision: str) -> str:
    """The single parent of ``revision``."""
    found = _script().get_revision(revision)  # type: ignore[attr-defined]
    parent = found.down_revision
    assert isinstance(parent, str), parent
    return parent


def revision_ending(suffix: str) -> str:
    """The one revision id ending with ``suffix`` (survives a K-MIG renumber)."""
    ids = [rev.revision for rev in _script().walk_revisions()]  # type: ignore[attr-defined]
    matches = [rev for rev in ids if rev.endswith(suffix)]
    assert len(matches) == 1, matches
    return str(matches[0])
