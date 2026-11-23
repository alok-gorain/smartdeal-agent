"""Load the public sample dataset (data/public/) into the database as demo data.

    python -m data_pipeline.seed_public_dataset            # load once (skips if already loaded)
    python -m data_pipeline.seed_public_dataset --force    # delete it and load again
    python -m data_pipeline.seed_public_dataset --limit 300

The history's dummy dates are shifted so they end on the day of loading. Also refreshes every
product's search text, which catalog search uses as a SQL prefilter.
"""

import argparse
import asyncio
import csv
import gzip
import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import task_session
from core.logging_config import setup_logging
from data_pipeline.seed_data import search_url
from models import PriceRecord, Product, ProductListing
from services.product_matcher import make_search_text, normalize

logger = logging.getLogger("seed_public")

DATA_DIR = Path(__file__).parent / "data" / "public"
DATASETS = ("promptcloud", "zenodo")
BATCH = 5000


def _num(value: str) -> float | None:
    return float(value) if value not in ("", None) else None


def read_products(data_dir: Path, limit: int | None) -> list[dict]:
    with open(data_dir / "products.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if limit:
        keep = {r["product_key"] for r in rows if not r["variant_of"]}
        keep = set(sorted(keep)[:limit])
        rows = [r for r in rows if r["product_key"] in keep or r["variant_of"] in keep]
    return rows


def read_listings(data_dir: Path, keys: set[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    with open(data_dir / "listings.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["product_key"] in keys:
                out[r["product_key"]].append(r)
    return out


def history_end_date(data_dir: Path) -> date:
    latest = None
    with gzip.open(data_dir / "price_history.csv.gz", "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if latest is None or r["date"] > latest:
                latest = r["date"]
    return date.fromisoformat(latest)


async def is_loaded(session: AsyncSession, data_dir: Path) -> bool:
    with open(data_dir / "products.csv", encoding="utf-8", newline="") as f:
        first = next(csv.DictReader(f))
    found = (await session.scalars(
        select(Product).where(Product.normalized_name == normalize(first["name"])[:500])
    )).all()
    return any((p.specifications or {}).get("dataset") in DATASETS for p in found)


async def delete_dataset(session: AsyncSession) -> int:
    demo_ids = select(ProductListing.product_id).where(ProductListing.source == "demo")
    products = (await session.scalars(select(Product).where(Product.id.in_(demo_ids)))).all()
    ids = [p.id for p in products if (p.specifications or {}).get("dataset") in DATASETS]
    for i in range(0, len(ids), 1000):
        chunk = ids[i:i + 1000]
        await session.execute(delete(PriceRecord).where(PriceRecord.product_id.in_(chunk)))
        await session.execute(delete(ProductListing).where(ProductListing.product_id.in_(chunk)))
        await session.execute(delete(Product).where(Product.id.in_(chunk)))
    return len(ids)


async def refresh_search_text(session: AsyncSession) -> int:
    changed = 0
    for p in (await session.scalars(select(Product))).all():
        text = make_search_text(p.name, p.brand, p.category, (p.specifications or {}).get("tags"))
        if p.search_text != text:
            p.search_text = text
            changed += 1
    return changed


async def load(data_dir: Path = DATA_DIR, force: bool = False, limit: int | None = None) -> dict:
    stats = {"products": 0, "listings": 0, "price_records": 0, "search_text_refreshed": 0}
    async with task_session() as session:
        if force:
            stats["deleted"] = await delete_dataset(session)
            await session.commit()
        if not force and await is_loaded(session, data_dir):
            stats["search_text_refreshed"] = await refresh_search_text(session)
            logger.info("Public dataset already loaded; refreshed search text for %d products.",
                        stats["search_text_refreshed"])
            return stats | {"skipped": True}

        products = read_products(data_dir, limit)
        listings = read_listings(data_dir, {p["product_key"] for p in products})
        shift = date.today() - history_end_date(data_dir)
        now = datetime.now(timezone.utc)

        ids: dict[str, int] = {}
        for i in range(0, len(products), 500):
            chunk = products[i:i + 500]
            objs = []
            for r in chunk:
                tags = [t for t in (r["subcategory"], r["category"].replace("_", " ")) if t]
                objs.append(Product(
                    name=r["name"][:500],
                    normalized_name=normalize(r["name"])[:500],
                    category=r["category"],
                    brand=r["brand"][:200] or None,
                    specifications={
                        "dataset": r["dataset"],
                        "source_ref": r["source_ref"],
                        "subcategory": r["subcategory"],
                        "tags": tags,
                        "augmented": r["is_augmented"] == "1",
                        "variant_of": r["variant_of"] or None,
                        "base_prices": {l["store"]: float(l["price"]) for l in listings[r["product_key"]]},
                    },
                    search_text=make_search_text(r["name"], r["brand"], r["category"], tags),
                ))
            session.add_all(objs)
            await session.flush()
            ids.update({r["product_key"]: o.id for r, o in zip(chunk, objs)})
        stats["products"] = len(ids)

        listing_rows = []
        for r in products:
            for l in listings[r["product_key"]]:
                listing_rows.append({
                    "product_id": ids[r["product_key"]],
                    "platform": l["store"],
                    "platform_product_id": f"PUB-{r['product_key']}-{l['store']}",
                    "title": r["name"][:500],
                    "product_url": search_url(l["store"], r["name"]),
                    "current_price": float(l["price"]),
                    "mrp": _num(l["mrp"]),
                    "rating": _num(l["rating"]),
                    "review_count": int(float(l["review_count"])) if l["review_count"] else None,
                    "in_stock": True,
                    "delivery_info": l["delivery_info"] or None,
                    "source": "demo",
                    "last_updated": now,
                })
        for i in range(0, len(listing_rows), BATCH):
            await session.execute(insert(ProductListing), listing_rows[i:i + BATCH])
        stats["listings"] = len(listing_rows)

        batch = []
        with gzip.open(data_dir / "price_history.csv.gz", "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                pid = ids.get(r["product_key"])
                if pid is None:
                    continue
                day = date.fromisoformat(r["date"]) + shift
                price, mrp = float(r["price"]), _num(r["mrp"])
                batch.append({
                    "product_id": pid,
                    "platform": r["store"],
                    "price": price,
                    "mrp": mrp,
                    "discount_percent": round((mrp - price) / mrp * 100, 1) if mrp and mrp > price else None,
                    "recorded_at": datetime(day.year, day.month, day.day, 6, tzinfo=timezone.utc),
                    "recorded_date": day,
                    "is_synthetic": True,
                    "source": "synthetic",
                })
                if len(batch) >= BATCH:
                    await session.execute(insert(PriceRecord), batch)
                    stats["price_records"] += len(batch)
                    batch = []
        if batch:
            await session.execute(insert(PriceRecord), batch)
            stats["price_records"] += len(batch)

        stats["search_text_refreshed"] = await refresh_search_text(session)
    logger.info("Loaded public dataset: %s", stats)
    return stats


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="delete the loaded dataset and load it again")
    parser.add_argument("--limit", type=int, default=None, help="load only this many base products")
    args = parser.parse_args()
    asyncio.run(load(force=args.force, limit=args.limit))


if __name__ == "__main__":
    main()
