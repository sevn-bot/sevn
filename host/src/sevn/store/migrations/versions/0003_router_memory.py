"""Decision log, memories, message search, and agent locks.

Mutable until plan 0020 Final. Later waves of that plan amend this file.
They do not add a sibling revision. ``agents.isolation`` already exists in
``0002_bots_agents`` and must not be added again.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_router_memory"
down_revision = "0002_bots_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("idle_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "bots",
        sa.Column("network", sa.String(), nullable=False, server_default="off"),
    )
    op.create_table(
        "decision_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("point", sa.String(), nullable=False),
        sa.Column("input_hash", sa.String(), nullable=False),
        sa.Column("state_redacted", sa.String(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("confidences", sa.JSON(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("corrected_to", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "route_decisions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "memories",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("bot_id", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("tier", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE VIRTUAL TABLE memories_fts USING fts5(id UNINDEXED, text, tokenize = 'unicode61')"
    )
    op.execute(
        "CREATE VIRTUAL TABLE messages_fts USING fts5(id UNINDEXED, text, tokenize = 'unicode61')"
    )
    op.execute(
        "INSERT INTO messages_fts(id, text) "
        "SELECT messages.id, COALESCE(("
        "SELECT group_concat(json_extract(value, '$.text'), char(10)) "
        "FROM json_each(messages.parts) "
        "WHERE json_extract(value, '$.text') IS NOT NULL"
        "), '') FROM messages"
    )
    op.execute(
        "CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages BEGIN "
        "INSERT INTO messages_fts(id, text) VALUES (new.id, COALESCE(("
        "SELECT group_concat(json_extract(value, '$.text'), char(10)) "
        "FROM json_each(new.parts) "
        "WHERE json_extract(value, '$.text') IS NOT NULL"
        "), '')); END"
    )
    op.execute(
        "CREATE TRIGGER messages_fts_update AFTER UPDATE OF parts ON messages BEGIN "
        "DELETE FROM messages_fts WHERE id = old.id; "
        "INSERT INTO messages_fts(id, text) VALUES (new.id, COALESCE(("
        "SELECT group_concat(json_extract(value, '$.text'), char(10)) "
        "FROM json_each(new.parts) "
        "WHERE json_extract(value, '$.text') IS NOT NULL"
        "), '')); END"
    )
    op.execute(
        "CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages BEGIN "
        "DELETE FROM messages_fts WHERE id = old.id; END"
    )
    op.create_table(
        "agent_locks",
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("path"),
    )


def downgrade() -> None:
    op.drop_table("agent_locks")
    op.execute("DROP TRIGGER IF EXISTS messages_fts_delete")
    op.execute("DROP TRIGGER IF EXISTS messages_fts_update")
    op.execute("DROP TRIGGER IF EXISTS messages_fts_insert")
    op.execute("DROP TABLE IF EXISTS messages_fts")
    op.execute("DROP TABLE IF EXISTS memories_fts")
    op.drop_table("memories")
    op.drop_table("route_decisions")
    op.drop_table("decision_log")
    op.drop_column("bots", "network")
    op.drop_column("agents", "archived_at")
    op.drop_column("agents", "idle_since")
