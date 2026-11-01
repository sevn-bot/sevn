"""Bot-reported metrics, read-only share links, and a budget override (phase 6).

``routines.budget_resumed_at`` records an owner resuming a routine the budget
paused, so the budget sweep does not pause it again the same day.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_metrics_shares"
down_revision = "0004_routines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "routines",
        sa.Column("budget_resumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "metric_points",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("bot_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness_minutes", sa.Integer(), nullable=False),
        sa.Column("shareable", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Tiles read each bot's latest point per key and one 24-48h lookup.
    op.create_index("ix_metric_points_key_bot_as_of", "metric_points", ["key", "bot_id", "as_of"])
    op.create_table(
        "share_links",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("secret_hash", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("bot_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opens", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("share_links")
    op.drop_index("ix_metric_points_key_bot_as_of", table_name="metric_points")
    op.drop_table("metric_points")
    op.drop_column("routines", "budget_resumed_at")
