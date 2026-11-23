"""Celery task: record today's price for every tracked listing (06:00 IST)."""

import asyncio
import logging
import random
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from sqlalchemy import select

from celery_app import celery_app
from core.config import settings
from core.database import task_session
from models import PriceRecord, Product, ProductListing
from services.catalog_service import record_price
from services.platforms.registry import get_adapter
from services.product_matcher import SAME_THRESHOLD, match_score
from services.sale_calendar import event_on

logger = logging.getLogger(__name__)

DIRECT_ADAPTERS = {"amazon", "flipkart", "myntra"}
MAX_LIVE_PRODUCTS_PER_RUN = 300


def _adapter_for(platform: str):
    """Direct adapter for the big three, Google Shopping for every other store."""
    if platform in DIRECT_ADAPTERS:
        adapter = get_adapter(platform)
        if adapter and adapter.is_enabled():
            return adapter
    adapter = get_adapter("google_shopping")
    return adapter if adapter and adapter.is_enabled() else None


async def _refresh_demo(session, listing: ProductListing, today: date) -> None:
    """Demo listings drift around their recent median, and dip during sale events."""
    since = today - timedelta(days=30)
    recent = (await session.scalars(
        select(PriceRecord.price).where(
            PriceRecord.product_id == listing.product_id,
            PriceRecord.platform == listing.platform,
            PriceRecord.recorded_date >= since,
        )
    )).all()
    base = median(recent) if recent else listing.current_price
    price = base * (1 + random.uniform(-0.02, 0.02))
    event = event_on(today)
    if event and listing.platform in event.platforms:
        price *= 1 - event.typical_discount
    price = float(round(price / 10) * 10 - 1) if price > 100 else round(price, 2)
    listing.current_price = price
    await record_price(session, listing.product_id, listing.platform, price, listing.mrp, day=today, synthetic=True)


async def _refresh_dataset(session, listing: ProductListing, spec: dict, today: date) -> None:
    """Weekly sample-data price: within ±4% of the loaded price, lower during sales."""
    base = (spec.get("base_prices") or {}).get(listing.platform, listing.current_price)
    price = base * (1 + random.uniform(-0.04, 0.04))
    event = event_on(today)
    if event and listing.platform in event.platforms:
        price *= 1 - event.typical_discount
    price = float(round(price / 10) * 10 - 1) if price > 100 else round(price, 2)
    if listing.mrp:
        price = min(price, listing.mrp)
    listing.current_price = price
    await record_price(session, listing.product_id, listing.platform, price, listing.mrp, day=today, synthetic=True)


async def _refresh_live(session, product: Product, listings: list[ProductListing], today: date) -> int:
    """Re-search the product on each store's adapter and update matching listings."""
    by_adapter: dict[str, list[ProductListing]] = defaultdict(list)
    for listing in listings:
        adapter = _adapter_for(listing.platform)
        if adapter:
            by_adapter[adapter.slug].append(listing)

    updated = 0
    for slug, adapter_listings in by_adapter.items():
        adapter = get_adapter(slug)
        try:
            offers = await asyncio.wait_for(adapter.search(product.name, max_results=10), settings.adapter_timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            logger.warning("refresh of %r via %s failed: %s", product.name, slug, exc)
            continue
        for listing in adapter_listings:
            candidates = [o for o in offers if o.platform == listing.platform]
            scored = sorted(((match_score(o.name, listing.title or product.name), o) for o in candidates),
                            key=lambda x: -x[0])
            if not scored or scored[0][0] < SAME_THRESHOLD:
                continue
            offer = scored[0][1]
            listing.current_price = offer.price
            listing.mrp = offer.mrp or listing.mrp
            listing.in_stock = offer.in_stock
            listing.rating = offer.rating or listing.rating
            listing.review_count = offer.review_count or listing.review_count
            await record_price(session, product.id, listing.platform, offer.price, listing.mrp, day=today)
            updated += 1
    return updated


async def _products_to_refresh(session, live_by_product: dict[int, list[ProductListing]], today: date) -> list[int]:
    """Which live products to re-price today.

    Each refresh costs a paid aggregator search, so: skip products already priced today
    (someone searched them), then take the most recently searched ones, up to the daily limit.
    """
    limit = min(settings.price_refresh_daily_limit, MAX_LIVE_PRODUCTS_PER_RUN)
    if limit <= 0 or not live_by_product:
        return []
    priced_today = set((await session.scalars(
        select(PriceRecord.product_id).where(
            PriceRecord.recorded_date == today,
            PriceRecord.source == "tracked",
            PriceRecord.product_id.in_(list(live_by_product)),
        )
    )).all())
    candidates = [pid for pid in live_by_product if pid not in priced_today]
    candidates.sort(key=lambda pid: max(l.last_updated for l in live_by_product[pid]), reverse=True)
    return candidates[:limit]


async def collect() -> dict:
    today = date.today()
    stats = {"demo": 0, "live_updated": 0, "live_products": 0}
    async with task_session() as session:
        rows = (await session.execute(
            select(ProductListing, Product.specifications).join(Product, Product.id == ProductListing.product_id)
        )).all()
        live_by_product: dict[int, list[ProductListing]] = defaultdict(list)
        for listing, spec in rows:
            if listing.source != "demo":
                live_by_product[listing.product_id].append(listing)
            elif (spec or {}).get("dataset"):
                # public sample dataset: thousands of listings, so a gentle weekly move is enough
                if today.weekday() == 0:
                    await _refresh_dataset(session, listing, spec, today)
                    stats["dataset"] = stats.get("dataset", 0) + 1
            else:
                await _refresh_demo(session, listing, today)
                stats["demo"] += 1
        await session.commit()

        for product_id in await _products_to_refresh(session, live_by_product, today):
            product = await session.get(Product, product_id)
            if product is None:
                continue
            stats["live_updated"] += await _refresh_live(session, product, live_by_product[product_id], today)
            stats["live_products"] += 1
            await session.commit()
    logger.info("daily price collection finished: %s", stats)
    return stats


@celery_app.task(name="collect_daily_prices", bind=True, max_retries=2, default_retry_delay=600)
def collect_daily_prices(self) -> dict:
    try:
        return asyncio.run(collect())
    except Exception as exc:  # noqa: BLE001
        logger.exception("daily price collection failed")
        raise self.retry(exc=exc)
