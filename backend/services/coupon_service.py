"""Coupons and bank card offers, and the effective price they produce."""

import logging
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Coupon

logger = logging.getLogger(__name__)


def compute_saving(c: Coupon, price: float) -> float:
    """Rupees saved by applying this offer to `price` (0 if it doesn't apply)."""
    if c.min_order_value and price < c.min_order_value:
        return 0.0
    if c.discount_type == "flat":
        saving = c.discount_value
    else:  # percent and cashback are both percentages of the order
        saving = price * c.discount_value / 100
    if c.max_discount:
        saving = min(saving, c.max_discount)
    return round(min(saving, price), 2)


def applies_to(c: Coupon, platform: str, category: str | None) -> bool:
    if c.platform not in (platform, "any"):
        return False
    if c.categories and category and category.lower() not in [x.lower() for x in c.categories]:
        return False
    return True


def coupon_to_dict(c: Coupon, price: float | None = None) -> dict:
    d = {
        "id": c.id,
        "platform": c.platform,
        "offer_kind": c.offer_kind,
        "code": c.code,
        "title": c.title,
        "description": c.description,
        "discount_type": c.discount_type,
        "discount_value": c.discount_value,
        "min_order_value": c.min_order_value,
        "max_discount": c.max_discount,
        "bank_name": c.bank_name,
        "card_type": c.card_type,
        "categories": c.categories,
        "valid_until": c.valid_until.date().isoformat() if c.valid_until else None,
        "source_url": c.source_url,
        "is_demo": c.is_demo,
    }
    if price is not None:
        saving = compute_saving(c, price)
        d["saving"] = saving
        d["effective_price"] = round(price - saving, 2)
    return d


async def active_coupons(
    session: AsyncSession,
    platform: str | None = None,
    category: str | None = None,
    bank_name: str | None = None,
    include_demo: bool | None = None,
) -> list[Coupon]:
    if include_demo is None:
        from services.platforms.catalog import demo_data_enabled

        include_demo = demo_data_enabled()
    now = datetime.now(timezone.utc)
    stmt = select(Coupon).where(
        Coupon.is_active.is_(True),
        or_(Coupon.valid_until.is_(None), Coupon.valid_until >= now),
        or_(Coupon.valid_from.is_(None), Coupon.valid_from <= now),
    )
    if not include_demo:
        stmt = stmt.where(Coupon.is_demo.is_(False))
    if platform and platform != "any":
        stmt = stmt.where(Coupon.platform.in_([platform.lower(), "any"]))
    if bank_name:
        stmt = stmt.where(Coupon.bank_name.ilike(bank_name.strip()))
    coupons = list((await session.scalars(stmt.order_by(Coupon.platform, Coupon.title))).all())
    if category:
        coupons = [c for c in coupons if not c.categories or category.lower() in [x.lower() for x in c.categories]]
    return coupons


def best_deal(coupons: list[Coupon], platform: str, category: str | None, price: float) -> dict | None:
    """The single offer that saves the most on this store for this price."""
    best, best_saving = None, 0.0
    for c in coupons:
        if not applies_to(c, platform, category):
            continue
        saving = compute_saving(c, price)
        if saving > best_saving:
            best, best_saving = c, saving
    return coupon_to_dict(best, price) if best else None
