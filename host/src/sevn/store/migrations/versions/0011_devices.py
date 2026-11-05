"""Paired devices, pairing tickets and pairing attempts (plan 0055 D1, D2).

``pairing_tickets`` keeps only SHA-256 hex digests of a ticket and of its short
code; neither value is stored. ``pairing_attempts`` feeds the per-host rate
limit. ``devices.pubkey_x25519`` stays NULL until plan 0080 uses it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_devices"
down_revision = "0010_trace_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("pubkey_ed25519", sa.String(), nullable=False),
        sa.Column("pubkey_x25519", sa.String(), nullable=True),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "pairing_tickets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("host_id", sa.String(), nullable=False),
        sa.Column("ticket_hash", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pairing_tickets_ticket_hash", "pairing_tickets", ["ticket_hash"], unique=True
    )
    op.create_index("ix_pairing_tickets_code_hash", "pairing_tickets", ["code_hash"])
    op.create_table(
        "pairing_attempts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pairing_attempts_created_at", "pairing_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_pairing_attempts_created_at", table_name="pairing_attempts")
    op.drop_table("pairing_attempts")
    op.drop_index("ix_pairing_tickets_code_hash", table_name="pairing_tickets")
    op.drop_index("ix_pairing_tickets_ticket_hash", table_name="pairing_tickets")
    op.drop_table("pairing_tickets")
    op.drop_table("devices")
