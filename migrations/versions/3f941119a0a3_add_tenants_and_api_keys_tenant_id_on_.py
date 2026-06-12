"""add tenants and api_keys, tenant_id on reviews

Revision ID: 3f941119a0a3
Revises: 26c1565cdf2f
Create Date: 2026-06-10 22:30:20.368361

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f941119a0a3"
down_revision: str | Sequence[str] | None = "26c1565cdf2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Bootstrap tenant that owns every review created before multi-tenancy existed.
# Stable id so application code / seed scripts can reference it.
DEFAULT_TENANT_ID = "00000000000000000000000000000000"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])

    # Seed the bootstrap tenant before backfilling reviews against it.
    op.execute(
        sa.text(
            "INSERT INTO tenants (id, name, is_active, created_at) "
            "VALUES (:id, :name, true, now())"
        ).bindparams(id=DEFAULT_TENANT_ID, name="default")
    )

    # Add the column nullable, backfill existing rows, then enforce NOT NULL so
    # the migration is safe on a table that already has data.
    op.add_column(
        "reviews", sa.Column("tenant_id", sa.String(length=32), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE reviews SET tenant_id = :id WHERE tenant_id IS NULL"
        ).bindparams(id=DEFAULT_TENANT_ID)
    )
    op.alter_column("reviews", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_reviews_tenant_id",
        "reviews",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_reviews_tenant_id", "reviews", ["tenant_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_reviews_tenant_id", table_name="reviews")
    op.drop_constraint("fk_reviews_tenant_id", "reviews", type_="foreignkey")
    op.drop_column("reviews", "tenant_id")
    op.drop_index("ix_api_keys_tenant_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("tenants")
