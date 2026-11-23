"""Myntra scraper.

Myntra renders with JavaScript, but the search page embeds its data as JSON in
`window.__myx = {...}`, so no headless browser is needed.
"""

import json
import logging
import re
from urllib.parse import quote, quote_plus

from scrapers.http import fetch_html
from services.platforms.base import AdapterError, Offer

logger = logging.getLogger(__name__)

BASE = "https://www.myntra.com"
_MYX_RE = re.compile(r"window\.__myx\s*=\s*(\{.*?\})\s*;?\s*</script>", re.DOTALL)


def parse_search_html(html: str, max_results: int = 10) -> list[Offer]:
    m = _MYX_RE.search(html)
    if not m:
        raise AdapterError("myntra page did not contain product data (layout changed or blocked)")
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise AdapterError("myntra product data could not be parsed") from exc

    products = (((data.get("searchData") or {}).get("results") or {}).get("products")) or []
    offers: list[Offer] = []
    for p in products[:max_results]:
        price = p.get("price") or p.get("discountedPrice")
        name = p.get("productName") or p.get("product")
        if not price or not name:
            continue
        landing = p.get("landingPageUrl") or ""
        offers.append(
            Offer(
                platform="myntra",
                name=name,
                price=float(price),
                mrp=float(p["mrp"]) if p.get("mrp") else None,
                rating=round(float(p["rating"]), 1) if p.get("rating") else None,
                review_count=int(p["ratingCount"]) if p.get("ratingCount") else None,
                image_url=p.get("searchImage"),
                url=f"{BASE}/{landing}" if landing else None,
                platform_product_id=str(p.get("productId")) if p.get("productId") else None,
                brand=p.get("brand"),
                category="fashion",
                via="myntra_scraper",
            )
        )
    return offers


async def search(query: str, max_results: int = 10) -> list[Offer]:
    slug = quote(re.sub(r"\s+", "-", query.strip().lower()))
    html = await fetch_html(f"{BASE}/{slug}?rawQuery={quote_plus(query)}")
    offers = parse_search_html(html, max_results)
    logger.info("myntra scraper: %d results for %r", len(offers), query)
    return offers
