from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from services import catalog_service, search_service
from services.platforms.registry import adapter_status

router = APIRouter(prefix="/api", tags=["products"])


@router.get("/products/search")
async def search(
    q: str = Query(..., min_length=2, max_length=200),
    category: str | None = None,
    platforms: str | None = Query(None, description="Comma-separated store slugs"),
    budget_min: float | None = Query(None, ge=0),
    budget_max: float | None = Query(None, ge=0),
    limit: int = Query(8, ge=1, le=30),
):
    platform_list = [p.strip() for p in platforms.split(",") if p.strip()] if platforms else None
    return await search_service.search_products(
        q, category=category, platforms=platform_list, budget_min=budget_min, budget_max=budget_max, max_results=limit
    )


@router.get("/products/{product_id}")
async def product_detail(product_id: int, session: AsyncSession = Depends(get_session)):
    product = await catalog_service.get_product(session, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    return catalog_service.product_to_dict(product)


@router.get("/platforms")
async def platforms():
    """Which store adapters are active and how they get data (API, scraper, aggregator)."""
    return adapter_status()
