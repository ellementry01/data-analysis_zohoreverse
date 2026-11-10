"""eval runs: the result of every evaluation-set run, for the monitoring page and the release gate (Phase 8)

Revision ID: 0007_eval_runs
Revises: 0006_domain_agents
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

from app.config import get_settings

revision = "0007_eval_runs"
down_revision = "0006_domain_agents"
branch_labels = None
depends_on = None

S = get_settings().meta_schema


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("set_name", sa.String(80), nullable=False),
        sa.Column("live", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("numbers_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("numbers_correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invented", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_inr", sa.Float(), nullable=False, server_default="0"),
        sa.Column("median_seconds", sa.Float(), nullable=True),
        sa.Column("failures", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("git_commit", sa.String(40), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=S,
    )
    op.create_index("ix_eval_runs_set_created", "eval_runs", ["set_name", "created_at"], schema=S)


def downgrade() -> None:
    op.drop_index("ix_eval_runs_set_created", table_name="eval_runs", schema=S)
    op.drop_table("eval_runs", schema=S)
