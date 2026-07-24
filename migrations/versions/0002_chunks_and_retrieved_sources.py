"""chunks table and requests.retrieved_sources

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-23

"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("heading", sa.String(300), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),
    )
    op.create_index("ix_chunks_source_url", "chunks", ["source_url"])
    op.add_column("requests", sa.Column("retrieved_sources", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("requests", "retrieved_sources")
    op.drop_index("ix_chunks_source_url", table_name="chunks")
    op.drop_table("chunks")
