"""Amazon India: official PA-API 5.0 when keys are set, scraper otherwise."""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

from core.config import settings
from scrapers import amazon_scraper
from services.platforms.base import AdapterError, Offer, PlatformAdapter

logger = logging.getLogger(__name__)

HOST = "webservices.amazon.in"
REGION = "eu-west-1"
SERVICE = "ProductAdvertisingAPI"
PATH = "/paapi5/searchitems"
TARGET = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"
RESOURCES = [
    "ItemInfo.Title",
    "ItemInfo.ByLineInfo",
    "Images.Primary.Medium",
    "Offers.Listings.Price",
    "Offers.Listings.SavingBasis",
    "Offers.Listings.Availability.Type",
    "Offers.Listings.MerchantInfo",
    "Offers.Listings.DeliveryInfo.IsPrimeEligible",
    "CustomerReviews.Count",
    "CustomerReviews.StarRating",
]
SEARCH_INDEX = {
    "mobiles": "Electronics",
    "electronics": "Electronics",
    "laptops": "Computers",
    "audio": "Electronics",
    "tv": "Electronics",
    "fashion": "Fashion",
    "footwear": "Fashion",
    "appliances": "HomeAndKitchen",
    "beauty": "Beauty",
}


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sign_request(payload: str, access_key: str, secret_key: str, now: datetime | None = None) -> dict[str, str]:
    """Build AWS Signature V4 headers for a PA-API request."""
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    headers = {
        "content-encoding": "amz-1.0",
        "content-type": "application/json; charset=utf-8",
        "host": HOST,
        "x-amz-date": amz_date,
        "x-amz-target": TARGET,
    }
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    canonical_request = "\n".join(
        ["POST", PATH, "", canonical_headers, signed_headers, hashlib.sha256(payload.encode()).hexdigest()]
    )
    scope = f"{date_stamp}/{REGION}/{SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )
    k_signing = _sign(_sign(_sign(_sign(f"AWS4{secret_key}".encode(), date_stamp), REGION), SERVICE), "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return headers


def parse_paapi_items(data: dict) -> list[Offer]:
    offers: list[Offer] = []
    for item in (data.get("SearchResult") or {}).get("Items", []):
        info = item.get("ItemInfo") or {}
        title = ((info.get("Title") or {}).get("DisplayValue")) or ""
        listings = ((item.get("Offers") or {}).get("Listings")) or []
        if not title or not listings:
            continue
        listing = listings[0]
        price = ((listing.get("Price") or {}).get("Amount"))
        if not price:
            continue
        reviews = item.get("CustomerReviews") or {}
        prime = ((listing.get("DeliveryInfo") or {}).get("IsPrimeEligible"))
        offers.append(
            Offer(
                platform="amazon",
                name=title,
                price=float(price),
                mrp=((listing.get("SavingBasis") or {}).get("Amount")),
                rating=((reviews.get("StarRating") or {}).get("Value")),
                review_count=reviews.get("Count"),
                image_url=(((item.get("Images") or {}).get("Primary") or {}).get("Medium") or {}).get("URL"),
                url=item.get("DetailPageURL"),
                platform_product_id=item.get("ASIN"),
                brand=(((info.get("ByLineInfo") or {}).get("Brand") or {}).get("DisplayValue")),
                in_stock=((listing.get("Availability") or {}).get("Type")) != "OutOfStock",
                seller=((listing.get("MerchantInfo") or {}).get("Name")),
                delivery_info="Prime delivery" if prime else None,
                via="amazon_paapi",
            )
        )
    return offers


class AmazonAdapter(PlatformAdapter):
    slug = "amazon"
    label = "Amazon"

    def _has_api(self) -> bool:
        return bool(settings.amazon_access_key and settings.amazon_secret_key and settings.amazon_partner_tag)

    def is_enabled(self) -> bool:
        return self._has_api() or settings.enable_scrapers

    def mode(self) -> str:
        return "official API (PA-API 5.0)" if self._has_api() else "scraper"

    async def _search_api(self, query: str, category: str | None, max_results: int) -> list[Offer]:
        body = {
            "Keywords": query,
            "PartnerTag": settings.amazon_partner_tag,
            "PartnerType": "Associates",
            "Marketplace": "www.amazon.in",
            "ItemCount": max(1, min(max_results, 10)),
            "SearchIndex": SEARCH_INDEX.get((category or "").lower(), "All"),
            "Resources": RESOURCES,
        }
        payload = json.dumps(body)
        headers = sign_request(payload, settings.amazon_access_key, settings.amazon_secret_key)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"https://{HOST}{PATH}", content=payload, headers=headers)
        if resp.status_code != 200:
            raise AdapterError(f"Amazon PA-API returned HTTP {resp.status_code}: {resp.text[:200]}")
        return parse_paapi_items(resp.json())

    async def search(self, query: str, category: str | None = None, max_results: int = 10) -> list[Offer]:
        if self._has_api():
            try:
                return await self._search_api(query, category, max_results)
            except (AdapterError, httpx.HTTPError) as exc:
                logger.warning("Amazon PA-API failed (%s); trying scraper", exc)
                if not settings.enable_scrapers:
                    raise AdapterError(str(exc)) from exc
        return await amazon_scraper.search(query, max_results)
