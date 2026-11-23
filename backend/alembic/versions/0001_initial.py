"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("normalized_name", sa.String(500), nullable=False),
        sa.Column("category", sa.String(100)),
        sa.Column("brand", sa.String(200)),
        sa.Column("model_number", sa.String(200)),
        sa.Column("image_url", sa.String(1000)),
        sa.Column("specifications", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_products_name", "products", ["name"])
    op.create_index("ix_products_normalized_name", "products", ["normalized_name"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_brand", "products", ["brand"])

    op.create_table(
        "product_listings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("platform_product_id", sa.String(200)),
        sa.Column("title", sa.String(500)),
        sa.Column("product_url", sa.String(2000)),
        sa.Column("affiliate_url", sa.String(2000)),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("mrp", sa.Float()),
        sa.Column("rating", sa.Float()),
        sa.Column("review_count", sa.Integer()),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
        sa.Column("seller_name", sa.String(300)),
        sa.Column("delivery_info", sa.String(300)),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("product_id", "platform", name="uq_listing_product_platform"),
    )
    op.create_index("ix_product_listings_product_id", "product_listings", ["product_id"])
    op.create_index("ix_product_listings_platform", "product_listings", ["platform"])

    op.create_table(
        "price_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("mrp", sa.Float()),
        sa.Column("discount_percent", sa.Float()),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_date", sa.Date(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("product_id", "platform", "recorded_date", name="uq_price_product_platform_day"),
    )
    op.create_index("ix_price_records_product_id", "price_records", ["product_id"])
    op.create_index("ix_price_records_platform", "price_records", ["platform"])
    op.create_index("ix_price_records_recorded_date", "price_records", ["recorded_date"])

    op.create_table(
        "coupons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("offer_kind", sa.String(20), nullable=False),
        sa.Column("code", sa.String(100)),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("discount_type", sa.String(20), nullable=False),
        sa.Column("discount_value", sa.Float(), nullable=False),
        sa.Column("min_order_value", sa.Float()),
        sa.Column("max_discount", sa.Float()),
        sa.Column("bank_name", sa.String(50)),
        sa.Column("card_type", sa.String(20)),
        sa.Column("categories", JSONType),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("source_url", sa.String(1000)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("platform", "title", name="uq_coupon_platform_title"),
    )
    op.create_index("ix_coupons_platform", "coupons", ["platform"])
    op.create_index("ix_coupons_bank_name", "coupons", ["bank_name"])


def downgrade() -> None:
    op.drop_table("coupons")
    op.drop_table("price_records")
    op.drop_table("product_listings")
    op.drop_table("products")
