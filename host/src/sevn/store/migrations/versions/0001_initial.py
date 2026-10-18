"""Initial events outbox and op log.

Frozen DDL. Later revisions add columns; these tables must not follow the live models.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("entity", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "op_log",
        sa.Column("op_id", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("op_id"),
    )


def downgrade() -> None:
    op.drop_table("op_log")
    op.drop_table("events")
