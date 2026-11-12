"""Router spend: what each routing step's model call used (plan fleet-dashboards).

``decision_log.usage`` holds the shared usage shape (``runtime/usage.py``) for a
step that called a model, and is null for rules and the default step.
``decision_log.bot_id`` is the bot whose message was routed, so the spend can
be counted per bot.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_routing_usage"
down_revision = "0011_devices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("decision_log", sa.Column("bot_id", sa.String(), nullable=True))
    op.add_column("decision_log", sa.Column("usage", sa.JSON(), nullable=True))
    # Spend reads the day's routing rows by time.
    op.create_index("ix_decision_log_created_at", "decision_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_decision_log_created_at", table_name="decision_log")
    op.drop_column("decision_log", "usage")
    op.drop_column("decision_log", "bot_id")
