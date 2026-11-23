"""Price-history backfill from Google Shopping (SerpApi google_product)."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, PriceRecord, Product, ProductListing
from services import history_backfill
from services.history_backfill import expand_daily, parse_price_insights

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "google_price_insights_iphone16.json").read_text())
INSIGHTS = FIXTURE["price_insights"]


def test_parse_maps_stores_and_drops_glitches():
    series = parse_price_insights(INSIGHTS)
    assert {"amazon", "croma", "apple", "poorvika"} <= set(series)
    amazon_prices = [price for _, price in series["amazon"]]
    assert 174900.0 not in amazon_prices  # one-day listing glitch (2.6x the usual price)
    assert 62590.0 in amazon_prices  # a real low (Dec 2025) survives
    assert series["amazon"] == sorted(series["amazon"])


def test_expand_daily_holds_each_price_until_it_changes():
    d0 = date(2026, 11, 1)
    daily = dict(expand_daily([(d0, 100.0), (d0 + timedelta(days=3), 90.0)], today=d0 + timedelta(days=5)))
    assert [daily[d0 + timedelta(days=i)] for i in range(6)] == [100.0, 100.0, 100.0, 90.0, 90.0, 90.0]


def test_expand_daily_is_capped_to_the_window():
    today = date(2026, 11, 23)
    daily = expand_daily([(today - timedelta(days=900), 50.0)], today=today, days=365)
    assert len(daily) == 366 and daily[0][0] == today - timedelta(days=365)


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def scope():
        async with maker() as session:
            yield session
            await session.commit()

    monkeypatch.setattr(history_backfill, "session_scope", scope)
    monkeypatch.setattr(history_backfill.settings, "serpapi_key", "test-key")
    monkeypatch.setattr(history_backfill.settings, "history_backfill_enabled", True)
    yield maker
    await engine.dispose()


async def test_backfill_runs_once_and_keeps_tracked_prices(db, monkeypatch):
    today = date.today()
    async with db() as session:
        product = Product(name="Apple iPhone 16 128GB", normalized_name="apple iphone 16 128gb",
                          specifications={"google_tokens": [{"store": "amazon", "token": "tok"}],
                                          "google_product_id": "123"})
        session.add(product)
        await session.flush()
        session.add(ProductListing(product_id=product.id, platform="amazon", current_price=76990.0, source="live"))
        session.add(PriceRecord(product_id=product.id, platform="amazon", price=75000.0, recorded_date=today))
        await session.commit()
        product_id = product.id

    calls = []

    async def fake_fetch(params):
        calls.append(params)
        await asyncio.sleep(0.05)  # let the parallel callers pile up on the lock
        return INSIGHTS

    monkeypatch.setattr(history_backfill, "fetch_price_insights", fake_fetch)

    # history, discount check and buy-timing ask at the same moment
    results = await asyncio.gather(*(history_backfill.ensure_history(product_id) for _ in range(3)))
    assert len(calls) == 1
    assert sorted(r["status"] for r in results) == ["backfilled", "not_needed", "not_needed"]

    async with db() as session:
        rows = (await session.scalars(select(PriceRecord).where(PriceRecord.product_id == product_id))).all()
        today_amazon = next(r for r in rows if r.platform == "amazon" and r.recorded_date == today)
        assert today_amazon.price == 75000.0 and today_amazon.source == "tracked"  # own tracking wins
        backfilled = [r for r in rows if r.source == "google_history"]
        assert len({r.recorded_date for r in backfilled if r.platform == "amazon"}) >= 360
        assert all(not r.is_synthetic for r in backfilled)
        product = await session.get(Product, product_id)
        assert product.specifications.get("history_backfilled_at")

    # a later call does nothing (and costs nothing)
    assert (await history_backfill.ensure_history(product_id))["status"] == "not_needed"
    assert len(calls) == 1


async def test_demo_products_are_never_backfilled(db, monkeypatch):
    async with db() as session:
        product = Product(name="Demo phone", normalized_name="demo phone", specifications={"google_product_id": "1"})
        session.add(product)
        await session.flush()
        session.add(ProductListing(product_id=product.id, platform="amazon", current_price=100.0, source="demo"))
        await session.commit()
        product_id = product.id

    async def fail_fetch(*_args, **_kwargs):
        raise AssertionError("must not call SerpApi for demo products")

    monkeypatch.setattr(history_backfill, "fetch_price_insights", fail_fetch)
    assert (await history_backfill.ensure_history(product_id))["status"] == "not_needed"


async def test_new_store_is_judged_against_the_market(db):
    from services.discount_analyzer import analyze_product

    today = date.today()
    async with db() as session:
        product = Product(name="Phone X", normalized_name="phone x", specifications={})
        session.add(product)
        await session.flush()
        session.add(ProductListing(product_id=product.id, platform="amazon", current_price=60000.0, source="live"))
        session.add(ProductListing(product_id=product.id, platform="small_shop", current_price=52000.0, source="live"))
        for i in range(40):  # Amazon has 40 days of history around ₹60,000
            session.add(PriceRecord(product_id=product.id, platform="amazon", price=60000.0,
                                    recorded_date=today - timedelta(days=i), source="google_history"))
        session.add(PriceRecord(product_id=product.id, platform="small_shop", price=52000.0, recorded_date=today))
        await session.commit()
        product_id = product.id

    async with db() as session:  # fresh session, as in the app
        result = await analyze_product(session, product_id)
    by_store = {r["platform"]: r for r in result["by_platform"]}
    assert by_store["small_shop"]["basis"] == "market"
    assert by_store["small_shop"]["verdict"] == "GENUINE"  # 13% below what the product usually costs
    assert result["primary"]["platform"] == "amazon"  # headline prefers a store with its own history


async def test_tries_next_link_when_first_has_no_history(db, monkeypatch):
    async with db() as session:
        product = Product(name="Sony WH-1000XM5", normalized_name="sony wh1000xm5", specifications={
            "google_tokens": [{"store": "ajio", "token": "no-history"}, {"store": "amazon", "token": "has-history"}],
        })
        session.add(product)
        await session.flush()
        session.add(ProductListing(product_id=product.id, platform="amazon", current_price=24989.0, source="live"))
        await session.commit()
        product_id = product.id

    calls = []

    async def fake_fetch(params):
        calls.append(params["page_token"])
        return {} if params["page_token"] == "no-history" else INSIGHTS

    monkeypatch.setattr(history_backfill, "fetch_price_insights", fake_fetch)
    result = await history_backfill.ensure_history(product_id)
    assert result["status"] == "backfilled" and calls == ["no-history", "has-history"]

    async with db() as session:
        spec = (await session.get(Product, product_id)).specifications
    assert len(spec["history_tried"]) == 1  # the empty link won't be paid for again


async def test_daily_refresh_is_capped_and_skips_fresh_products(db, monkeypatch):
    from datetime import datetime, timezone

    from data_pipeline import daily_collector

    today = date.today()
    async with db() as session:
        ids = []
        for i in range(4):
            p = Product(name=f"Product {i}", normalized_name=f"product {i}", specifications={})
            session.add(p)
            await session.flush()
            session.add(ProductListing(product_id=p.id, platform="croma", current_price=1000.0, source="live",
                                       last_updated=datetime(2026, 11, 1 + i, tzinfo=timezone.utc)))
            ids.append(p.id)
        # product 3 (the most recently searched) was already priced today by a search
        session.add(PriceRecord(product_id=ids[3], platform="croma", price=1000.0, recorded_date=today))
        await session.commit()

    monkeypatch.setattr(daily_collector.settings, "price_refresh_daily_limit", 2)
    async with db() as session:
        listings = (await session.scalars(select(ProductListing))).all()
        by_product = {}
        for l in listings:
            by_product.setdefault(l.product_id, []).append(l)
        chosen = await daily_collector._products_to_refresh(session, by_product, today)
    assert chosen == [ids[2], ids[1]]  # newest first, already-fresh product skipped, capped at 2
