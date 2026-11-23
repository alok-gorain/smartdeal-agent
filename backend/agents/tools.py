"""Agent tools.

Each tool returns text for the LLM plus a structured `artifact`
({"kind": ..., "data": ...}) that the chat API forwards to the UI, which
renders product cards, comparison tables, charts and badges from it.
"""

import logging
from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from core.database import session_scope
from services import (
    coupon_service,
    discount_analyzer,
    history_backfill,
    prediction_service,
    price_history,
    search_service,
)
from services.platforms.base import platform_label

logger = logging.getLogger(__name__)


def _errors_note(errors: dict) -> str:
    if not errors:
        return ""
    return "\nStores that failed this time: " + "; ".join(f"{k}: {v}" for k, v in errors.items())


@tool
async def search_products(
    query: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    category: Optional[str] = None,
    platforms: Optional[list[str]] = None,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
) -> Command:
    """Search all Indian stores at once (Amazon, Flipkart, Myntra, Croma, Reliance Digital, Tata CLiQ, AJIO, Nykaa, ...).

    Returns products matched across stores with each store's price, rating and best coupon/bank offer.

    Args:
        query: short product words only, e.g. "noise cancelling earbuds" or "iPhone 16 128GB".
        category: optional hint, e.g. mobiles, laptops, tablets, audio, tv, cameras, fashion, footwear, jewellery,
            watches, bags, beauty, appliances, kitchen, home, furniture, toys, baby, sports.
        platforms: optional list of store slugs to limit to, e.g. ["amazon", "flipkart"].
        budget_min: optional minimum price in rupees.
        budget_max: optional maximum price in rupees.
    """
    result = await search_service.search_products(
        query, category=category, platforms=platforms, budget_min=budget_min, budget_max=budget_max
    )
    groups = result["groups"]
    content = (
        f"Found {result['total_found']} products for \"{query}\" (showing {len(groups)}), ranked by effective price.\n"
        + search_service.summarize_groups(groups)
        + _errors_note(result["errors"])
    )
    artifact = {"kind": "products", "data": {"title": f"Results for “{query}”", **result}}
    filters = {k: v for k, v in {"budget_min": budget_min, "budget_max": budget_max, "platforms": platforms}.items() if v}
    update = {
        "last_search": {"query": query, "category": category, "groups": groups},
        "filters": filters,
        "messages": [ToolMessage(content, artifact=artifact, tool_call_id=tool_call_id)],
    }
    if groups and groups[0].get("product_id"):
        update["focus_product_id"] = groups[0]["product_id"]
    return Command(update=update)


@tool
async def filter_results(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    brand: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    keywords: Optional[list[str]] = None,
    min_rating: Optional[float] = None,
    platforms: Optional[list[str]] = None,
    sort_by: str = "price",
) -> Command:
    """Refine the PREVIOUS search results without searching again.

    Use for follow-ups like "only Samsung", "under ₹2000", "with ANC", "4 stars and above", "only on Flipkart".

    Args:
        brand: keep only this brand.
        min_price: minimum effective price in rupees.
        max_price: maximum effective price in rupees.
        keywords: words that must appear in the product name, e.g. ["ANC"].
        min_rating: minimum star rating, e.g. 4.0.
        platforms: keep only these store slugs, e.g. ["flipkart"].
        sort_by: "price", "rating" or "savings".
    """
    search = state.get("last_search") or {}
    groups = search.get("groups") or []
    if not groups:
        msg = "There are no previous results to filter. Call search_products first."
        return Command(update={"messages": [ToolMessage(msg, tool_call_id=tool_call_id)]})

    filters = {**(state.get("filters") or {})}
    filters.update({k: v for k, v in {
        "brand": brand, "min_price": min_price, "max_price": max_price, "keywords": keywords,
        "min_rating": min_rating, "platforms": platforms, "sort_by": sort_by,
    }.items() if v is not None})
    filtered = search_service.filter_groups(
        groups,
        brand=filters.get("brand"),
        min_price=filters.get("min_price"),
        max_price=filters.get("max_price"),
        keywords=filters.get("keywords"),
        min_rating=filters.get("min_rating"),
        platforms=filters.get("platforms"),
        sort_by=filters.get("sort_by", "price"),
    )
    content = (
        f"{len(filtered)} of {len(groups)} previous results match filters {filters}.\n"
        + search_service.summarize_groups(filtered)
    )
    artifact = {
        "kind": "products",
        "data": {"title": f"Refined: “{search.get('query')}”", "query": search.get("query"), "groups": filtered,
                 "filters": filters, "errors": {}, "total_found": len(filtered)},
    }
    update = {"filters": filters, "messages": [ToolMessage(content, artifact=artifact, tool_call_id=tool_call_id)]}
    if filtered and filtered[0].get("product_id"):
        update["focus_product_id"] = filtered[0]["product_id"]
    return Command(update=update)


@tool(response_format="content_and_artifact")
async def compare_prices(product_name: str, product_id: Optional[int] = None) -> tuple[str, dict | None]:
    """Compare ONE specific product across all stores: price, rating, delivery, best offer and effective price.

    Args:
        product_name: the exact product, e.g. "Samsung Galaxy S24 256GB".
        product_id: optional product_id from earlier results, to pick the exact match.
    """
    result = await search_service.search_products(product_name, max_results=5)
    groups = result["groups"]
    if not groups:
        return f"Could not find \"{product_name}\" in any store." + _errors_note(result["errors"]), None
    group = next((g for g in groups if product_id and g.get("product_id") == product_id), groups[0])
    rows = []
    for o in group["offers"]:
        rows.append({
            "platform": o["platform"],
            "platform_label": o["platform_label"],
            "price": o["price"],
            "mrp": o.get("mrp"),
            "rating": o.get("rating"),
            "review_count": o.get("review_count"),
            "delivery_info": o.get("delivery_info"),
            "in_stock": o.get("in_stock", True),
            "url": o.get("url"),
            "trusted": o.get("trusted", True),
            "best_deal": o.get("best_deal"),
            "effective_price": o.get("effective_price", o["price"]),
        })
    rows.sort(key=lambda r: r["effective_price"])
    best = rows[0]
    savings = [{"platform": r["platform"], "platform_label": r["platform_label"],
                "amount": round(r["effective_price"] - best["effective_price"])} for r in rows[1:]]
    data = {
        "product_id": group.get("product_id"),
        "name": group["name"],
        "image_url": group.get("image_url"),
        "is_demo": group.get("is_demo", False),
        "rows": rows,
        "best_platform": best["platform"],
        "best_platform_label": best["platform_label"],
        "savings": savings,
    }
    lines = [f"Comparison for {group['name']} [product_id={group.get('product_id')}]:"]
    for r in rows:
        deal = f", with {r['best_deal']['title']} → ₹{r['effective_price']:,.0f}" if r.get("best_deal") else ""
        lines.append(f"- {r['platform_label']}: ₹{r['price']:,.0f}{deal}; rating {r.get('rating') or 'n/a'}; delivery {r.get('delivery_info') or 'n/a'}")
    if savings:
        lines.append(f"Cheapest on {best['platform_label']}; saves up to ₹{max(s['amount'] for s in savings):,.0f}.")
    if group.get("is_demo"):
        lines.append("NOTE: demo data.")
    return "\n".join(lines) + _errors_note(result["errors"]), {"kind": "comparison", "data": data}


@tool(response_format="content_and_artifact")
async def get_price_history(product_id: int, months: int = 12) -> tuple[str, dict | None]:
    """Month-wise price history for a product on every store (shown to the user as a chart with sale events).

    Args:
        product_id: product_id from search results.
        months: how many months back, 1-24 (default 12).
    """
    await history_backfill.ensure_history(product_id)  # first look at a new product: load Google's history
    async with session_scope() as session:
        history = await price_history.get_history(session, product_id, months)
    if not history:
        return f"No product with id {product_id}.", None
    return price_history.summarize_history(history), {"kind": "history", "data": history}


@tool(response_format="content_and_artifact")
async def analyze_discount(product_id: int, platform: Optional[str] = None) -> tuple[str, dict | None]:
    """Check whether a product's discount is real or the MRP is inflated (compares today's price with the 90-day median).

    Args:
        product_id: product_id from search results.
        platform: optional store slug; default checks every store.
    """
    await history_backfill.ensure_history(product_id)
    async with session_scope() as session:
        analysis = await discount_analyzer.analyze_product(session, product_id, platform)
    if not analysis:
        return f"No price data for product {product_id}.", None
    return discount_analyzer.summarize_analysis(analysis), {"kind": "discount", "data": analysis}


@tool(response_format="content_and_artifact")
async def predict_best_buy_time(product_id: int) -> tuple[str, dict | None]:
    """Predict whether to buy now or wait, using price history and the Indian sale calendar
    (Republic Day, Prime Day, Independence Day, Big Billion Days / Great Indian Festival, Diwali, Black Friday, Year-end).

    Args:
        product_id: product_id from search results.
    """
    await history_backfill.ensure_history(product_id)
    async with session_scope() as session:
        prediction = await prediction_service.predict(session, product_id)
    if not prediction:
        return f"No price data for product {product_id}.", None
    return prediction_service.summarize_prediction(prediction), {"kind": "timing", "data": prediction}


@tool(response_format="content_and_artifact")
async def find_coupons(
    platform: Optional[str] = None,
    category: Optional[str] = None,
    bank_name: Optional[str] = None,
    price: Optional[float] = None,
) -> tuple[str, dict | None]:
    """Find active coupons and bank card offers (SBI, HDFC, ICICI, Axis, ...).

    Args:
        platform: store slug, e.g. "amazon". Omit for all stores.
        category: product category, e.g. "mobiles".
        bank_name: e.g. "HDFC".
        price: order value in rupees, to calculate the exact saving of each offer.
    """
    async with session_scope() as session:
        coupons = await coupon_service.active_coupons(session, platform, category, bank_name)
    items = [coupon_service.coupon_to_dict(c, price) for c in coupons]
    if price is not None:
        items.sort(key=lambda c: -c.get("saving", 0))
    if not items:
        from services.platforms.catalog import demo_data_enabled

        if not demo_data_enabled():
            return (
                "SmartDeal has no live coupon/bank-offer feed connected, so offers can't be checked right now "
                "(sample offers are hidden in live mode). Tell the user to check the store's product page for "
                "current card offers.",
                None,
            )
        return "No active coupons or bank offers match.", None
    lines = [f"{len(items)} active offers:"]
    for c in items[:12]:
        saving = f" → saves ₹{c['saving']:,.0f}" if c.get("saving") else ""
        code = f" code {c['code']}" if c.get("code") else ""
        lines.append(f"- [{platform_label(c['platform'])}] {c['title']}{code}{saving} (valid till {c.get('valid_until') or 'n/a'})")
    data = {"platform": platform, "bank_name": bank_name, "price": price, "items": items}
    return "\n".join(lines), {"kind": "coupons", "data": data}


TOOLS = [
    search_products,
    filter_results,
    compare_prices,
    get_price_history,
    analyze_discount,
    predict_best_buy_time,
    find_coupons,
]

# Status lines streamed to the UI while a tool runs
THINKING_MESSAGES = {
    "search_products": "🔍 Searching {stores}…",
    "filter_results": "🔎 Refining your results…",
    "compare_prices": "⚖️ Comparing prices across stores…",
    "get_price_history": "📊 Loading 12-month price history…",
    "analyze_discount": "🧾 Checking if the discount is real…",
    "predict_best_buy_time": "📅 Checking the sale calendar…",
    "find_coupons": "🏷️ Finding coupons & bank offers…",
}
