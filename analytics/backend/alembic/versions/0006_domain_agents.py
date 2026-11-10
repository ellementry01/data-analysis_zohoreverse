"""domain agents: decisions on warehouse alerts, executive briefings, what the app has already announced

Revision ID: 0006_domain_agents
Revises: 0005_data_issues
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

from app.config import get_settings

revision = "0006_domain_agents"
down_revision = "0005_data_issues"
branch_labels = None
depends_on = None

S = get_settings().meta_schema


def upgrade() -> None:
    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.BigInteger(), nullable=False),
        sa.Column("alert_code", sa.String(40), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("decided_by", sa.String(200), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alert_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("memory_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], [f"{S}.workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_id"], [f"{S}.memories.id"], ondelete="SET NULL"),
        schema=S,
    )
    op.create_index("ix_agent_decisions_workspace_alert", "agent_decisions", ["workspace_id", "alert_id"], schema=S)
    op.create_table(
        "briefings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="executive"),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("as_of_date", sa.String(10), nullable=True),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("written_by", sa.String(40), nullable=False, server_default=""),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], [f"{S}.workspaces.id"], ondelete="CASCADE"),
        schema=S,
    )
    op.create_index("ix_briefings_workspace_created", "briefings", ["workspace_id", "created_at"], schema=S)
    op.create_table(
        "agent_sync_state",
        sa.Column("workspace_id", sa.Integer(), primary_key=True),
        sa.Column("last_alert_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_run_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], [f"{S}.workspaces.id"], ondelete="CASCADE"),
        schema=S,
    )


def downgrade() -> None:
    op.drop_table("agent_sync_state", schema=S)
    op.drop_index("ix_briefings_workspace_created", table_name="briefings", schema=S)
    op.drop_table("briefings", schema=S)
    op.drop_index("ix_agent_decisions_workspace_alert", table_name="agent_decisions", schema=S)
    op.drop_table("agent_decisions", schema=S)
