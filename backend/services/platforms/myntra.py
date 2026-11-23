"""Myntra (fashion only) via its embedded page JSON."""

from core.config import settings
from scrapers import myntra_scraper
from services.platforms.base import Offer, PlatformAdapter

FASHION_CATEGORIES = {"fashion", "footwear", "clothing", "beauty", "accessories", "watches"}


class MyntraAdapter(PlatformAdapter):
    slug = "myntra"
    label = "Myntra"

    def is_enabled(self) -> bool:
        return settings.enable_scrapers

    def mode(self) -> str:
        return "scraper (fashion only)"

    def handles(self, category: str | None) -> bool:
        return category is None or category.lower() in FASHION_CATEGORIES

    async def search(self, query: str, category: str | None = None, max_results: int = 10) -> list[Offer]:
        if not self.handles(category):
            return []
        return await myntra_scraper.search(query, max_results)
