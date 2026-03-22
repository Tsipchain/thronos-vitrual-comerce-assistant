import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_shop_id
from dependencies.database import get_db
from services.analytics import AnalyticsService
from services.inventory import InventoryService
from services.returns import ReturnsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/revenue")
async def revenue_summary(
    days: int = Query(30, ge=1, le=365),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = AnalyticsService(db)
    return await svc.revenue_summary(shop_id, days)


@router.get("/low-stock")
async def low_stock_products(
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = InventoryService(db)
    return await svc.get_low_stock_products(shop_id)


@router.get("/dead-stock")
async def dead_stock_products(
    days: int = Query(90, ge=30, le=365),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = InventoryService(db)
    return await svc.get_dead_stock_products(shop_id, days)


@router.get("/restock-suggestions")
async def restock_suggestions(
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = InventoryService(db)
    return await svc.suggest_restock(shop_id)


@router.get("/returns-summary")
async def returns_summary(
    days: int = Query(7, ge=1, le=90),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = ReturnsService(db)
    return await svc.get_returns_summary(shop_id, days)


@router.get("/suspicious-patterns")
async def suspicious_patterns(
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = ReturnsService(db)
    return await svc.detect_suspicious_patterns(shop_id)


@router.get("/top-cancelled-skus")
async def top_cancelled_skus(
    limit: int = Query(10, ge=1, le=50),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = AnalyticsService(db)
    return await svc.top_cancelled_skus(shop_id, limit)


@router.get("/top-selling")
async def top_selling_products(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=1, le=50),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = AnalyticsService(db)
    return await svc.top_selling_products(shop_id, days, limit)


@router.get("/orders-by-status")
async def orders_by_status(
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = AnalyticsService(db)
    return await svc.orders_by_status(shop_id)


@router.get("/customer-risk")
async def customer_risk_report(
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = AnalyticsService(db)
    return await svc.customer_risk_report(shop_id)
