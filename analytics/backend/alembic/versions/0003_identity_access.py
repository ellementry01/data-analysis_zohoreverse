"""identity and access: users, sign-in sessions, login states, API tokens, access rules, audit log

Revision ID: 0003_identity_access
Revises: 0002_assistant_groundwork
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa

from app.config import get_settings

revision = "0003_identity_access"
down_revision = "0002_assistant_groundwork"
branch_labels = None
depends_on = None

S = get_settings().meta_schema


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.String(200), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        schema=S,
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_email", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.String(300), nullable=False, server_default=""),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["user_email"], [f"{S}.users.email"], ondelete="CASCADE"),
        schema=S,
    )
    op.create_index("ix_auth_sessions_user_email", "auth_sessions", ["user_email"], schema=S)
    op.create_table(
        "login_states",
        sa.Column("state", sa.String(64), primary_key=True),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("code_verifier", sa.String(128), nullable=False),
        sa.Column("next_path", sa.String(500), nullable=False, server_default="/"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=S,
    )
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_email", sa.String(200), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["user_email"], [f"{S}.users.email"], ondelete="CASCADE"),
        schema=S,
    )
    op.create_index("ix_api_tokens_user_email", "api_tokens", ["user_email"], schema=S)
    op.create_table(
        "access_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("principal_type", sa.String(20), nullable=False),
        sa.Column("principal", sa.String(200), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], [f"{S}.workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "target_type", "target", "principal_type", "principal", name="uq_access_rules"),
        schema=S,
    )
    op.create_index("ix_access_rules_workspace_id", "access_rules", ["workspace_id"], schema=S)
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_email", sa.String(200), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("target", sa.String(300), nullable=False, server_default=""),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
        schema=S,
    )
    for col in ("at", "user_email", "action"):
        op.create_index(f"ix_audit_events_{col}", "audit_events", [col], schema=S)


def downgrade() -> None:
    for t in ("audit_events", "access_rules", "api_tokens", "login_states", "auth_sessions", "users"):
        op.drop_table(t, schema=S)
