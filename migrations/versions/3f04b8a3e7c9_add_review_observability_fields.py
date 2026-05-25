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
    op.execute(
        "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS queued_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS error_code VARCHAR(100)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("reviews", "error_code")
    op.drop_column("reviews", "completed_at")
    op.drop_column("reviews", "started_at")
    op.drop_column("reviews", "queued_at")
