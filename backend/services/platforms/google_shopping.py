"""Google Shopping India through SerpApi.

One call returns offers from most Indian stores (Croma, Reliance Digital,
Vijay Sales, Tata CLiQ, Nykaa, AJIO, JioMart, brand stores, ...), which is how
SmartDeal covers "all other sites" without one fragile scraper per store.
"""

import logging
import re

import httpx

from core.config import settings
from services.platforms.base import AdapterError, Offer, PlatformAdapter, platform_from_source
from services.product_matcher import ACCESSORY_RE

logger = logging.getLogger(__name__)

API_URL = "https://serpapi.com/search.json"
_USED_RE = re.compile(r"\b(refurbished|renewed|pre-owned|preowned|used|open box|unboxed)\b", re.I)
# Indian stores that mainly sell pre-owned/refurbished devices
_USED_SELLERS = ("cashify", "gameloot", "ovantica", "controlz", "budli", "yaantra", "zoplar", "togofogo",
                 "2gud", "refit", "mobilegoo", "grest", "xtracover")


def parse_shopping_results(data: dict, max_results: int, query: str = "") -> list[Offer]:
    # Phone searches also return covers and chargers; keep them only if the user asked for one
    want_accessories = bool(ACCESSORY_RE.search(query))
    offers: list[Offer] = []
    for r in data.get("shopping_results", []):
        price = r.get("extracted_price")
        title = r.get("title")
        source = r.get("source") or ""
        if not price or not title or not source:
            continue
        # Used/refurbished listings would distort a new-product price comparison
        if r.get("second_hand_condition") or _USED_RE.search(title):
            continue
        if any(s in source.lower().replace(" ", "") for s in _USED_SELLERS):
            continue
        if not want_accessories and ACCESSORY_RE.search(title):
            continue
        offers.append(
            Offer(
                platform=platform_from_source(source),
                name=title,
                price=float(price),
                mrp=float(r["extracted_old_price"]) if r.get("extracted_old_price") else None,
                rating=float(r["rating"]) if r.get("rating") else None,
                review_count=int(r["reviews"]) if r.get("reviews") else None,
                image_url=r.get("thumbnail"),
                url=r.get("link") or r.get("product_link"),
                platform_product_id=str(r.get("product_id")) if r.get("product_id") else None,
                seller=source,
                delivery_info=r.get("delivery"),
                via="google_shopping",
                google_page_token=r.get("immersive_product_page_token"),
            )
        )
        if len(offers) >= max_results:
            break
    return offers


class GoogleShoppingAdapter(PlatformAdapter):
    slug = "google_shopping"
    label = "Google Shopping (all stores)"
    kind = "aggregator"

    def is_enabled(self) -> bool:
        return bool(settings.serpapi_key)

    def mode(self) -> str:
        return "aggregator API (SerpApi)"

    async def search(self, query: str, category: str | None = None, max_results: int = 10) -> list[Offer]:
        params = {
            "engine": "google_shopping",
            "q": query,
            "gl": "in",
            "hl": "en",
            "location": "India",
            "num": 40,
            "api_key": settings.serpapi_key,
        }
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.get(API_URL, params=params)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("error") or ""
            except ValueError:
                detail = ""
            raise AdapterError(f"SerpApi returned HTTP {resp.status_code}" + (f": {detail}" if detail else ""))
        data = resp.json()
        if data.get("error"):
            raise AdapterError(f"SerpApi: {data['error']}")
        # Aggregator results span many stores, so allow more of them.
        return parse_shopping_results(data, max_results * 3, query)
