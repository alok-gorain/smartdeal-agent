"""Best time to buy: price history + the Indian sale calendar."""

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean

from sqlalchemy.ext.asyncio import AsyncSession

from models import Product
from services.price_history import MONTH_NAMES, get_records
from services.sale_calendar import SaleEvent, previous_occurrence, upcoming_events

NEAR_LOW_PCT = 3.0  # within 3% of the all-time low -> buy now
WAIT_SAVING_PCT = 7.0  # wait only if a sale is expected to save at least this much
WAIT_HORIZON_DAYS = 45


def _observed_drop(daily: dict[date, float], event: SaleEvent) -> float | None:
    """How much cheaper the product was during `event` vs the 30 days before it."""
    during = [p for d, p in daily.items() if event.start <= d <= event.end]
    before = [p for d, p in daily.items() if event.start - timedelta(days=30) <= d < event.start]
    if not during or not before:
        return None
    drop = (mean(before) - min(during)) / mean(before)
    return max(0.0, drop)


async def predict(session: AsyncSession, product_id: int, today: date | None = None) -> dict | None:
    product = await session.get(Product, product_id)
    if not product or not product.listings:
        return None
    today = today or date.today()
    records = await get_records(session, product_id, days=400)

    best_listing = min(product.listings, key=lambda l: l.current_price)
    current = best_listing.current_price

    # Lowest price across stores for each day
    daily: dict[date, float] = {}
    for r in records:
        daily[r.recorded_date] = min(daily.get(r.recorded_date, r.price), r.price)

    base = {"product_id": product.id, "product_name": product.name, "current_price": current,
            "current_platform": best_listing.platform}
    if len(daily) < 30:
        events = upcoming_events(today, limit=3)
        return base | {
            "action": "UNKNOWN",
            "label": "❔ NOT ENOUGH HISTORY",
            "reason": "We need about a month of prices before predicting. Upcoming sales are listed below.",
            "upcoming_sales": [e.to_dict(today) | {"predicted_price": round(current * (1 - e.typical_discount))} for e in events],
            "confidence": "none",
        }

    last_year = {d: p for d, p in daily.items() if d >= today - timedelta(days=365)}
    avg_price = mean(last_year.values())
    low_day = min(last_year, key=last_year.get)
    lowest = last_year[low_day]

    by_month: dict[int, list[float]] = defaultdict(list)
    for d, p in last_year.items():
        by_month[d.month].append(p)
    cheapest_month = min(by_month, key=lambda m: mean(by_month[m]))

    upcoming = []
    for e in upcoming_events(today, limit=4):
        prev = previous_occurrence(e)
        observed = _observed_drop(daily, prev) if prev else None
        drop = observed if observed is not None else e.typical_discount
        # A sale rarely beats the previous all-time low by much
        predicted = max(round(avg_price * (1 - drop)), round(lowest * 0.97))
        predicted = min(predicted, current)
        upcoming.append(
            e.to_dict(today)
            | {
                "predicted_price": predicted,
                "expected_saving": round(current - predicted),
                "expected_saving_pct": round((current - predicted) / current * 100, 1),
                "based_on": "last year's sale" if observed is not None else "typical sale discount",
            }
        )

    near_low = current <= lowest * (1 + NEAR_LOW_PCT / 100)
    worth_waiting = [
        u for u in upcoming if u["days_until"] <= WAIT_HORIZON_DAYS and u["expected_saving_pct"] >= WAIT_SAVING_PCT
    ]
    live_sale = next((u for u in upcoming if u.get("is_live")), None)

    if near_low:
        action, label = "BUY_NOW", "🟢 BUY NOW"
        reason = f"₹{current:,.0f} is at or near the 12-month low of ₹{lowest:,.0f}."
        wait_days = 0
    elif live_sale and current <= avg_price * 0.95:
        action, label = "BUY_NOW", "🟢 BUY NOW"
        reason = f"{live_sale['name']} is live and the price is {round((1 - current / avg_price) * 100)}% below the yearly average."
        wait_days = 0
    elif worth_waiting:
        nxt = worth_waiting[0]
        action, label = "WAIT", f"🟡 WAIT {nxt['days_until']} DAYS"
        reason = (
            f"{nxt['name']} starts {nxt['start_date']}; expected price about ₹{nxt['predicted_price']:,.0f} "
            f"(save ~₹{nxt['expected_saving']:,.0f}, {nxt['expected_saving_pct']}%)."
        )
        wait_days = nxt["days_until"]
    elif current <= avg_price * 0.92:
        action, label = "BUY_NOW", "🟢 BUY NOW"
        reason = f"₹{current:,.0f} is well below the yearly average of ₹{avg_price:,.0f} and no big sale is close."
        wait_days = 0
    else:
        action, label = "BUY_NOW", "🟢 OK TO BUY"
        reason = f"No major sale in the next {WAIT_HORIZON_DAYS} days is likely to cut the price much; ₹{current:,.0f} is a typical price."
        wait_days = 0

    return base | {
        "action": action,
        "label": label,
        "reason": reason,
        "wait_days": wait_days,
        "avg_price": round(avg_price),
        "lowest_ever": lowest,
        "lowest_ever_date": low_day.isoformat(),
        "cheapest_month": MONTH_NAMES[cheapest_month - 1],
        "upcoming_sales": upcoming,
        "confidence": "high" if len(daily) >= 300 else "medium" if len(daily) >= 90 else "low",
        "is_synthetic": any(r.is_synthetic for r in records),
    }


def summarize_prediction(p: dict) -> str:
    lines = [f"Buy timing for {p['product_name']}: {p['label']} — {p['reason']}"]
    if p.get("avg_price"):
        lines.append(
            f"Current best ₹{p['current_price']:,.0f}, 12-month avg ₹{p['avg_price']:,.0f}, "
            f"lowest ₹{p['lowest_ever']:,.0f} on {p['lowest_ever_date']}, usually cheapest in {p['cheapest_month']}."
        )
    for u in p.get("upcoming_sales", []):
        lines.append(f"- {u['name']}: starts {u['start_date']} (in {u['days_until']} days), predicted ₹{u['predicted_price']:,.0f}")
    if p.get("is_synthetic"):
        lines.append("NOTE: based on synthetic demo history.")
    return "\n".join(lines)
