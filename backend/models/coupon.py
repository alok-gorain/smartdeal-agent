from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, JSONType, utcnow


class Coupon(Base):
    """A store coupon or a bank card offer (offer_kind tells them apart)."""

    __tablename__ = "coupons"
    __table_args__ = (UniqueConstraint("platform", "title", name="uq_coupon_platform_title"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    offer_kind: Mapped[str] = mapped_column(String(20), default="coupon", nullable=False)  # coupon | bank_offer
    code: Mapped[str | None] = mapped_column(String(100))  # None = auto-applied
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)  # percent | flat | cashback
    discount_value: Mapped[float] = mapped_column(Float, nullable=False)
    min_order_value: Mapped[float | None] = mapped_column(Float)
    max_discount: Mapped[float | None] = mapped_column(Float)
    bank_name: Mapped[str | None] = mapped_column(String(50), index=True)
    card_type: Mapped[str | None] = mapped_column(String(20))  # credit | debit | both
    categories: Mapped[list | None] = mapped_column(JSONType)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Sample offers shipped with the demo; hidden whenever demo data is hidden
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
