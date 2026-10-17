"""Initial events outbox and op log."""

from __future__ import annotations

from alembic import op
from sevn.store.models import Event, OpLogEntry
from sqlalchemy import Table
from sqlalchemy.orm import DeclarativeBase

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    _apply(Event, drop=False)
    _apply(OpLogEntry, drop=False)


def downgrade() -> None:
    _apply(OpLogEntry, drop=True)
    _apply(Event, drop=True)


def _apply(model: type[DeclarativeBase], *, drop: bool) -> None:
    table = model.__table__
    if not isinstance(table, Table):
        raise RuntimeError(f"{model.__name__} has no table")
    bind = op.get_bind()
    if drop:
        table.drop(bind)
    else:
        table.create(bind)
