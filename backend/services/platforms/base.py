"""Common types for every store adapter."""

import re
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field, computed_field

# Known Indian stores: slug -> display label, keywords matched (as whole words) against an
# aggregator's store name, and whether the store is "trusted": a major retailer or an official
# brand store. Open marketplaces (Meesho, Snapdeal) and unknown small sellers are not, because
# clones and grey imports are common there.
PLATFORM_INFO: dict[str, dict] = {
    "amazon": {"label": "Amazon", "keywords": ["amazon"], "trusted": True},
    "flipkart": {"label": "Flipkart", "keywords": ["flipkart"], "trusted": True},
    "myntra": {"label": "Myntra", "keywords": ["myntra"], "trusted": True},
    "croma": {"label": "Croma", "keywords": ["croma"], "trusted": True},
    "reliance_digital": {"label": "Reliance Digital", "keywords": ["reliance digital", "reliancedigital"], "trusted": True},
    "vijay_sales": {"label": "Vijay Sales", "keywords": ["vijay sales", "vijaysales"], "trusted": True},
    "tata_cliq": {"label": "Tata CLiQ", "keywords": ["tata cliq", "tatacliq", "cliq"], "trusted": True},
    "ajio": {"label": "AJIO", "keywords": ["ajio"], "trusted": True},
    "nykaa": {"label": "Nykaa", "keywords": ["nykaa"], "trusted": True},
    "jiomart": {"label": "JioMart", "keywords": ["jiomart"], "trusted": True},
    "decathlon": {"label": "Decathlon", "keywords": ["decathlon"], "trusted": True},
    "firstcry": {"label": "FirstCry", "keywords": ["firstcry"], "trusted": True},
    "pepperfry": {"label": "Pepperfry", "keywords": ["pepperfry"], "trusted": True},
    # Large regional electronics chains
    "sangeetha_mobiles": {"label": "Sangeetha Mobiles", "keywords": ["sangeetha"], "trusted": True},
    "poorvika": {"label": "Poorvika", "keywords": ["poorvika"], "trusted": True},
    "bajaj_electronics": {"label": "Bajaj Electronics", "keywords": ["bajaj electronics"], "trusted": True},
    "pai_international": {"label": "Pai International", "keywords": ["pai international"], "trusted": True},
    "lot_mobiles": {"label": "Lot Mobiles", "keywords": ["lot mobiles"], "trusted": True},
    "girias": {"label": "Girias", "keywords": ["girias"], "trusted": True},
    "sathya": {"label": "Sathya", "keywords": ["sathya"], "trusted": True},
    "snapdeal": {"label": "Snapdeal", "keywords": ["snapdeal"], "trusted": False},
    "meesho": {"label": "Meesho", "keywords": ["meesho"], "trusted": False},
    # Official brand stores
    "apple": {"label": "Apple Store", "keywords": ["apple"], "trusted": True},
    "samsung": {"label": "Samsung Shop", "keywords": ["samsung"], "trusted": True},
    "oneplus": {"label": "OnePlus Store", "keywords": ["oneplus"], "trusted": True},
    "boat": {"label": "boAt", "keywords": ["boat lifestyle", "boat-lifestyle", "boat"], "trusted": True},
    "sony": {"label": "Sony Store", "keywords": ["sony centre", "shopatsc", "sony"], "trusted": True},
    "realme": {"label": "realme Store", "keywords": ["realme"], "trusted": True},
    "xiaomi": {"label": "Xiaomi Store", "keywords": ["xiaomi", "mi store", "mi.com"], "trusted": True},
    "nothing": {"label": "Nothing Store", "keywords": ["nothing"], "trusted": True},
    "noise": {"label": "Noise", "keywords": ["gonoise", "noise"], "trusted": True},
    "jbl": {"label": "JBL / HARMAN", "keywords": ["jbl", "harman"], "trusted": True},
    "lenovo": {"label": "Lenovo Store", "keywords": ["lenovo"], "trusted": True},
    "dell": {"label": "Dell Store", "keywords": ["dell"], "trusted": True},
    "hp": {"label": "HP Store", "keywords": ["hp online store", "hp store", "hp"], "trusted": True},
    "asus": {"label": "ASUS Store", "keywords": ["asus"], "trusted": True},
    "lg": {"label": "LG Store", "keywords": ["lg electronics", "lg"], "trusted": True},
    "nike": {"label": "Nike", "keywords": ["nike"], "trusted": True},
    "adidas": {"label": "adidas", "keywords": ["adidas"], "trusted": True},
    "puma": {"label": "PUMA", "keywords": ["puma"], "trusted": True},
    "mivi": {"label": "Mivi", "keywords": ["mivi"], "trusted": True},
}


def platform_label(slug: str) -> str:
    info = PLATFORM_INFO.get(slug)
    return info["label"] if info else slug.replace("_", " ").title()


def is_trusted(slug: str) -> bool:
    """Major retailer, big regional chain or official brand store."""
    return bool(PLATFORM_INFO.get(slug, {}).get("trusted", False))


def platform_from_source(source: str) -> str:
    """Map a store name from an aggregator (e.g. 'Reliance Digital') to a slug."""
    s = source.lower().strip()
    for slug, info in PLATFORM_INFO.items():
        # whole-word match, so "lg" doesn't match inside another store's name
        if any(re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", s) for k in info["keywords"]):
            return slug
    s = re.sub(r"\.(com|in|co\.in)$", "", s)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "other"


class Offer(BaseModel):
    """A single product offer from one store."""

    platform: str
    name: str
    price: float
    mrp: float | None = None
    rating: float | None = None
    review_count: int | None = None
    image_url: str | None = None
    url: str | None = None
    platform_product_id: str | None = None
    brand: str | None = None
    category: str | None = None
    in_stock: bool = True
    seller: str | None = None
    delivery_info: str | None = None
    source: str = "live"  # live | demo
    via: str | None = None  # adapter that found it, e.g. "google_shopping"
    product_id: int | None = None  # set once linked to a Product row
    # Google Shopping token for fetching price history; kept out of API responses and caches (it's long)
    google_page_token: str | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def platform_label(self) -> str:
        # Known stores get their brand name; others keep the store's own name ("Sangeetha Mobiles")
        if self.platform in PLATFORM_INFO or not self.seller:
            return platform_label(self.platform)
        return self.seller

    @computed_field  # type: ignore[prop-decorator]
    @property
    def trusted(self) -> bool:
        """Major retailer or official brand store (see PLATFORM_INFO)."""
        return is_trusted(self.platform)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def discount_percent(self) -> float | None:
        if self.mrp and self.mrp > self.price > 0:
            return round((self.mrp - self.price) / self.mrp * 100, 1)
        return None


class AdapterError(Exception):
    """Raised when a store cannot be searched (blocked, misconfigured, down)."""


class PlatformAdapter(ABC):
    slug: str = ""
    label: str = ""
    kind: str = "direct"  # direct | aggregator | catalog

    @abstractmethod
    def is_enabled(self) -> bool: ...

    @abstractmethod
    async def search(self, query: str, category: str | None = None, max_results: int = 10) -> list[Offer]: ...

    def mode(self) -> str:
        """Human-readable description of how this adapter gets data."""
        return self.kind
