"""Store search results as tracked products, listings and daily price records."""

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import PriceRecord, Product, ProductListing
from services.platforms.base import Offer
from services.product_matcher import (
    OUTLIER_HIGH,
    OUTLIER_LOW,
    SAME_THRESHOLD,
    ProductGroup,
    make_search_text,
    match_score,
    normalize,
)

logger = logging.getLogger(__name__)


def _insert(session: AsyncSession, table):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(table)


async def find_matching_product(session: AsyncSession, name: str) -> Product | None:
    """Find the tracked product a live offer belongs to. Seeded demo products are
    never matched, so real prices don't get attached to synthetic history."""
    norm = normalize(name)
    live_only = ~Product.listings.any(ProductListing.source == "demo")
    exact = await session.scalar(select(Product).where(Product.normalized_name == norm, live_only))
    if exact:
        return exact
    first_word = norm.split()[0] if norm else ""
    if not first_word:
        return None
    candidates = (
        await session.scalars(
            select(Product).where(Product.normalized_name.like(f"%{first_word}%"), live_only).limit(200)
        )
    ).all()
    best, best_score = None, 0.0
    for p in candidates:
        score = match_score(name, p.name)
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= SAME_THRESHOLD else None


async def record_price(
    session: AsyncSession,
    product_id: int,
    platform: str,
    price: float,
    mrp: float | None,
    day: date | None = None,
    synthetic: bool = False,
) -> None:
    """Upsert today's price (one row per product/store/day; the latest observation wins)."""
    day = day or date.today()
    discount = round((mrp - price) / mrp * 100, 1) if mrp and mrp > price else None
    stmt = _insert(session, PriceRecord).values(
        product_id=product_id,
        platform=platform,
        price=price,
        mrp=mrp,
        discount_percent=discount,
        recorded_at=datetime.now(timezone.utc),
        recorded_date=day,
        is_synthetic=synthetic,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["product_id", "platform", "recorded_date"],
        set_={"price": price, "mrp": mrp, "discount_percent": discount, "recorded_at": stmt.excluded.recorded_at},
    )
    await session.execute(stmt)


async def upsert_listing(session: AsyncSession, product_id: int, offer: Offer) -> None:
    now = datetime.now(timezone.utc)
    values = {
        "product_id": product_id,
        "platform": offer.platform,
        "platform_product_id": offer.platform_product_id,
        "title": offer.name[:500],
        "product_url": offer.url,
        "current_price": offer.price,
        "mrp": offer.mrp,
        "rating": offer.rating,
        "review_count": offer.review_count,
        "in_stock": offer.in_stock,
        "seller_name": offer.seller,
        "delivery_info": offer.delivery_info,
        "source": offer.source,
        "last_updated": now,
    }
    stmt = _insert(session, ProductListing).values(**values)
    update = {k: v for k, v in values.items() if k not in ("product_id", "platform") and v is not None}
    stmt = stmt.on_conflict_do_update(index_elements=["product_id", "platform"], set_=update)
    await session.execute(stmt)


def _price_plausible(product: Product, price: float) -> bool:
    """Same rule as the search-time outlier check (product_matcher.split_price_outliers)."""
    prices = sorted(l.current_price for l in product.listings)
    if not prices:
        return True
    mid = prices[len(prices) // 2]
    return OUTLIER_LOW * mid <= price <= OUTLIER_HIGH * mid


async def persist_groups(session: AsyncSession, groups: list[ProductGroup], max_groups: int = 10) -> None:
    """Link live search results to Product rows (creating them if needed) and log today's prices.

    Sets `product_id` on every offer of the persisted groups so the agent can
    fetch price history for them later.
    """
    for group in groups[:max_groups]:
        live = [o for o in group.offers if o.source == "live" and o.via != "catalog"]
        if not live:
            continue
        product_id = group.product_id
        if not product_id:
            product = await find_matching_product(session, group.name)
            if product is not None and not _price_plausible(product, min(o.price for o in live)):
                product = None  # same name but a very different price: an accessory or a different item
            if product is None:
                first = live[0]
                brand = next((o.brand for o in live if o.brand), None)
                product = Product(
                    name=group.name[:500],
                    normalized_name=normalize(group.name)[:500],
                    category=first.category,
                    brand=brand,
                    image_url=next((o.image_url for o in group.offers if o.image_url), None),
                    specifications={},
                    search_text=make_search_text(group.name, brand, first.category),
                )
                session.add(product)
                await session.flush()
            product_id = product.id
        for offer in group.offers:
            offer.product_id = product_id
        await _remember_google_ids(session, product_id, live)
        for offer in live:
            await upsert_listing(session, product_id, offer)
            await record_price(session, product_id, offer.platform, offer.price, offer.mrp)
    await session.commit()


# Google keeps price history mainly on big merchants' product pages, so their links are tried first
_HISTORY_STORE_PREFERENCE = ["amazon", "flipkart", "croma", "reliance_digital", "vijay_sales", "tata_cliq", "jiomart"]
MAX_GOOGLE_TOKENS = 3


def _history_rank(offer: Offer) -> tuple:
    pref = _HISTORY_STORE_PREFERENCE.index(offer.platform) if offer.platform in _HISTORY_STORE_PREFERENCE else 99
    return (pref, not offer.trusted)


async def _remember_google_ids(session: AsyncSession, product_id: int, offers: list[Offer]) -> None:
    """Keep the Google Shopping links needed to backfill this product's price history.

    Page tokens (which carry the history) can expire, so they're refreshed on every search;
    the Google product id is stable and used as a last resort.
    """
    google = sorted((o for o in offers if o.via == "google_shopping"), key=_history_rank)
    if not google:
        return
    product = await session.get(Product, product_id)
    if product is None:
        return
    spec = dict(product.specifications or {})
    tokens = [{"store": o.platform, "token": o.google_page_token} for o in google if o.google_page_token]
    if tokens:
        spec["google_tokens"] = tokens[:MAX_GOOGLE_TOKENS]
        spec.pop("google_page_token", None)  # older single-token format
    pid = next((o.platform_product_id for o in google if o.platform_product_id), None)
    if pid and not spec.get("google_product_id"):
        spec["google_product_id"] = pid
    product.specifications = spec  # reassign so SQLAlchemy sees the JSON change


async def get_product(session: AsyncSession, product_id: int) -> Product | None:
    return await session.get(Product, product_id)


def product_to_dict(p: Product) -> dict:
    listings = sorted(p.listings, key=lambda l: l.current_price)
    return {
        "id": p.id,
        "name": p.name,
        "category": p.category,
        "brand": p.brand,
        "model_number": p.model_number,
        "image_url": p.image_url,
        "specifications": {
            k: v for k, v in (p.specifications or {}).items()
            if k != "tags" and not k.startswith(("google_", "history_"))  # internal bookkeeping
        },
        "best_price": listings[0].current_price if listings else None,
        "best_platform": listings[0].platform if listings else None,
        "listings": [
            {
                "platform": l.platform,
                "price": l.current_price,
                "mrp": l.mrp,
                "rating": l.rating,
                "review_count": l.review_count,
                "in_stock": l.in_stock,
                "url": l.affiliate_url or l.product_url,
                "seller": l.seller_name,
                "delivery_info": l.delivery_info,
                "source": l.source,
                "last_updated": l.last_updated.isoformat() if l.last_updated else None,
            }
            for l in listings
        ],
    }
