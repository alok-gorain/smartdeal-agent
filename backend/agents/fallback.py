"""Rule-based assistant used when no Gemini key is set or the model is unavailable.

It understands the common requests (search, budget, refine, compare, history,
fake-discount check, buy timing, coupons) with simple patterns, so the app is
fully usable as a demo without an LLM.
"""

import re
from collections.abc import Awaitable, Callable

from agents.tools import (
    analyze_discount,
    compare_prices,
    filter_results,
    find_coupons,
    get_price_history,
    predict_best_buy_time,
    search_products,
)
from core.database import session_scope
from models import Product

Emit = Callable[[str], Awaitable[None]]

_BUDGET_RE = re.compile(
    r"(under|below|less than|upto|up to|within|max|<)\s*(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d+)?)\s*(k)?", re.I
)
_ABOVE_RE = re.compile(r"(above|over|more than|min|>)\s*(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d+)?)\s*(k)?", re.I)
_ID_RE = re.compile(r"(?:#|product\s*(?:id)?\s*)(\d+)", re.I)
_BANKS = ["sbi", "hdfc", "icici", "axis", "kotak", "idfc", "bob", "au", "onecard", "rbl", "yes"]
_STORES = ["amazon", "flipkart", "myntra", "croma", "ajio", "nykaa", "tata cliq", "reliance digital", "vijay sales", "jiomart"]
_FILLER = re.compile(
    r"\b(show me|show|find me|find|search for|search|look for|i want|i need|get me|best|cheapest|good|"
    r"price of|prices of|price for|deals? on|deals? for|please|a|an|the|some|buy|compare prices for|compare|"
    r"under|below|within|upto|up to|rs|inr|now|only|me|prices?|next|and)\b",
    re.I,
)

_INTENT_WORDS = re.compile(
    r"\b(price history|history|chart|trend|graph|is the discount|discount|real|fake|genuine|mrp|"
    r"when should i buy|when to buy|when|should i|wait|best time|buy now|sale|for|on|top pick|this one|this|it|that)\b",
    re.I,
)


async def _product_name(product_id: int, memory: dict) -> str | None:
    for g in (memory.get("last_search") or {}).get("groups", []):
        if g.get("product_id") == product_id:
            return g["name"]
    async with session_scope() as session:
        product = await session.get(Product, product_id)
        return product.name if product else None


# Per-session memory for the fallback (the LLM path uses the LangGraph checkpointer instead)
_sessions: dict[str, dict] = {}


def _amount(m: re.Match) -> float:
    value = float(m.group(2).replace(",", ""))
    return value * 1000 if m.group(3) else value


def _clean_query(text: str) -> str:
    text = _BUDGET_RE.sub(" ", text)
    text = _ABOVE_RE.sub(" ", text)
    text = re.sub(r"[₹?!.,]", " ", text)
    text = _FILLER.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


async def _call(tool, args: dict, memory: dict) -> tuple[str, dict | None]:
    """Invoke a LangChain tool outside the graph and return (content, artifact)."""
    call = {"name": tool.name, "args": args, "id": "fallback", "type": "tool_call"}
    if tool.name == "filter_results":
        call["args"] = {**args, "state": memory}
    result = await tool.ainvoke(call)
    if hasattr(result, "update"):  # Command from search/filter tools
        update = result.update
        for key in ("last_search", "filters", "focus_product_id"):
            if key in update:
                memory[key] = update[key]
        msg = update["messages"][0]
        return msg.content, msg.artifact
    return result.content, getattr(result, "artifact", None)


def _top_lines(groups: list[dict], n: int = 3) -> str:
    lines = []
    for g in groups[:n]:
        cheapest = min(g["offers"], key=lambda o: o["price"])
        lines.append(f"- **{g['name']}** — ₹{cheapest['price']:,.0f} on {cheapest['platform_label']}"
                     + (f" (⭐ {g['rating']})" if g.get("rating") else ""))
    return "\n".join(lines)


async def run_fallback(session_id: str, text: str, emit: Emit) -> dict:
    memory = _sessions.setdefault(session_id, {})
    lower = text.lower()
    blocks: list[dict] = []

    budget_max = _amount(m) if (m := _BUDGET_RE.search(text)) else None
    budget_min = _amount(m) if (m := _ABOVE_RE.search(text)) else None
    id_match = _ID_RE.search(text)
    product_id = int(id_match.group(1)) if id_match else memory.get("focus_product_id")
    if id_match:
        memory["focus_product_id"] = product_id
    # Product words left after removing intent words, ids and references like "top pick"
    named = _clean_query(_INTENT_WORDS.sub(" ", _ID_RE.sub(" ", text))).strip(" ()")

    def add(artifact):
        if artifact:
            blocks.append(artifact)

    wants_history = re.search(r"history|chart|trend|graph", lower)
    wants_discount = re.search(r"fake|genuine|real discount|discount real|is .* discount|mrp", lower)
    wants_timing = re.search(r"when|wait|best time|buy now|should i buy|sale", lower)
    if (wants_history or wants_discount or wants_timing) and named and not id_match:
        # "price history for iPhone 16": find the product first
        await emit("🔍 Finding the product…")
        _, art = await _call(search_products, {"query": named}, memory)
        groups = (art or {}).get("data", {}).get("groups", [])
        if groups and groups[0].get("product_id"):
            product_id = groups[0]["product_id"]
            memory["focus_product_id"] = product_id

    # --- product-specific intents -------------------------------------------------
    if product_id and wants_history:
        await emit("📊 Loading 12-month price history…")
        content, art = await _call(get_price_history, {"product_id": product_id}, memory)
        add(art)
        if not art:
            return {"content": content, "blocks": blocks}
        h = art["data"]
        lines = [f"📊 12-month price history for **{h['product_name']}**."]
        if h.get("lowest"):
            lo = h["lowest"]
            lines.append(f"Lowest: **₹{lo['price']:,.0f}** on {lo['date']}.")
        if h.get("trend"):
            lines.append(f"Last 3 months: {h['trend']['direction']} ({h['trend']['change_pct_3m']}%).")
        return {"content": " ".join(lines), "blocks": blocks}

    if product_id and wants_discount:
        await emit("🧾 Checking if the discount is real…")
        content, art = await _call(analyze_discount, {"product_id": product_id}, memory)
        add(art)
        return {"content": content, "blocks": blocks}

    if product_id and wants_timing:
        await emit("📅 Checking the sale calendar…")
        content, art = await _call(predict_best_buy_time, {"product_id": product_id}, memory)
        add(art)
        return {"content": content, "blocks": blocks}

    if re.search(r"coupon|bank offer|offers?|promo|code|cashback|card", lower) and not re.search(r"compare", lower):
        await emit("🏷️ Finding coupons & bank offers…")
        bank = next((b.upper() for b in _BANKS if re.search(rf"\b{b}\b", lower)), None)
        store = next((s.replace(" ", "_") for s in _STORES if s in lower), None)
        content, art = await _call(find_coupons, {"platform": store, "bank_name": bank}, memory)
        add(art)
        return {"content": "🏷️ " + content, "blocks": blocks}

    # --- refine previous results -------------------------------------------------
    refine = memory.get("last_search") and re.match(r"\s*(now |show |filter |just |only |what about )?(only|under|below|with|from|sort|cheaper|above)", lower)
    if refine:
        await emit("🔎 Refining your results…")
        args: dict = {}
        if budget_max:
            args["max_price"] = budget_max
        if budget_min:
            args["min_price"] = budget_min
        if "rating" in lower:
            args["sort_by"] = "rating"
        store = [s.replace(" ", "_") for s in _STORES if s in lower]
        if store:
            args["platforms"] = store
        words = [w for w in _clean_query(lower).split() if w not in {"with", "from", "sort", "by", "rating", "cheaper", "above", "on"}]
        words = [w for w in words if w.replace(" ", "_") not in store]
        if words:
            args["keywords"] = words
        content, art = await _call(filter_results, args, memory)
        add(art)
        groups = (art or {}).get("data", {}).get("groups", [])
        msg = f"🔎 {len(groups)} products match." + (f"\n\n{_top_lines(groups)}" if groups else " Try loosening the filters.")
        return {"content": msg, "blocks": blocks}

    # --- compare one product -------------------------------------------------------
    if re.search(r"\bcompare\b", lower):
        name = named
        pid = int(id_match.group(1)) if id_match else (None if name else product_id)
        if not name and pid:
            name = await _product_name(pid, memory)
        if not name:
            return {"content": "Which product should I compare? e.g. *\"compare iPhone 16 128GB\"*.", "blocks": []}
        await emit("⚖️ Comparing prices across stores…")
        content, art = await _call(compare_prices, {"product_name": name, "product_id": pid}, memory)
        add(art)
        if art:
            memory["focus_product_id"] = art["data"].get("product_id")
        return {"content": "⚖️ " + content, "blocks": blocks}

    # --- default: search -------------------------------------------------------------
    query = _clean_query(text)
    if not query:
        return {
            "content": "Tell me what you're shopping for — e.g. *\"ANC earbuds under ₹3000\"* or *\"iPhone 16\"*.",
            "blocks": [],
        }
    await emit("🔍 Searching every store…")
    args = {"query": query}
    if budget_max:
        args["budget_max"] = budget_max
    if budget_min:
        args["budget_min"] = budget_min
    content, art = await _call(search_products, args, memory)
    add(art)
    groups = (art or {}).get("data", {}).get("groups", [])
    if not groups:
        errors = (art or {}).get("data", {}).get("errors") or {}
        note = ("\n\nSome stores failed: " + ", ".join(errors)) if errors else ""
        return {"content": f"I couldn't find anything for **{query}**. Try a simpler name.{note}", "blocks": blocks}

    top = groups[0]
    pid = top.get("product_id")
    best = top["offers"][0]
    deal = f" (₹{best['effective_price']:,.0f} with {best['best_deal']['title']})" if best.get("best_deal") else ""
    msg = [f"### 🏆 Top Pick: {top['name']}",
           f"**₹{best['price']:,.0f}** on {best['platform_label']}{deal}"
           + (f" — ₹{nxt['price'] - best['price']:,.0f} less than {nxt['platform_label']}, the next cheapest."
              if (nxt := next((o for o in sorted(top["offers"], key=lambda o: o["price"]) if o["price"] > best["price"]), None))
              else ".")]
    if len(groups) > 1:
        msg.append("\n**Other options:**\n" + _top_lines(groups[1:], 4))
    if pid:
        await emit("🧾 Checking if the discount is real…")
        _, disc = await _call(analyze_discount, {"product_id": pid}, memory)
        await emit("📅 Checking the sale calendar…")
        _, timing = await _call(predict_best_buy_time, {"product_id": pid}, memory)
        add(disc)
        add(timing)
        if disc:
            msg.append(f"\n🧾 **Discount check:** {disc['data']['primary']['label']}")
        if timing:
            msg.append(f"📅 **Buy timing:** {timing['data']['label']} — {timing['data']['reason']}")
    if top.get("is_demo"):
        msg.append("\n_Prices shown are sample data from the demo catalog._")
    msg.append("\nWant the price history chart, or should I narrow these down (brand, budget, features)?")
    return {"content": "\n\n".join(m.strip("\n") for m in msg), "blocks": blocks}
