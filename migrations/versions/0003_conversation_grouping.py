"""conversation_id and turn on requests

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-24

"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("conversation_id", sa.Uuid(), nullable=True))
    op.add_column("requests", sa.Column("turn", sa.Integer(), nullable=True))
    op.create_index("ix_requests_conversation_id", "requests", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_requests_conversation_id", table_name="requests")
    op.drop_column("requests", "turn")
    op.drop_column("requests", "conversation_id")
