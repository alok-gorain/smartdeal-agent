"""searchable text per product, so catalog search can prefilter in SQL

Revision ID: 0004_product_search_text
Revises: 0003_price_record_source
Create Date: 2026-11-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_product_search_text"
down_revision: Union[str, None] = "0003_price_record_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("search_text", sa.Text(), nullable=True))
    # Rough text for existing rows; the app writes the full version for new products
    op.execute(
        "UPDATE products SET search_text = lower(name || ' ' || coalesce(brand, '') || ' ' || coalesce(category, ''))"
    )


def downgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.drop_column("search_text")
