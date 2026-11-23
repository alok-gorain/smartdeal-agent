"""record where each price came from (own tracking vs Google price history)

Revision ID: 0003_price_record_source
Revises: 0002_coupon_is_demo
Create Date: 2026-11-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_price_record_source"
down_revision: Union[str, None] = "0002_coupon_is_demo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("price_records") as batch:
        batch.add_column(sa.Column("source", sa.String(20), server_default="tracked", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("price_records") as batch:
        batch.drop_column("source")
