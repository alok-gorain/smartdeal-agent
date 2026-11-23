"""Fallback scraper for flipkart.com search results.

Flipkart's CSS class names are obfuscated and change often, so this parser
relies on stable signals instead: product links contain "/p/itm", prices start
with "₹", ratings look like "4.3". Expect it to need maintenance.
"""

import logging
import re
from urllib.parse import quote_plus, urljoin

from selectolax.lexbor import LexborHTMLParser, LexborNode

from scrapers.http import fetch_html, parse_int, parse_price
from services.platforms.base import Offer

logger = logging.getLogger(__name__)

BASE = "https://www.flipkart.com"
_RATING_RE = re.compile(r"^[1-5]\.\d$")
_REVIEWS_RE = re.compile(r"([\d,]+)\s*(?:Ratings|ratings|\))")


def _card_for(anchor: LexborNode) -> LexborNode:
    """Climb up from a product link to the element holding the whole product card."""
    node = anchor
    for _ in range(6):
        if node.parent is None:
            break
        node = node.parent
        if "₹" in (node.text() or ""):
            # Keep climbing one more level if the price is not yet next to a title.
            if len(node.css('a[href*="/p/itm"]')) >= 1 and len(node.text()) > 40:
                return node
    return node


def parse_search_html(html: str, max_results: int = 10) -> list[Offer]:
    tree = LexborHTMLParser(html)
    seen: set[str] = set()
    offers: list[Offer] = []
    for anchor in tree.css('a[href*="/p/itm"]'):
        href = anchor.attributes.get("href") or ""
        path = href.split("?")[0]
        if not path or path in seen:
            continue
        card = _card_for(anchor)
        tokens = [t.strip() for t in card.text(separator="|").split("|") if t.strip()]
        prices = [parse_price(t) for t in tokens if t.startswith("₹")]
        prices = [p for p in prices if p]
        if not prices:
            continue
        img = card.css_first("img")
        title = (
            anchor.attributes.get("title")
            or (img.attributes.get("alt") if img else None)
            or next((t for t in tokens if len(t) > 15 and not t.startswith("₹")), None)
        )
        if not title:
            continue
        seen.add(path)
        price = prices[0]
        mrp = next((p for p in prices[1:] if p > price), None)
        rating = next((float(t) for t in tokens if _RATING_RE.match(t)), None)
        reviews = None
        for t in tokens:
            m = _REVIEWS_RE.search(t)
            if m:
                reviews = parse_int(m.group(1))
                break
        pid = None
        m = re.search(r"[?&]pid=([A-Z0-9]+)", href)
        if m:
            pid = m.group(1)
        offers.append(
            Offer(
                platform="flipkart",
                name=title,
                price=price,
                mrp=mrp,
                rating=rating,
                review_count=reviews,
                image_url=img.attributes.get("src") if img else None,
                url=urljoin(BASE, path + (f"?pid={pid}" if pid else "")),
                platform_product_id=pid,
                via="flipkart_scraper",
            )
        )
        if len(offers) >= max_results:
            break
    return offers


async def search(query: str, max_results: int = 10) -> list[Offer]:
    html = await fetch_html(f"{BASE}/search?q={quote_plus(query)}")
    offers = parse_search_html(html, max_results)
    logger.info("flipkart scraper: %d results for %r", len(offers), query)
    return offers
