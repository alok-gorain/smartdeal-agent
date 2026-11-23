"""Flipkart: affiliate API when credentials are set, scraper otherwise."""

import logging

import httpx

from core.config import settings
from scrapers import flipkart_scraper
from services.platforms.base import AdapterError, Offer, PlatformAdapter

logger = logging.getLogger(__name__)

API_URL = "https://affiliate-api.flipkart.net/affiliate/1.0/search.json"


def _amount(obj: dict | None) -> float | None:
    if not obj:
        return None
    value = obj.get("amount")
    return float(value) if value else None


def parse_affiliate_products(data: dict) -> list[Offer]:
    offers: list[Offer] = []
    for entry in data.get("products", []):
        info = entry.get("productBaseInfoV1") or {}
        title = info.get("title")
        price = _amount(info.get("flipkartSpecialPrice")) or _amount(info.get("flipkartSellingPrice"))
        if not title or not price:
            continue
        images = info.get("imageUrls") or {}
        shipping = entry.get("productShippingInfoV1") or {}
        offers.append(
            Offer(
                platform="flipkart",
                name=title,
                price=price,
                mrp=_amount(info.get("maximumRetailPrice")),
                image_url=images.get("400x400") or images.get("200x200") or next(iter(images.values()), None),
                url=info.get("productUrl"),
                platform_product_id=info.get("productId"),
                brand=info.get("productBrand"),
                in_stock=bool(info.get("inStock", True)),
                seller=shipping.get("sellerName"),
                delivery_info="Flipkart Assured" if info.get("isAvailable") else None,
                via="flipkart_affiliate",
            )
        )
    return offers


class FlipkartAdapter(PlatformAdapter):
    slug = "flipkart"
    label = "Flipkart"

    def _has_api(self) -> bool:
        return bool(settings.flipkart_affiliate_id and settings.flipkart_affiliate_token)

    def is_enabled(self) -> bool:
        return self._has_api() or settings.enable_scrapers

    def mode(self) -> str:
        return "official API (affiliate)" if self._has_api() else "scraper"

    async def _search_api(self, query: str, max_results: int) -> list[Offer]:
        headers = {
            "Fk-Affiliate-Id": settings.flipkart_affiliate_id,
            "Fk-Affiliate-Token": settings.flipkart_affiliate_token,
        }
        params = {"query": query, "resultCount": max(1, min(max_results, 10))}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(API_URL, params=params, headers=headers)
        if resp.status_code != 200:
            raise AdapterError(f"Flipkart affiliate API returned HTTP {resp.status_code}")
        return parse_affiliate_products(resp.json())

    async def search(self, query: str, category: str | None = None, max_results: int = 10) -> list[Offer]:
        if self._has_api():
            try:
                return await self._search_api(query, max_results)
            except (AdapterError, httpx.HTTPError) as exc:
                logger.warning("Flipkart API failed (%s); trying scraper", exc)
                if not settings.enable_scrapers:
                    raise AdapterError(str(exc)) from exc
        return await flipkart_scraper.search(query, max_results)
