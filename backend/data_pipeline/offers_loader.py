"""Load the curated coupons/bank offers file into the database.

`data/offers.json` is the single place to maintain offers. Entries can use
`valid_until` (ISO date) for real offers, or `valid_days` (relative to load
time). Entries with `"demo": true` are sample offers: they are only shown while
demo data is shown (see DEMO_CATALOG), never next to live prices.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Coupon

logger = logging.getLogger(__name__)

OFFERS_FILE = Path(__file__).parent / "data" / "offers.json"


async def load_offers(session: AsyncSession, path: Path = OFFERS_FILE) -> int:
    entries = json.loads(path.read_text())
    now = datetime.now(timezone.utc)
    count = 0
    for e in entries:
        valid_until = None
        if e.get("valid_until"):
            valid_until = datetime.fromisoformat(e["valid_until"]).replace(tzinfo=timezone.utc)
        elif e.get("valid_days"):
            valid_until = now + timedelta(days=int(e["valid_days"]))
        fields = {
            "offer_kind": e.get("offer_kind", "coupon"),
            "code": e.get("code"),
            "description": e.get("description"),
            "discount_type": e["discount_type"],
            "discount_value": float(e["discount_value"]),
            "min_order_value": e.get("min_order_value"),
            "max_discount": e.get("max_discount"),
            "bank_name": e.get("bank_name"),
            "card_type": e.get("card_type"),
            "categories": e.get("categories"),
            "valid_from": None,
            "valid_until": valid_until,
            "is_active": True,
            "is_demo": bool(e.get("demo", False)),
            "source_url": e.get("source_url"),
        }
        existing = await session.scalar(
            select(Coupon).where(Coupon.platform == e["platform"], Coupon.title == e["title"])
        )
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
        else:
            session.add(Coupon(platform=e["platform"], title=e["title"], **fields))
        count += 1
    await session.flush()
    logger.info("loaded %d offers from %s", count, path.name)
    return count


async def expire_offers(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(Coupon).where(Coupon.is_active.is_(True), Coupon.valid_until < now).values(is_active=False)
    )
    return result.rowcount or 0
