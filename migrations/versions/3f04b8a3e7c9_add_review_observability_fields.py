"""add review observability fields

Revision ID: 3f04b8a3e7c9
Revises: 26c1565cdf2f
Create Date: 2026-05-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f04b8a3e7c9"
down_revision: str | Sequence[str] | None = "26c1565cdf2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "reviews", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "reviews", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "reviews", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "reviews", sa.Column("error_code", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "reviews", sa.Column("otel_trace_id", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "reviews", sa.Column("langfuse_trace_id", sa.String(length=64), nullable=True)
    )
    op.add_column("reviews", sa.Column("langfuse_trace_url", sa.Text(), nullable=True))
    op.create_index("ix_reviews_otel_trace_id", "reviews", ["otel_trace_id"])
    op.create_index("ix_reviews_langfuse_trace_id", "reviews", ["langfuse_trace_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_reviews_langfuse_trace_id", table_name="reviews")
    op.drop_index("ix_reviews_otel_trace_id", table_name="reviews")
    op.drop_column("reviews", "langfuse_trace_url")
    op.drop_column("reviews", "langfuse_trace_id")
    op.drop_column("reviews", "otel_trace_id")
    op.drop_column("reviews", "error_code")
    op.drop_column("reviews", "completed_at")
    op.drop_column("reviews", "started_at")
    op.drop_column("reviews", "queued_at")
