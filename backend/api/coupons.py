from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from services import coupon_service

router = APIRouter(prefix="/api/coupons", tags=["coupons"])


@router.get("")
async def coupons(
    platform: str | None = None,
    category: str | None = None,
    bank: str | None = None,
    price: float | None = Query(None, ge=0, description="Order value, to compute each offer's saving"),
    session: AsyncSession = Depends(get_session),
):
    items = await coupon_service.active_coupons(session, platform, category, bank)
    result = [coupon_service.coupon_to_dict(c, price) for c in items]
    if price is not None:
        result.sort(key=lambda c: -c["saving"])
    return result
