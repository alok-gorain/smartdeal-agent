"""Fake discount detection.

Stores often inflate the MRP so a normal price looks like a big discount.
We ignore the MRP and compare today's price with what the product actually
sold for: the median of the last 90 days (median, so a one-day sale or a
price glitch doesn't skew it).
"""

from statistics import median

from sqlalchemy.ext.asyncio import AsyncSession

from models import Product
from services.platforms.base import is_trusted, platform_label
from services.price_history import get_records

WINDOW_DAYS = 90
MIN_DAYS = 30  # below this the verdict is marked low-confidence
GENUINE_PCT = 12.0  # real saving needed for a "genuine deal"
FAKE_PCT = 5.0  # real saving below this = no real discount
CLAIM_GAP_PCT = 10.0  # claimed discount must exceed the real one by this much to call it fake

ABOVE_PCT = 5.0  # this much over the usual price = "above usual"

VERDICTS = {
    "HIGH": "📈 ABOVE USUAL PRICE",
    "FAKE": "🚩 FAKE DISCOUNT",
    "MINOR": "⚠️ MINOR DISCOUNT",
    "GENUINE": "✅ GENUINE DEAL",
    "REGULAR": "ℹ️ REGULAR PRICE",
    "UNKNOWN": "❔ NOT ENOUGH DATA",
}


def classify(price: float, mrp: float | None, median_price: float) -> tuple[str, float, float]:
    """Return (verdict, actual_discount_pct, claimed_discount_pct)."""
    claimed = (mrp - price) / mrp * 100 if mrp and mrp > price else 0.0
    actual = (median_price - price) / median_price * 100 if median_price else 0.0
    if actual >= GENUINE_PCT:
        verdict = "GENUINE"
    elif actual >= FAKE_PCT:
        verdict = "MINOR"
    elif claimed >= CLAIM_GAP_PCT and claimed - actual >= CLAIM_GAP_PCT:
        verdict = "FAKE"  # the store claims a discount that isn't really there
    elif actual <= -ABOVE_PCT:
        verdict = "HIGH"  # no real claim, but the price is above what it usually is
    else:
        verdict = "REGULAR"
    return verdict, round(actual, 1), round(claimed, 1)


def _explain(verdict: str, label: str, price: float, mrp: float | None, med: float, actual: float, claimed: float) -> str:
    if verdict == "FAKE":
        vs_usual = (
            f"only {actual:.0f}% below that" if actual >= 1
            else "the same as that" if actual > -1
            else f"{-actual:.0f}% above that"
        )
        return (
            f"{label} shows {claimed:.0f}% off MRP ₹{mrp:,.0f}, but over the last 90 days it usually sold for "
            f"₹{med:,.0f}. Today's ₹{price:,.0f} is {vs_usual} — the MRP is inflated."
        )
    if verdict == "HIGH":
        return (f"₹{price:,.0f} is {abs(actual):.0f}% above the usual 90-day price of ₹{med:,.0f}. "
                "It has been cheaper recently, so this isn't a good time to buy here.")
    if verdict == "GENUINE":
        return f"₹{price:,.0f} is {actual:.0f}% below the usual 90-day price of ₹{med:,.0f}. This is a real drop."
    if verdict == "MINOR":
        return (
            f"₹{price:,.0f} is {int(actual)}% below the usual ₹{med:,.0f}"
            + (f" — much less than the {claimed:.0f}% off MRP shown." if claimed > actual + 5 else ".")
        )
    return f"₹{price:,.0f} is about the usual price (90-day median ₹{med:,.0f}). No special deal right now."


def _daily_lowest(records) -> dict:
    """Lowest price across stores for each day: what a careful shopper could have paid."""
    lows: dict = {}
    for r in records:
        lows[r.recorded_date] = min(lows.get(r.recorded_date, r.price), r.price)
    return lows


async def analyze_listing(session: AsyncSession, product: Product, listing) -> dict:
    """Judge one store's price against what this product usually cost.

    Two references, when there's enough data (a week or more):
    - the store's own 90-day median price ("store"), the classic fake-discount check;
    - the median of the daily lowest price across all stores ("market").
    The LOWER one is used: a store dropping from its own inflated price isn't a deal if
    the product is usually cheaper elsewhere. New stores are judged on the market alone.
    """
    own = await get_records(session, product.id, WINDOW_DAYS, platform=listing.platform)
    lows = _daily_lowest(await get_records(session, product.id, WINDOW_DAYS))
    own_days = len({r.recorded_date for r in own})
    own_median = median(r.price for r in own) if own_days >= 7 else None
    market_median = median(lows.values()) if len(lows) >= 7 else None

    label = platform_label(listing.platform)
    base = {
        "product_id": product.id,
        "product_name": product.name,
        "platform": listing.platform,
        "platform_label": label,
        "current_price": listing.current_price,
        "mrp": listing.mrp,
    }
    if own_median is None and market_median is None:
        days = max(own_days, len(lows))
        return base | {
            "verdict": "UNKNOWN",
            "label": VERDICTS["UNKNOWN"],
            "basis": "none",
            "explanation": f"Only {days} day(s) of price data so far; we need at least a week.",
            "history_days": days,
            "confidence": "none",
        }

    if own_median is not None and (market_median is None or own_median <= market_median):
        basis, med, ref_prices, days = "store", own_median, [r.price for r in own], own_days
    else:
        basis, med, ref_prices, days = "market", market_median, list(lows.values()), len(lows)

    verdict, actual, claimed = classify(listing.current_price, listing.mrp, med)
    mrp_inflation = round((listing.mrp - med) / med * 100, 1) if listing.mrp and listing.mrp > med else 0.0
    explanation = _explain(verdict, label, listing.current_price, listing.mrp, med, actual, claimed)
    if basis == "market":
        explanation += (" (Usual price = the typical lowest price across stores over 90 days"
                        + ("; this store's own history isn't available yet." if own_median is None else ".") + ")")
    return base | {
        "verdict": verdict,
        "label": VERDICTS[verdict],
        "basis": basis,
        "median_90d": round(med),
        "lowest_90d": min(ref_prices),
        "highest_90d": max(ref_prices),
        "actual_discount_pct": actual,
        "claimed_discount_pct": claimed,
        "mrp_inflation_pct": mrp_inflation,
        "explanation": explanation,
        "history_days": days,
        "confidence": "high" if days >= MIN_DAYS else "low",
        "is_synthetic": any(r.is_synthetic for r in own),
    }


async def analyze_product(session: AsyncSession, product_id: int, platform: str | None = None) -> dict | None:
    product = await session.get(Product, product_id)
    if not product or not product.listings:
        return None
    listings = [l for l in product.listings if not platform or l.platform == platform]
    if not listings:
        return None
    results = [await analyze_listing(session, product, l) for l in listings]
    results.sort(key=lambda r: r["current_price"])
    # Headline verdict: the cheapest store we can judge, preferring trusted stores, then a store's own history
    judged = [r for r in results if r["verdict"] != "UNKNOWN"]
    trusted = [r for r in judged if is_trusted(r["platform"])]
    pool = trusted or judged
    own = [r for r in pool if r.get("basis") == "store"]
    primary = (own or pool or results)[0]
    return {"product_id": product.id, "product_name": product.name, "primary": primary, "by_platform": results}


def summarize_analysis(a: dict) -> str:
    lines = [f"Discount check for {a['product_name']}:"]
    for r in a["by_platform"]:
        lines.append(f"- {r['platform_label']}: {r['label']} — {r['explanation']}")
    if a["primary"].get("is_synthetic"):
        lines.append("NOTE: based on synthetic Data history, not observed store prices.")
    return "\n".join(lines)
