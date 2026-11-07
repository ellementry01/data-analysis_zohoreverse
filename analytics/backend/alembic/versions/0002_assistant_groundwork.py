"""assistant groundwork: stable dashboard keys, conversation scopes, message details, AI usage ledger

Revision ID: 0002_assistant_groundwork
Revises: 0001_initial
Create Date: 2026-11-07
"""
import re
import unicodedata

from alembic import op
import sqlalchemy as sa

from app.config import get_settings

revision = "0002_assistant_groundwork"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

S = get_settings().meta_schema


def _key(name: str) -> str:  # same rule as app.services.naming.dashboard_key (kept local: migrations must not drift)
    value = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:80].rstrip("-") or "dashboard"


def upgrade() -> None:
    # dashboards: key (backfilled from the name, unique per workspace) and domain
    op.add_column("dashboards", sa.Column("key", sa.String(80), nullable=True), schema=S)
    op.add_column("dashboards", sa.Column("domain", sa.String(30), nullable=False, server_default=""), schema=S)
    bind = op.get_bind()
    rows = bind.execute(sa.text(f'SELECT id, workspace_id, name FROM "{S}".dashboards ORDER BY id')).fetchall()
    taken: dict[int, set[str]] = {}
    for did, ws, name in rows:
        base, used = _key(name), taken.setdefault(ws, set())
        key, i = base, 2
        while key in used:
            key = f"{base[:76]}-{i}"
            i += 1
        used.add(key)
        bind.execute(sa.text(f'UPDATE "{S}".dashboards SET key = :k WHERE id = :i'), {"k": key, "i": did})
    op.alter_column("dashboards", "key", nullable=False, schema=S)
    op.create_unique_constraint("uq_dashboards_workspace_key", "dashboards", ["workspace_id", "key"], schema=S)

    # conversations: where the thread lives, compaction summary, archive flag
    op.add_column("conversations", sa.Column("scope_type", sa.String(20), nullable=False, server_default="workspace"), schema=S)
    op.add_column("conversations", sa.Column("dashboard_key", sa.String(80), nullable=True), schema=S)
    op.add_column("conversations", sa.Column("summary", sa.Text(), nullable=False, server_default=""), schema=S)
    op.add_column("conversations", sa.Column("summary_upto_message_id", sa.Integer(), nullable=True), schema=S)
    op.add_column("conversations", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()), schema=S)
    op.create_index("ix_conversations_scope", "conversations", ["workspace_id", "user_email", "scope_type", "dashboard_key"], schema=S)

    # messages: what the user was looking at, agent steps, model, usage, feedback
    op.add_column("messages", sa.Column("screen_state", sa.JSON(), nullable=True), schema=S)
    op.add_column("messages", sa.Column("tool_trace", sa.JSON(), nullable=True), schema=S)
    op.add_column("messages", sa.Column("model", sa.String(60), nullable=False, server_default=""), schema=S)
    op.add_column("messages", sa.Column("usage", sa.JSON(), nullable=True), schema=S)
    op.add_column("messages", sa.Column("feedback", sa.String(10), nullable=True), schema=S)
    op.add_column("messages", sa.Column("feedback_note", sa.Text(), nullable=False, server_default=""), schema=S)

    # AI usage ledger
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("user_email", sa.String(200), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_inr", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], [f"{S}.workspaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], [f"{S}.conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema=S,
    )
    op.create_index("ix_ai_usage_workspace_id", "ai_usage", ["workspace_id"], schema=S)
    op.create_index("ix_ai_usage_user_email", "ai_usage", ["user_email"], schema=S)
    op.create_index("ix_ai_usage_created_at", "ai_usage", ["created_at"], schema=S)


def downgrade() -> None:
    op.drop_table("ai_usage", schema=S)
    for col in ("feedback_note", "feedback", "usage", "model", "tool_trace", "screen_state"):
        op.drop_column("messages", col, schema=S)
    op.drop_index("ix_conversations_scope", table_name="conversations", schema=S)
    for col in ("archived", "summary_upto_message_id", "summary", "dashboard_key", "scope_type"):
        op.drop_column("conversations", col, schema=S)
    op.drop_constraint("uq_dashboards_workspace_key", "dashboards", schema=S)
    op.drop_column("dashboards", "domain", schema=S)
    op.drop_column("dashboards", "key", schema=S)
