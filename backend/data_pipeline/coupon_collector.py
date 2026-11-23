"""Celery task: keep coupons and bank offers current (every 6 hours).

Coupon sites (GrabOn, CouponDunia) forbid scraping and change layout often,
so offers come from the curated `data/offers.json` (edit it, or have a script
fill it from an affiliate network's offer feed). This task expires old offers
and reloads the file.
"""

import asyncio
import logging

from celery_app import celery_app
from core.database import task_session
from data_pipeline.offers_loader import expire_offers, load_offers

logger = logging.getLogger(__name__)


async def refresh() -> dict:
    async with task_session() as session:
        expired = await expire_offers(session)
        loaded = await load_offers(session)
    stats = {"expired": expired, "loaded": loaded}
    logger.info("offers refreshed: %s", stats)
    return stats


@celery_app.task(name="refresh_offers")
def refresh_offers() -> dict:
    return asyncio.run(refresh())


if __name__ == "__main__":
    # Run once at deploy so the DB matches data/offers.json immediately
    print(asyncio.run(refresh()))
