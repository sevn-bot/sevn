"""Trace context on jobs (plan 0015 D5).

``jobs.trace_parent`` holds the W3C ``traceparent`` of the job's root span, so
the turn the worker runs later, in another task or after a restart, joins the
same trace. It stays NULL while tracing is off.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_trace_context"
down_revision = "0005_metrics_shares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("trace_parent", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("trace_parent")
