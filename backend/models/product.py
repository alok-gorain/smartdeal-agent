from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, JSONType, TimestampMixin, utcnow


class Product(TimestampMixin, Base):
    """A canonical product, matched across stores (e.g. 'Apple iPhone 16 128GB Black')."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500), index=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), index=True, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    brand: Mapped[str | None] = mapped_column(String(200), index=True)
    model_number: Mapped[str | None] = mapped_column(String(200))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    specifications: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    # normalised name + brand + category + tags, for a fast SQL prefilter in catalog search
    search_text: Mapped[str | None] = mapped_column(Text)

    listings: Mapped[list["ProductListing"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin"
    )


class ProductListing(Base):
    """One store's offer for a product."""

    __tablename__ = "product_listings"
    __table_args__ = (UniqueConstraint("product_id", "platform", name="uq_listing_product_platform"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False
    )
    platform: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    platform_product_id: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(500))  # the store's own title
    product_url: Mapped[str | None] = mapped_column(String(2000))
    affiliate_url: Mapped[str | None] = mapped_column(String(2000))
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    mrp: Mapped[float | None] = mapped_column(Float)
    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    seller_name: Mapped[str | None] = mapped_column(String(300))
    delivery_info: Mapped[str | None] = mapped_column(String(300))
    # "live" = from a real store/API, "demo" = seeded sample data
    source: Mapped[str] = mapped_column(String(20), default="live", nullable=False)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    product: Mapped[Product] = relationship(back_populates="listings")
