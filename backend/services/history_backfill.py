"""Backfill ~12 months of real price history from Google Shopping.

SmartDeal records prices daily, but a newly tracked product starts with no history,
so the chart, fake-discount check and buy-timing have nothing to work with. Google
Shopping keeps per-store price history; SerpApi's Google Product API returns it as
dated price points (one point each time a store's price changed). This module turns
those points into daily records (the price holds until the next change), drops
glitches, and stores them with source="google_history". SmartDeal's own tracked
prices always win over backfilled ones for the same day.

Each backfill costs one SerpApi search, so it runs at most once per product, only
when a product is actually analysed, and within a monthly budget.
"""

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from statistics import median

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import session_scope
from core.redis_client import get_redis
from models import PriceRecord, Product
from services.platforms.base import platform_from_source
from services.product_matcher import OUTLIER_HIGH, OUTLIER_LOW

logger = logging.getLogger(__name__)

API_URL = "https://serpapi.com/search.json"
HISTORY_DAYS = 365
ENOUGH_TRACKED_DAYS = 30  # products we've tracked this long don't need a backfill
SOURCE = "google_history"
_DATE_FORMATS = ("%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%Y-%m-%d")

_locks: dict[int, asyncio.Lock] = {}
_memory_budget: dict[str, int] = {}


# ---------- parsing ------------------------------------------------------------------

def _parse_date(text: str) -> date | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def parse_price_insights(price_insights: dict) -> dict[str, list[tuple[date, float]]]:
    """{"stores": [{"name", "prices": [{"date", "price"}]}]} -> {platform_slug: [(date, price), ...]}.

    Glitch points (under 45% or over 220% of that store's median) are dropped.
    """
    series: dict[str, list[tuple[date, float]]] = {}
    for store in price_insights.get("stores") or []:
        name = (store.get("name") or "").strip()
        points = []
        for p in store.get("prices") or []:
            d, price = _parse_date(str(p.get("date", ""))), p.get("price")
            if d and isinstance(price, (int, float)) and price > 0:
                points.append((d, float(price)))
        if not name or not points:
            continue
        if len(points) >= 3:
            mid = median(price for _, price in points)
            points = [(d, price) for d, price in points if OUTLIER_LOW * mid <= price <= OUTLIER_HIGH * mid]
        slug = platform_from_source(name)
        series.setdefault(slug, []).extend(points)
    return {slug: sorted(set(points)) for slug, points in series.items() if points}


def expand_daily(points: list[tuple[date, float]], today: date, days: int = HISTORY_DAYS) -> list[tuple[date, float]]:
    """Change points -> one price per day: each price holds until the next change (or today)."""
    start = today - timedelta(days=days)
    daily: dict[date, float] = {}
    for i, (d, price) in enumerate(points):
        end = points[i + 1][0] - timedelta(days=1) if i + 1 < len(points) else today
        day = max(d, start)
        while day <= min(end, today):
            daily[day] = price  # same-day changes: the later point wins
            day += timedelta(days=1)
    return sorted(daily.items())


# ---------- budget -------------------------------------------------------------------

def _budget_key(today: date) -> str:
    return f"backfill:serpapi:{today:%Y-%m}"


async def _take_budget() -> bool:
    """Reserve one SerpApi search from this month's backfill budget."""
    key = _budget_key(date.today())
    limit = settings.history_backfill_monthly_limit
    try:
        redis = get_redis()
        used = await redis.incr(key)
        if used == 1:
            await redis.expire(key, 40 * 24 * 3600)
        if used > limit:
            await redis.decr(key)
            return False
        return True
    except Exception:  # noqa: BLE001 - Redis down: count in memory instead
        used = _memory_budget.get(key, 0)
        if used >= limit:
            return False
        _memory_budget[key] = used + 1
        return True


# ---------- fetching -----------------------------------------------------------------

async def fetch_price_insights(params: dict) -> dict | None:
    """One Google Product request ({"page_token": ...} or {"product_id": ...}).

    Returns the price insights ({} when Google has no history for that page), or None when
    the request failed or this month's backfill budget is used up.
    """
    if not await _take_budget():
        logger.warning("price-history backfill budget used up for this month")
        return None
    query = {"engine": "google_product", "gl": "in", "hl": "en", "api_key": settings.serpapi_key, **params}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(API_URL, params=query)
        data = resp.json() if resp.status_code == 200 else {}
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("google_product request failed: %s", exc.__class__.__name__)
        return None
    if resp.status_code != 200:
        logger.info("google_product returned HTTP %s", resp.status_code)
        return None
    if data.get("error"):
        logger.info("google_product: %s", data["error"])
        return {}
    return (data.get("product_results") or {}).get("price_insights") or {}


def _fingerprint(params: dict) -> str:
    return hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]


def _candidates(spec: dict) -> list[dict]:
    """Google links to try, best first, skipping ones that already came back without history."""
    tried = set(spec.get("history_tried") or [])
    out = [{"page_token": t["token"]} for t in spec.get("google_tokens") or [] if t.get("token")]
    if spec.get("google_page_token"):  # older single-token format
        out.append({"page_token": spec["google_page_token"]})
    if spec.get("google_product_id"):
        out.append({"product_id": spec["google_product_id"]})
    return [c for c in out if _fingerprint(c) not in tried]


# ---------- backfilling --------------------------------------------------------------

async def _tracked_days(session: AsyncSession, product_id: int) -> int:
    return await session.scalar(
        select(func.count(func.distinct(PriceRecord.recorded_date))).where(
            PriceRecord.product_id == product_id, PriceRecord.is_synthetic.is_(False)
        )
    ) or 0


def _insert(session: AsyncSession):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(PriceRecord)


async def store_history(session: AsyncSession, product_id: int, series: dict[str, list[tuple[date, float]]],
                        today: date | None = None) -> int:
    """Insert daily backfilled prices; days SmartDeal already tracked are left untouched."""
    today = today or date.today()
    now = datetime.now(timezone.utc)
    rows = []
    for platform, points in series.items():
        for day, price in expand_daily(points, today):
            rows.append({
                "product_id": product_id,
                "platform": platform,
                "price": price,
                "mrp": None,
                "discount_percent": None,
                "recorded_at": now,
                "recorded_date": day,
                "is_synthetic": False,
                "source": SOURCE,
            })
    if not rows:
        return 0
    for i in range(0, len(rows), 1000):
        stmt = _insert(session).values(rows[i:i + 1000])
        stmt = stmt.on_conflict_do_nothing(index_elements=["product_id", "platform", "recorded_date"])
        await session.execute(stmt)
    return len(rows)


MAX_ATTEMPTS_PER_CALL = 3


def _needs_backfill(product: Product, tracked_days: int) -> bool:
    spec = product.specifications or {}
    if spec.get("history_backfilled_at") and spec.get("history_backfill_stores"):
        return False  # done: Google history is in the database
    if any(listing.source == "demo" for listing in product.listings):
        return False
    if tracked_days >= ENOUGH_TRACKED_DAYS:
        return False
    return bool(_candidates(spec))


async def ensure_history(product_id: int) -> dict:
    """Backfill a product's price history once, if it's new and Google has history for it.

    Tries the saved Google links in order (big stores first) until one has history; links
    without history are remembered and not paid for again. Safe to call from several tools
    at once: one call does the work, the rest wait and skip.
    """
    if not (settings.serpapi_key and settings.history_backfill_enabled):
        return {"status": "disabled"}
    lock = _locks.setdefault(product_id, asyncio.Lock())
    async with lock:
        try:
            async with session_scope() as session:
                product = await session.get(Product, product_id)
                if product is None:
                    return {"status": "no_product"}
                tracked = await _tracked_days(session, product_id)
                if not _needs_backfill(product, tracked):
                    return {"status": "not_needed"}
                spec = dict(product.specifications or {})
                tried = list(spec.get("history_tried") or [])
                for params in _candidates(spec)[:MAX_ATTEMPTS_PER_CALL]:
                    insights = await fetch_price_insights(params)
                    if insights is None:
                        break  # request failed or budget used up: try again another time
                    series = parse_price_insights(insights)
                    if not series:
                        tried.append(_fingerprint(params))
                        continue
                    inserted = await store_history(session, product_id, series)
                    spec.update(history_backfilled_at=datetime.now(timezone.utc).isoformat(),
                                history_backfill_stores=sorted(series), history_tried=tried)
                    product.specifications = spec
                    logger.info("backfilled %d daily prices for product %s from %d stores",
                                inserted, product_id, len(series))
                    return {"status": "backfilled", "rows": inserted, "stores": sorted(series)}
                spec["history_tried"] = tried
                product.specifications = spec
            logger.info("no Google price history found yet for product %s", product_id)
            return {"status": "no_history"}
        except Exception:  # noqa: BLE001 - a failed backfill must never break the answer
            logger.exception("price-history backfill failed for product %s", product_id)
            return {"status": "error"}
