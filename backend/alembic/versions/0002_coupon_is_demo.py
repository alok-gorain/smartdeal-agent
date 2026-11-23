"""mark sample coupons as demo data

Revision ID: 0002_coupon_is_demo
Revises: 0001_initial
Create Date: 2026-11-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_coupon_is_demo"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("coupons") as batch:
        batch.add_column(sa.Column("is_demo", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("coupons") as batch:
        batch.drop_column("is_demo")
