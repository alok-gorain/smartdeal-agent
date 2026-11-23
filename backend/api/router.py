from fastapi import APIRouter

from api import chat, coupons, history, products

api_router = APIRouter()
api_router.include_router(products.router)
api_router.include_router(history.router)
api_router.include_router(coupons.router)
api_router.include_router(chat.router)
