"""initial requests table

Revision ID: 0001
Revises:
Create Date: 2026-07-23

"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "requests",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("model_id", sa.String(200), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("client_id", sa.String(100), nullable=True),
        sa.Column("system_prompt_version", sa.String(20), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_requests_created_at", "requests", ["created_at"])
    op.create_index("ix_requests_model_id", "requests", ["model_id"])


def downgrade() -> None:
    op.drop_index("ix_requests_model_id", table_name="requests")
    op.drop_index("ix_requests_created_at", table_name="requests")
    op.drop_table("requests")
