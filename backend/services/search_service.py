"""Search every active store in parallel, match products across stores, rank by effective price."""

import asyncio
import hashlib
import json
import re
import logging

from core.config import settings
from core.database import session_scope
from core.redis_client import cache_get, cache_set
from services import catalog_service, coupon_service
from services.platforms.base import Offer, platform_label
from services.platforms.registry import active_adapters
from services.product_matcher import _UNIT_SUFFIX_RE, group_offers, normalize

logger = logging.getLogger(__name__)


async def _run_adapter(adapter, query: str, category: str | None, max_results: int):
    try:
        offers = await asyncio.wait_for(
            adapter.search(query, category=category, max_results=max_results),
            timeout=settings.adapter_timeout_seconds,
        )
        return adapter.slug, offers, None
    except asyncio.TimeoutError:
        logger.warning("%s timed out for %r", adapter.slug, query)
        return adapter.slug, [], "timed out"
    except Exception as exc:  # noqa: BLE001 - one store failing must never break the search
        logger.warning("%s failed for %r: %s", adapter.slug, query, exc)
        return adapter.slug, [], str(exc)[:200]


CACHE_VERSION = 10  # bump when matching/grouping logic changes


def _cache_key(query: str, category: str | None, max_results: int) -> str:
    # Include the active sources so adding an API key doesn't serve results cached from before
    sources = sorted(a.slug for a in active_adapters()) + [str(settings.demo_catalog), CACHE_VERSION]
    raw = json.dumps([query.lower().strip(), (category or "").lower(), max_results, sources])
    return "search:" + hashlib.sha1(raw.encode()).hexdigest()


def model_tokens(query: str) -> list[str]:
    """Model-number words in a query ("16", "1000xm5", "s24"), ignoring units like 128gb or 5g."""
    return [
        t for t in normalize(query).replace('"', " ").split()
        if any(ch.isdigit() for ch in t) and not _UNIT_SUFFIX_RE.match(t)
        and not (t.isdigit() and int(t) >= 1000)  # "15000" in a query is a budget, not a model
    ]


_ENC_ONLY = re.compile(r"\benc\b", re.I)
_ANC_TITLE = re.compile(r"\banc\b|active noise|hybrid (?:anc|noise)|\b\d*nc\b", re.I)

# Must-have features: (query pattern, test on the result title)
FEATURE_RULES = [
    # ANC: ENC/"AI-ENC" only cleans up calls, so it doesn't count
    (re.compile(r"\banc\b|noise[- ]cancel", re.I),
     lambda t: bool(_ANC_TITLE.search(t)) or (bool(re.search(r"noise[- ]cancel", t, re.I)) and not _ENC_ONLY.search(t))),
    (re.compile(r"\b5g\b", re.I), lambda t: bool(re.search(r"\b5g\b", t, re.I))),
    (re.compile(r"\boled\b", re.I), lambda t: bool(re.search(r"oled", t, re.I))),
    (re.compile(r"\bqled\b", re.I), lambda t: bool(re.search(r"\bqled\b", t, re.I))),
    (re.compile(r"\b4k\b|\buhd\b", re.I), lambda t: bool(re.search(r"\b4k\b|\buhd\b|2160p", t, re.I))),
]


def has_required_features(title: str, query: str) -> bool:
    return all(test(title) for pattern, test in FEATURE_RULES if pattern.search(query))


def is_relevant(title: str, query: str) -> bool:
    """For model-specific searches, keep only results that mention that model.

    Shopping aggregators pad specific searches ("Sony WH-1000XM5") with popular but
    unrelated products. Generic searches ("ANC earbuds") have no model numbers and
    keep everything.
    """
    if not has_required_features(title, query):
        return False
    wanted = model_tokens(query)
    if not wanted:
        return True
    norm = normalize(title).replace('"', " ")  # 55" -> 55
    tokens = set(norm.split())
    squashed = norm.replace(" ", "")
    for t in wanted:
        if t in tokens:
            continue
        if len(t) >= 4 and t in squashed:  # "1000xm5" inside "wh1000xm5"
            continue
        return False
    return True


async def _fresh_search(query: str, category: str | None, max_results: int, persist: bool) -> dict:
    adapters = active_adapters()
    results = await asyncio.gather(*(_run_adapter(a, query, category, max_results) for a in adapters))

    offers: list[Offer] = []
    errors: dict[str, str] = {}
    for slug, found, error in results:
        offers.extend(found)
        if error:
            errors[slug] = error
    for o in offers:
        o.category = o.category or category
    before = len(offers)
    offers = [o for o in offers if is_relevant(o.name, query)]
    if len(offers) < before:
        logger.info("dropped %d results that don't mention the model asked for", before - len(offers))

    groups = await group_offers(offers)
    if persist and groups:
        try:
            async with session_scope() as session:
                await catalog_service.persist_groups(session, groups)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not store search results: %s", exc)

    return {
        "query": query,
        "category": category,
        "searched": [a.label for a in adapters],
        "errors": errors,
        "groups": [g.to_dict() for g in groups],
    }


async def _attach_offers(groups: list[dict]) -> None:
    """Add the best coupon/bank offer and effective price to every store offer."""
    try:
        async with session_scope() as session:
            coupons = await coupon_service.active_coupons(session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not load coupons: %s", exc)
        coupons = []
    for g in groups:
        for o in g["offers"]:
            deal = coupon_service.best_deal(coupons, o["platform"], g.get("category"), o["price"])
            o["best_deal"] = deal
            o["effective_price"] = deal["effective_price"] if deal else o["price"]
        g["offers"].sort(key=lambda o: o["effective_price"])
        best = g["offers"][0]
        g["best_effective_price"] = best["effective_price"]
        g["best_effective_platform"] = best["platform"]


async def search_products(
    query: str,
    category: str | None = None,
    platforms: list[str] | None = None,
    budget_min: float | None = None,
    budget_max: float | None = None,
    max_results: int = 8,
    use_cache: bool = True,
    persist: bool = True,
) -> dict:
    query = query.strip()
    category = category.lower().strip() if category else None
    key = _cache_key(query, category, max_results)
    payload = await cache_get(key) if use_cache else None
    if payload is None:
        payload = await _fresh_search(query, category, max_results, persist)
        if use_cache and payload["groups"]:
            await cache_set(key, payload, settings.search_cache_ttl)

    groups = payload["groups"]
    if platforms:
        wanted = {p.lower() for p in platforms}
        for g in groups:
            g["offers"] = [o for o in g["offers"] if o["platform"] in wanted]
        groups = [g for g in groups if g["offers"]]
    await _attach_offers(groups)
    # Real (live) results before sample data; within each, major retailers and brand stores first
    groups.sort(key=lambda g: (g.get("is_demo", False), not g.get("trusted", True)))
    # Budgets apply to the listed price (card offers aren't available to everyone)
    if budget_min is not None:
        groups = [g for g in groups if min(o["price"] for o in g["offers"]) >= budget_min]
    if budget_max is not None:
        groups = [g for g in groups if min(o["price"] for o in g["offers"]) <= budget_max]

    return {**payload, "groups": pick_results(groups, max_results), "total_found": len(groups)}


def pick_results(groups: list[dict], max_results: int) -> list[dict]:
    """Real results first, but keep a few sample-data products when both kinds exist, so a busy
    live search doesn't push the demo dataset out entirely."""
    live = [g for g in groups if not g.get("is_demo")]
    demo = [g for g in groups if g.get("is_demo")]
    if not live or not demo:
        return groups[:max_results]
    k = min(len(demo), max(2, max_results // 3))
    return live[: max_results - k] + demo[:k]


def filter_groups(
    groups: list[dict],
    brand: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    keywords: list[str] | None = None,
    min_rating: float | None = None,
    platforms: list[str] | None = None,
    sort_by: str = "price",
) -> list[dict]:
    """Refine previous results without searching again."""
    out = []
    for g in groups:
        g = {**g, "offers": list(g["offers"])}
        if platforms:
            wanted = {p.lower() for p in platforms}
            g["offers"] = [o for o in g["offers"] if o["platform"] in wanted]
            if not g["offers"]:
                continue
        price = min(o["price"] for o in g["offers"])
        text = f"{g['name']} {g.get('brand') or ''}".lower()
        if brand and brand.lower() not in text:
            continue
        if keywords and not all(k.lower() in text for k in keywords):
            continue
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        if min_rating is not None and (g.get("rating") or 0) < min_rating:
            continue
        g["best_effective_price"] = min(o.get("effective_price", o["price"]) for o in g["offers"])
        out.append(g)
    untrusted = lambda g: not g.get("trusted", True)  # noqa: E731
    if sort_by == "rating":
        out.sort(key=lambda g: (untrusted(g), -(g.get("rating") or 0)))
    elif sort_by == "savings":
        out.sort(key=lambda g: (untrusted(g), -(g.get("max_saving") or 0)))
    else:
        out.sort(key=lambda g: (untrusted(g), g["best_effective_price"]))
    return out


def summarize_groups(groups: list[dict], limit: int = 8) -> str:
    """Compact text for the LLM (the UI gets the full structured data)."""
    if not groups:
        return "No products found."
    lines = []
    for i, g in enumerate(groups[:limit], 1):
        stores = ", ".join(
            f"{platform_label(o['platform'])} ₹{o['price']:,.0f}"
            + (f" (₹{o['effective_price']:,.0f} with {o['best_deal']['title']})" if o.get("best_deal") else "")
            for o in g["offers"]
        )
        rating = f", rating {g['rating']}" if g.get("rating") else ""
        demo = " [demo data]" if g.get("is_demo") else ""
        unverified = "" if g.get("trusted", True) else " [unverified sellers only]"
        lines.append(f"{i}. [product_id={g.get('product_id')}] {g['name']}{rating}{demo}{unverified} — {stores}")
    return "\n".join(lines)
