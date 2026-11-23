from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, utcnow


class PriceRecord(Base):
    """One price observation per product, per store, per day."""

    __tablename__ = "price_records"
    __table_args__ = (
        UniqueConstraint("product_id", "platform", "recorded_date", name="uq_price_product_platform_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False
    )
    platform: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    mrp: Mapped[float | None] = mapped_column(Float)
    discount_percent: Mapped[float | None] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    recorded_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # "tracked" = SmartDeal recorded it; "google_history" = backfilled from Google Shopping price history
    source: Mapped[str] = mapped_column(String(20), default="tracked", server_default="tracked", nullable=False)
