"""Fallback scraper for amazon.in search results.

Amazon actively blocks scrapers (CAPTCHA). Use it for local development only;
in production prefer the PA-API or the Google Shopping aggregator.
"""

import logging
import re
from urllib.parse import quote_plus, urljoin

from selectolax.lexbor import LexborHTMLParser

from scrapers.http import fetch_html, parse_int, parse_price
from services.platforms.base import Offer

logger = logging.getLogger(__name__)

BASE = "https://www.amazon.in"


def parse_search_html(html: str, max_results: int = 10) -> list[Offer]:
    tree = LexborHTMLParser(html)
    offers: list[Offer] = []
    for node in tree.css('div[data-component-type="s-search-result"]'):
        asin = node.attributes.get("data-asin")
        if not asin:
            continue
        title_node = node.css_first("h2 span") or node.css_first("h2")
        title = (title_node.text(strip=True) if title_node else "") or (
            node.css_first("h2").attributes.get("aria-label", "") if node.css_first("h2") else ""
        )
        price_node = node.css_first("span.a-price:not(.a-text-price) span.a-offscreen")
        price = parse_price(price_node.text() if price_node else None)
        if not title or not price:
            continue
        mrp_node = node.css_first("span.a-price.a-text-price span.a-offscreen")
        rating_node = node.css_first("span.a-icon-alt")
        rating = None
        if rating_node:
            m = re.search(r"(\d(?:\.\d)?)\s+out of", rating_node.text())
            rating = float(m.group(1)) if m else None
        reviews_node = node.css_first('a[href*="#customerReviews"] span') or node.css_first(
            "span.a-size-base.s-underline-text"
        )
        img = node.css_first("img.s-image")
        link = node.css_first('a.a-link-normal[href*="/dp/"]') or node.css_first("h2 a")
        href = link.attributes.get("href") if link else f"/dp/{asin}"
        offers.append(
            Offer(
                platform="amazon",
                name=title,
                price=price,
                mrp=parse_price(mrp_node.text() if mrp_node else None),
                rating=rating,
                review_count=parse_int(reviews_node.text() if reviews_node else None),
                image_url=img.attributes.get("src") if img else None,
                url=urljoin(BASE, href or f"/dp/{asin}").split("/ref=")[0],
                platform_product_id=asin,
                via="amazon_scraper",
            )
        )
        if len(offers) >= max_results:
            break
    return offers


async def search(query: str, max_results: int = 10) -> list[Offer]:
    html = await fetch_html(f"{BASE}/s?k={quote_plus(query)}")
    offers = parse_search_html(html, max_results)
    logger.info("amazon scraper: %d results for %r", len(offers), query)
    return offers
