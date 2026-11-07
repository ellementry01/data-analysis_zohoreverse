"""data issues: issue register, owner notifications, cached "worth a look" items

Revision ID: 0005_data_issues
Revises: 0004_memory
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa

from app.config import get_settings

revision = "0005_data_issues"
down_revision = "0004_memory"
branch_labels = None
depends_on = None

S = get_settings().meta_schema


def upgrade() -> None:
    op.create_table(
        "data_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("area", sa.String(80), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("status_detail", sa.String(120), nullable=False, server_default=""),
        sa.Column("severity", sa.String(10), nullable=False, server_default="medium"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("affects", sa.JSON(), nullable=False),
        sa.Column("owner", sa.String(120), nullable=False, server_default=""),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("solved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.String(200), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], [f"{S}.workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "code"),
        schema=S,
    )
    op.create_index("ix_data_issues_workspace_id", "data_issues", ["workspace_id"], schema=S)
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("issue_code", sa.String(30), nullable=True),
        sa.Column("read_by", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], [f"{S}.workspaces.id"], ondelete="CASCADE"),
        schema=S,
    )
    op.create_index("ix_notifications_workspace_id", "notifications", ["workspace_id"], schema=S)
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"], schema=S)
    op.create_table(
        "dashboard_insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("dashboard_key", sa.String(80), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], [f"{S}.workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "dashboard_key"),
        schema=S,
    )
    op.create_index("ix_dashboard_insights_workspace_id", "dashboard_insights", ["workspace_id"], schema=S)


def downgrade() -> None:
    for t in ("dashboard_insights", "notifications", "data_issues"):
        op.drop_table(t, schema=S)
