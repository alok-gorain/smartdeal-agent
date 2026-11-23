"""Public sample dataset: build helpers, loader and catalog search over it."""

import csv
import gzip
from contextlib import asynccontextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from data_pipeline import build_public_dataset as build
from data_pipeline import seed_public_dataset as loader
from models import Base, PriceRecord, Product, ProductListing


def test_mojibake_is_repaired():
    assert build.clean_name("Discovery Toys MarbleworksÃ¢Â® Marble Run") == "Discovery Toys Marbleworks® Marble Run"
    assert build.clean_name("Allwin 360Â° Spin Mop") == "Allwin 360° Spin Mop"
    assert build.clean_name("Pureit Water Purifier\xa0\xa0(Black)") == "Pureit Water Purifier (Black)"


@pytest.mark.parametrize(
    "name,category",
    [
        ("Prestige Atlas Delight Electric Rice Cooker (1.8 L, Blue)", "appliances"),
        ("APPLE iPad (9th Gen) 64 GB ROM 10.2 inch with Wi-Fi Only", "tablets"),
        ("HP 14s Intel Core i3 11th Gen Thin and Light Laptop", "laptops"),
        ("Men Solid Single Breasted Formal Blazer (Blue)", "fashion"),
        ("Delite Kom Flex Engineered Wood TV Entertainment Unit", "furniture"),
        ("Crompton 75 L Desert Air Cooler (White, Teal)", "appliances"),
    ],
)
def test_categories_from_names(name, category):
    assert build.categorize(name) == category


def test_history_dates_are_evenly_spaced():
    today = date(2026, 11, 23)
    dates = build.sample_dates(today)
    weekly = [d for d in dates if (today - d).days % 7 == 0]
    assert dates[-1] == today and len(weekly) == 53
    assert all(today - timedelta(days=365) <= d <= today for d in dates)


def _write_mini_dataset(folder, end: date):
    folder.mkdir()
    with open(folder / "products.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["product_key", "name", "brand", "category", "subcategory", "mrp", "price", "rating",
                    "rating_count", "dataset", "source_ref", "variant_of", "is_augmented"])
        w.writerow(["k1", "Prestige Electric Rice Cooker 1.8 L", "Prestige", "appliances", "", "3995", "2499",
                    "4.3", "120", "zenodo", "z1", "", "0"])
        w.writerow(["k2", "Puma Primary 3 L Backpack", "Puma", "bags", "Backpacks", "1499", "549", "", "",
                    "promptcloud", "p1", "", "0"])
        w.writerow(["k3", "Puma Primary 3 L Backpack (Navy Blue)", "Puma", "bags", "Backpacks", "1499", "559", "",
                    "", "promptcloud", "p1", "k2", "1"])
    with open(folder / "listings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["product_key", "store", "price", "mrp", "rating", "review_count", "delivery_info"])
        for key, price in (("k1", 2499), ("k2", 549), ("k3", 559)):
            w.writerow([key, "flipkart", price, 3995 if key == "k1" else 1499, "4.3", "50", "2–3 days"])
        w.writerow(["k1", "amazon", 2599, 3995, "4.2", "30", "Prime: 1–2 days"])
    with gzip.open(folder / "price_history.csv.gz", "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "product_key", "store", "price", "mrp"])
        for weeks_ago in range(20):
            day = (end - timedelta(weeks=weeks_ago)).isoformat()
            w.writerow([day, "k1", "flipkart", 2999 if weeks_ago else 2499, 3995])
            w.writerow([day, "k1", "amazon", 2999, 3995])
            w.writerow([day, "k2", "flipkart", 549, 1499])
            w.writerow([day, "k3", "flipkart", 559, 1499])


@pytest.fixture
async def sqlite(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pub.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def scope():
        async with maker() as session:
            yield session
            await session.commit()

    monkeypatch.setattr(loader, "task_session", scope)
    yield maker, scope
    await engine.dispose()


async def test_loader_shifts_dates_and_runs_once(tmp_path, sqlite):
    maker, _ = sqlite
    data_dir = tmp_path / "public"
    _write_mini_dataset(data_dir, end=date(2025, 1, 1))  # built long ago

    stats = await loader.load(data_dir)
    assert (stats["products"], stats["listings"], stats["price_records"]) == (3, 4, 80)

    async with maker() as session:
        latest = await session.scalar(select(func.max(PriceRecord.recorded_date)))
        assert latest == date.today()  # dummy dates end on the load day
        product = await session.scalar(select(Product).where(Product.brand == "Prestige"))
        assert product.search_text and "rice" in product.search_text
        assert product.specifications["dataset"] == "zenodo"
        assert product.specifications["base_prices"] == {"flipkart": 2499.0, "amazon": 2599.0}
        assert all(l.source == "demo" for l in (await session.scalars(select(ProductListing))).all())
        assert all(r.is_synthetic for r in (await session.scalars(select(PriceRecord))).all())

    again = await loader.load(data_dir)
    assert again.get("skipped") is True


async def test_catalog_finds_loaded_products(tmp_path, sqlite, monkeypatch):
    _, scope = sqlite
    data_dir = tmp_path / "public"
    _write_mini_dataset(data_dir, end=date.today())
    await loader.load(data_dir)

    from services.platforms import catalog

    monkeypatch.setattr(catalog, "session_scope", scope)
    monkeypatch.setattr(catalog, "demo_data_enabled", lambda: True)
    offers = await catalog.CatalogAdapter().search("rice cookers")  # plural still matches
    assert {o.platform for o in offers} == {"flipkart", "amazon"}
    assert all(o.source == "demo" for o in offers)
    bags = await catalog.CatalogAdapter().search("puma backpack")
    assert {o.name for o in bags} == {"Puma Primary 3 L Backpack", "Puma Primary 3 L Backpack (Navy Blue)"}
