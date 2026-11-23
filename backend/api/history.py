from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from services import discount_analyzer, history_backfill, prediction_service, price_history

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/{product_id}")
async def history(product_id: int, months: int = Query(12, ge=1, le=24), session: AsyncSession = Depends(get_session)):
    """Month-wise price history per store, plus sale-event markers for the chart."""
    await history_backfill.ensure_history(product_id)
    data = await price_history.get_history(session, product_id, months)
    if not data:
        raise HTTPException(404, "Product not found")
    return data


@router.get("/{product_id}/discount")
async def discount(product_id: int, platform: str | None = None, session: AsyncSession = Depends(get_session)):
    await history_backfill.ensure_history(product_id)
    data = await discount_analyzer.analyze_product(session, product_id, platform)
    if not data:
        raise HTTPException(404, "No price data for this product")
    return data


@router.get("/{product_id}/prediction")
async def prediction(product_id: int, session: AsyncSession = Depends(get_session)):
    await history_backfill.ensure_history(product_id)
    data = await prediction_service.predict(session, product_id)
    if not data:
        raise HTTPException(404, "No price data for this product")
    return data
