"""Price history queries, aggregated month-wise for charts."""

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import PriceRecord, Product
from services.platforms.base import platform_label
from services.sale_calendar import events_between

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_label(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} '{str(year)[2:]}"


async def get_records(
    session: AsyncSession, product_id: int, days: int, platform: str | None = None
) -> list[PriceRecord]:
    since = date.today() - timedelta(days=days)
    stmt = select(PriceRecord).where(PriceRecord.product_id == product_id, PriceRecord.recorded_date >= since)
    if platform:
        stmt = stmt.where(PriceRecord.platform == platform)
    return list((await session.scalars(stmt.order_by(PriceRecord.recorded_date))).all())


def _month_keys(months: int, today: date) -> list[tuple[int, int]]:
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(keys))


async def get_history(session: AsyncSession, product_id: int, months: int = 12) -> dict | None:
    product = await session.get(Product, product_id)
    if not product:
        return None
    months = max(1, min(months, 24))
    today = date.today()
    records = await get_records(session, product_id, days=months * 31)

    buckets: dict[tuple[int, int, str], list[float]] = defaultdict(list)
    platforms: set[str] = set()
    for r in records:
        buckets[(r.recorded_date.year, r.recorded_date.month, r.platform)].append(r.price)
        platforms.add(r.platform)

    keys = _month_keys(months, today)
    series = []
    for y, m in keys:
        row: dict = {"month": f"{y}-{m:02d}", "label": month_label(y, m)}
        lows = []
        for p in sorted(platforms):
            prices = buckets.get((y, m, p))
            # "<store>" = monthly average, "<store>_low" = lowest price that month (shows sale dips)
            row[p] = round(mean(prices)) if prices else None
            row[f"{p}_low"] = min(prices) if prices else None
            if prices:
                lows.append(min(prices))
        row["lowest"] = min(lows) if lows else None
        series.append(row)

    # Sale events, attached to the month they start in (only months shown on the chart)
    first = date(keys[0][0], keys[0][1], 1)
    shown = {row["label"] for row in series}
    sale_markers: dict[str, list[str]] = defaultdict(list)
    for e in events_between(first, today):
        label = month_label(e.start.year, e.start.month)
        if label in shown:
            sale_markers[label].append(e.name)

    lowest = min(records, key=lambda r: r.price) if records else None
    highest = max(records, key=lambda r: r.price) if records else None
    stats = {}
    for p in sorted(platforms):
        prices = [r.price for r in records if r.platform == p]
        stats[p] = {
            "label": platform_label(p),
            "min": min(prices),
            "max": max(prices),
            "avg": round(mean(prices)),
            "latest": prices[-1],
        }

    # Trend: average of the last month with data vs three months before it
    lows = [row["lowest"] for row in series if row["lowest"] is not None]
    trend = None
    if len(lows) >= 4:
        change = (lows[-1] - lows[-4]) / lows[-4] * 100
        trend = {"change_pct_3m": round(change, 1), "direction": "down" if change < -2 else "up" if change > 2 else "flat"}

    return {
        "product_id": product.id,
        "product_name": product.name,
        "months": months,
        # Most-tracked stores first (the chart shows the first few)
        "platforms": [{"slug": p, "label": platform_label(p)}
                      for p in sorted(platforms, key=lambda p: (-sum(r.platform == p for r in records), p))],
        "series": series,
        "sale_events": [{"label": label, "names": names} for label, names in sale_markers.items()],
        "lowest": {"price": lowest.price, "platform": lowest.platform, "date": lowest.recorded_date.isoformat()} if lowest else None,
        "highest": {"price": highest.price, "platform": highest.platform, "date": highest.recorded_date.isoformat()} if highest else None,
        "stats": stats,
        "trend": trend,
        "data_points": len(records),
        "days_tracked": len({r.recorded_date for r in records}),
        "tracking_since": records[0].recorded_date.isoformat() if records else None,
        # Where the prices came from: SmartDeal's own daily tracking and/or Google Shopping history
        "from_google": any(r.source == "google_history" for r in records),
        "tracked_since": _first_tracked_day(records),
        "is_synthetic": bool(records) and any(r.is_synthetic for r in records),
    }


def _first_tracked_day(records: list[PriceRecord]) -> str | None:
    days = [r.recorded_date for r in records if r.source != "google_history"]
    return min(days).isoformat() if days else None


def summarize_history(h: dict) -> str:
    if not h or not h["data_points"]:
        return "No price history recorded yet for this product."
    if h["days_tracked"] < 7 and not h["is_synthetic"]:
        prices = "; ".join(f"{s['label']} ₹{s['latest']:,.0f}" for s in h["stats"].values())
        return (
            f"Only {h['days_tracked']} day(s) of real price data for {h['product_name']} so far "
            f"(tracking started {h['tracking_since']}); too early for a trend or history. Current prices: {prices}."
        )
    parts = [f"Price history for {h['product_name']} over {h['months']} months ({h['data_points']} data points)."]
    if h["is_synthetic"]:
        parts.append("NOTE: Data history is synthetic and may not reflect observed store prices.")
    elif h.get("from_google"):
        parts.append("Source: Google Shopping price history (real prices; each price holds until the store changed it), "
                     "plus SmartDeal's daily tracking.")
    for slug, s in h["stats"].items():
        parts.append(f"{s['label']}: now ₹{s['latest']:,.0f}, avg ₹{s['avg']:,.0f}, low ₹{s['min']:,.0f}, high ₹{s['max']:,.0f}.")
    if h["lowest"]:
        lo = h["lowest"]
        parts.append(f"All-time low in this window: ₹{lo['price']:,.0f} on {platform_label(lo['platform'])} ({lo['date']}).")
    if h["trend"]:
        parts.append(f"3-month trend: {h['trend']['direction']} ({h['trend']['change_pct_3m']}%).")
    cheapest = min((r for r in h["series"] if r["lowest"]), key=lambda r: r["lowest"], default=None)
    if cheapest:
        parts.append(f"Cheapest month: {cheapest['label']} (avg low ₹{cheapest['lowest']:,.0f}).")
    parts.append("A month-wise chart is shown to the user.")
    return " ".join(parts)
