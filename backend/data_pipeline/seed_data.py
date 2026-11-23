"""Seed the database with 50 demo products across Indian stores, 12 months of
synthetic price history, and 20 coupons / bank offers.

    python -m data_pipeline.seed_data            # only if the DB is empty
    python -m data_pipeline.seed_data --force    # wipe demo data and reseed
"""

import argparse
import asyncio
import json
import logging
import random
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote, quote_plus

from sqlalchemy import delete, func, insert, select

from core.database import task_session
from core.logging_config import setup_logging
from data_pipeline.offers_loader import load_offers
from data_pipeline.synthetic_history import generate_history
from models import PriceRecord, Product, ProductListing
from services.product_matcher import make_search_text, normalize

logger = logging.getLogger("seed")

PRODUCTS_FILE = Path(__file__).parent / "data" / "seed_products.json"

STORES_BY_CATEGORY = {
    "mobiles": ["amazon", "flipkart", "croma", "reliance_digital", "vijay_sales", "tata_cliq"],
    "laptops": ["amazon", "flipkart", "croma", "reliance_digital", "vijay_sales", "tata_cliq"],
    "audio": ["amazon", "flipkart", "croma", "reliance_digital", "tata_cliq", "myntra"],
    "tv": ["amazon", "flipkart", "croma", "reliance_digital", "vijay_sales"],
    "appliances": ["amazon", "flipkart", "croma", "reliance_digital", "vijay_sales"],
    "fashion": ["amazon", "flipkart", "myntra", "ajio", "tata_cliq"],
    "footwear": ["amazon", "flipkart", "myntra", "ajio", "tata_cliq"],
    "beauty": ["amazon", "flipkart", "nykaa", "myntra"],
}
ALWAYS = {"amazon", "flipkart"}

DELIVERY = {
    "amazon": "Prime: 1–2 days",
    "flipkart": "2–3 days",
    "myntra": "3–4 days",
    "croma": "2–4 days / store pickup",
    "reliance_digital": "3–5 days / store pickup",
    "vijay_sales": "3–5 days",
    "tata_cliq": "4–6 days",
    "ajio": "4–6 days",
    "nykaa": "3–5 days",
}


def search_url(platform: str, name: str) -> str:
    q = quote_plus(name)
    return {
        "amazon": f"https://www.amazon.in/s?k={q}",
        "flipkart": f"https://www.flipkart.com/search?q={q}",
        "myntra": f"https://www.myntra.com/{quote(name.lower().replace(' ', '-'))}",
        "croma": f"https://www.croma.com/searchB?q={q}",
        "reliance_digital": f"https://www.reliancedigital.in/search?q={q}",
        "vijay_sales": f"https://www.vijaysales.com/search/{quote(name)}",
        "tata_cliq": f"https://www.tatacliq.com/search/?searchCategory=all&text={q}",
        "ajio": f"https://www.ajio.com/search/?text={q}",
        "nykaa": f"https://www.nykaa.com/search/result/?q={q}",
        "jiomart": f"https://www.jiomart.com/search/{quote(name)}",
        "pepperfry": f"https://www.pepperfry.com/site_product/search?q={q}",
        "firstcry": f"https://www.firstcry.com/search?q={q}",
        "decathlon": f"https://www.decathlon.in/search?query={q}",
    }.get(platform, f"https://www.google.com/search?tbm=shop&q={q}")


async def seed(force: bool = False) -> None:
    async with task_session() as session:
        existing = await session.scalar(select(func.count(Product.id)))
        if existing and not force:
            logger.info("Database already has %d products; skipping seed (use --force to reseed).", existing)
            return
        if force:
            demo_ids = select(ProductListing.product_id).where(ProductListing.source == "demo")
            await session.execute(delete(Product).where(Product.id.in_(demo_ids)))
            await session.flush()

        products = json.loads(PRODUCTS_FILE.read_text())
        today = date.today()
        now = datetime.now(timezone.utc)
        total_records = 0

        for idx, item in enumerate(products):
            rng = random.Random(1000 + idx)
            product = Product(
                name=item["name"],
                normalized_name=normalize(item["name"]),
                category=item["category"],
                brand=item["brand"],
                model_number=item.get("model_number"),
                image_url=item.get("image_url"),
                specifications={**item.get("specs", {}), "tags": item.get("tags", [])},
                search_text=make_search_text(item["name"], item["brand"], item["category"], item.get("tags")),
            )
            session.add(product)
            await session.flush()

            pool = STORES_BY_CATEGORY.get(item["category"], ["amazon", "flipkart"])
            extra = [p for p in pool if p not in ALWAYS]
            stores = sorted(ALWAYS | set(rng.sample(extra, k=min(len(extra), rng.randint(1, 3)))))

            records = []
            for platform in stores:
                factor = 1.0 if platform == "amazon" else rng.uniform(0.95, 1.08)
                history = generate_history(item, platform, factor, today, rng)
                for day, price, mrp in history:
                    records.append({
                        "product_id": product.id,
                        "platform": platform,
                        "price": price,
                        "mrp": mrp,
                        "discount_percent": round((mrp - price) / mrp * 100, 1) if mrp > price else None,
                        "recorded_at": datetime(day.year, day.month, day.day, 6, tzinfo=timezone.utc),
                        "recorded_date": day,
                        "is_synthetic": True,
                    })
                _, current, current_mrp = history[-1]
                session.add(ProductListing(
                    product_id=product.id,
                    platform=platform,
                    platform_product_id=f"DEMO-{product.id}-{platform}",
                    title=item["name"],
                    product_url=search_url(platform, item["name"]),
                    current_price=current,
                    mrp=current_mrp,
                    rating=round(min(5.0, max(1.0, item["rating"] + rng.uniform(-0.2, 0.1))), 1),
                    review_count=int(item["reviews"] * rng.uniform(0.2, 1.0)),
                    in_stock=rng.random() > 0.05,
                    seller_name=None,
                    delivery_info=DELIVERY.get(platform),
                    source="demo",
                    last_updated=now,
                ))
            await session.execute(insert(PriceRecord), records)
            total_records += len(records)

        offers = await load_offers(session)
        logger.info("Seeded %d products, %d price records, %d offers.", len(products), total_records, offers)


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="delete demo products and reseed")
    args = parser.parse_args()
    asyncio.run(seed(force=args.force))


if __name__ == "__main__":
    main()
