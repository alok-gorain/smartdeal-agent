"""All store adapters. Adding a store = write an adapter and list it here."""

from core.config import settings
from services.platforms.amazon import AmazonAdapter
from services.platforms.base import PlatformAdapter
from services.platforms.catalog import CatalogAdapter
from services.platforms.flipkart import FlipkartAdapter
from services.platforms.google_shopping import GoogleShoppingAdapter
from services.platforms.myntra import MyntraAdapter

ALL_ADAPTERS: list[PlatformAdapter] = [
    CatalogAdapter(),
    GoogleShoppingAdapter(),
    AmazonAdapter(),
    FlipkartAdapter(),
    MyntraAdapter(),
]


def active_adapters() -> list[PlatformAdapter]:
    allowed = settings.enabled_platform_list
    return [a for a in ALL_ADAPTERS if a.is_enabled() and (not allowed or a.slug in allowed)]


def get_adapter(slug: str) -> PlatformAdapter | None:
    return next((a for a in ALL_ADAPTERS if a.slug == slug), None)


def adapter_status() -> list[dict]:
    active = {a.slug for a in active_adapters()}
    return [
        {"slug": a.slug, "label": a.label, "kind": a.kind, "enabled": a.slug in active, "mode": a.mode()}
        for a in ALL_ADAPTERS
    ]
