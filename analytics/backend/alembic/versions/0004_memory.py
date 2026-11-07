"""memory: memories, user profiles, background jobs, conversation extraction marker

Revision ID: 0004_memory
Revises: 0003_identity_access
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa

from app.config import get_settings

revision = "0004_memory"
down_revision = "0003_identity_access"
branch_labels = None
depends_on = None

S = get_settings().meta_schema


def upgrade() -> None:
    op.add_column("conversations", sa.Column("memory_scanned_upto_message_id", sa.Integer(), nullable=True), schema=S)
    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("layer", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("scope", sa.String(120), nullable=False, server_default="global"),
        sa.Column("owner_email", sa.String(200), nullable=True),
        sa.Column("visibility", sa.String(10), nullable=False, server_default="private"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("review_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("origin", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("share_status", sa.String(20), nullable=False, server_default="none"),
        sa.Column("source_conversation_id", sa.Integer(), nullable=True),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("source_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("supersedes_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("approved_by", sa.String(200), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], [f"{S}.workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_conversation_id"], [f"{S}.conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_message_id"], [f"{S}.messages.id"], ondelete="SET NULL"),
        schema=S,
    )
    for col in ("workspace_id", "owner_email", "status"):
        op.create_index(f"ix_memories_{col}", "memories", [col], schema=S)
    # full-text search over a memory's words (retrieval ranks with ts_rank on the same expression)
    op.execute(f"CREATE INDEX ix_memories_search ON {S}.memories USING gin "
               f"(to_tsvector('english', coalesce(text, '') || ' ' || coalesce(rationale, '')))")
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("user_email", sa.String(200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edited_by_user", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approvals_since", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], [f"{S}.workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "user_email"),
        schema=S,
    )
    op.create_index("ix_user_profiles_workspace_id", "user_profiles", ["workspace_id"], schema=S)
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        schema=S,
    )
    for col in ("kind", "dedupe_key", "status", "run_after"):
        op.create_index(f"ix_jobs_{col}", "jobs", [col], schema=S)


def downgrade() -> None:
    for t in ("jobs", "user_profiles", "memories"):
        op.drop_table(t, schema=S)
    op.drop_column("conversations", "memory_scanned_upto_message_id", schema=S)
