"""Routines and the jobs that run them (plan fleet-dashboards, phase 4)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_routines"
down_revision = "0003_router_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routines",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("bot_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("schedule", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("paused_reason", sa.String(), nullable=True),
        sa.Column("next_run", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("jobs", sa.Column("routine_id", sa.String(), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("silent", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("silent")
        batch.drop_column("routine_id")
    op.drop_table("routines")
