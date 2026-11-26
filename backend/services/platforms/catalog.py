"""Search products already in our database.

Returns products tracked from earlier live searches, plus the seeded demo
listings while demo mode is on. With DEMO_CATALOG=auto (the default), demo data
is used only when no live price source is configured, so sample prices never
appear next to real ones.
"""

from rapidfuzz import fuzz
from sqlalchemy import or_, select

from core.config import settings
from core.database import session_scope
from models import Product
from services.platforms.base import Offer, PlatformAdapter
from services.product_matcher import normalize


def _token_matches(token: str, hay_tokens: set[str]) -> bool:
    if token in hay_tokens:
        return True
    if any(ch.isdigit() for ch in token):
        return False  # model numbers must match exactly ("pixel 9" is not "pixel 8")
    if len(token) >= 4:
        # tolerate typos and plurals: "earbud" ~ "earbuds", "samsng" ~ "samsung"
        return any(fuzz.ratio(token, h) >= 80 for h in hay_tokens)
    return False


def query_coverage(q_tokens: list[str], hay_tokens: set[str]) -> float:
    if not q_tokens:
        return 0.0
    return sum(_token_matches(t, hay_tokens) for t in q_tokens) / len(q_tokens)


def _haystack(p: Product) -> str:
    tags = " ".join(p.specifications.get("tags", [])) if p.specifications else ""
    return normalize(f"{p.name} {p.brand or ''} {p.category or ''} {tags}")


def demo_data_enabled() -> bool:
    """DEMO_CATALOG: true = always, false = never, auto = only when no live source is active."""
    mode = str(settings.demo_catalog).strip().lower()
    if mode in ("true", "1", "yes", "on"):
        return True
    if mode in ("false", "0", "no", "off"):
        return False
    from services.platforms.registry import active_adapters

    return not any(a.kind != "catalog" for a in active_adapters())


class CatalogAdapter(PlatformAdapter):
    slug = "catalog"
    label = "SmartDeal catalog"
    kind = "catalog"

    def is_enabled(self) -> bool:
        return True  # tracked live products are always searchable

    def mode(self) -> str:
        if demo_data_enabled():
            return "local database (sample catalog + tracked products)"
        return "local database (tracked live products)"

    @staticmethod
    def _prefilter(q: str):
        """SQL prefilter: products whose search text contains the start of any query word.

        Using the first 5 letters keeps plurals and typo endings ("earbud"/"earbuds"); the exact
        scoring happens in Python. The category isn't a hard filter: the LLM's category guess
        ("electronics" for earbuds) shouldn't hide matching products.
        """
        stems = {t[:5] for t in q.split() if len(t) >= 3 or any(ch.isdigit() for ch in t)}
        stmt = select(Product)
        if stems:
            stmt = stmt.where(or_(Product.search_text.is_(None), *(Product.search_text.ilike(f"%{s}%") for s in stems)))
        return stmt.limit(1500)

    async def search(self, query: str, category: str | None = None, max_results: int = 10) -> list[Offer]:
        q = normalize(query)
        if not q:
            return []
        include_demo = demo_data_enabled()
        async with session_scope() as session:
            products = (await session.scalars(self._prefilter(q))).all()

            q_tokens = q.split()
            scored = []
            for p in products:
                listings = [l for l in p.listings if include_demo or l.source != "demo"]
                if not listings:
                    continue
                hay = _haystack(p)
                coverage = query_coverage(q_tokens, set(hay.split()))
                needed = 1.0 if len(q_tokens) < 4 else 0.75
                if coverage >= needed:
                    scored.append((coverage, fuzz.token_set_ratio(q, hay), p, listings))
            scored.sort(key=lambda x: (-x[0], -x[1], x[2].name))

            offers: list[Offer] = []
            for _, _, p, listings in scored[:max_results]:
                for listing in listings:
                    offers.append(
                        Offer(
                            platform=listing.platform,
                            # the store's own title, so a listing attached to the wrong product can be caught
                            name=listing.title or p.name,
                            price=listing.current_price,
                            mrp=listing.mrp,
                            rating=listing.rating,
                            review_count=listing.review_count,
                            image_url=p.image_url,
                            url=listing.affiliate_url or listing.product_url,
                            platform_product_id=listing.platform_product_id,
                            brand=p.brand,
                            category=p.category,
                            in_stock=listing.in_stock,
                            seller=listing.seller_name,
                            delivery_info=listing.delivery_info,
                            source=listing.source,
                            via="catalog",
                            product_id=p.id,
                        )
                    )
            return offers
