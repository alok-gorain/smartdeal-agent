"""Generate realistic synthetic price history for demo products.

Patterns:
- normal:        ±3% weekly noise, 15–30% drops during the big sales
- inflated_mrp:  normal prices, but the MRP was raised recently (fake discount)
- price_drop:    a genuine price cut in the last 10 days
- new_launch:    launched ~12% higher and drifting down over the year
"""

import random
from datetime import date, timedelta

from services.sale_calendar import event_on

MAJOR_SALES = {"republic_day", "prime_day", "festive", "diwali"}
MINOR_SALES = {"holi", "summer", "independence_day", "black_friday", "year_end"}
FASHION_CATEGORIES = {"fashion", "footwear", "beauty"}


def round_price(p: float) -> float:
    """Indian retail style: ₹1,299 / ₹24,999."""
    if p >= 1000:
        return float(max(round(p / 100) * 100 - 1, 1))
    return float(max(round(p / 10) * 10 - 1, 1))


def generate_history(
    product: dict, platform: str, platform_factor: float, today: date, rng: random.Random, days: int = 365
) -> list[tuple[date, float, float]]:
    """Return [(day, price, mrp)] for the last `days` days (oldest first)."""
    base = product["base_price"] * platform_factor
    mrp = float(product["mrp"])
    pattern = product.get("pattern", "normal")
    is_fashion = product["category"] in FASHION_CATEGORIES

    # One discount depth per sale event, shared by stores, slightly varied per store
    depths: dict[tuple[str, int], float] = {}

    rows = []
    level = 1.0
    for i in range(days, -1, -1):
        day = today - timedelta(days=i)
        if i % 7 == 0 or i == days:
            level = 1 + rng.uniform(-0.03, 0.03)
        price = base * level

        if pattern == "new_launch":
            price *= 1 + 0.12 * (i / days)

        event = event_on(day)
        if event:
            key = (event.key, day.year)
            if key not in depths:
                if event.key in MAJOR_SALES:
                    depths[key] = rng.uniform(0.15, 0.30)
                elif event.key == "eors":
                    depths[key] = rng.uniform(0.25, 0.40) if is_fashion else 0.0
                else:
                    depths[key] = rng.uniform(0.04, 0.10)
            depth = depths[key]
            if event.key == "prime_day" and platform != "amazon":
                depth = 0.04  # other stores run small counter-sales
            if platform not in event.platforms and event.key not in ("prime_day",):
                depth *= 0.4
            price *= 1 - depth * rng.uniform(0.9, 1.1)

        if pattern == "price_drop" and i <= 10:
            price *= 0.84

        day_mrp = mrp
        if pattern == "inflated_mrp" and i <= 45:
            day_mrp = max(mrp, round_price(product["base_price"] * 1.7))

        rows.append((day, round_price(min(price, day_mrp)), day_mrp))
    return rows
