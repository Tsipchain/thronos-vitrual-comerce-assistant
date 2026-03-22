import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_shop_id
from dependencies.database import get_db
from models.vouchers import Voucher
from schemas.vouchers import VoucherCreate, VoucherResponse, VoucherValidateRequest, VoucherValidateResponse
from services.vouchers import VoucherService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/vouchers", tags=["vouchers"])


@router.get("/", response_model=list[VoucherResponse])
async def list_vouchers(
    active_only: bool = False,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    query = select(Voucher).where(Voucher.shop_id == shop_id)
    if active_only:
        query = query.where(Voucher.is_active == True)
    query = query.order_by(Voucher.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", response_model=VoucherResponse, status_code=201)
async def create_voucher(
    data: VoucherCreate,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = VoucherService(db)
    return await svc.generate_voucher(
        shop_id=shop_id, voucher_type=data.type, value=data.value,
        customer_id=data.customer_id, created_by="manual",
        currency=data.currency, min_order_amount=data.min_order_amount,
        max_discount_amount=data.max_discount_amount,
        applicable_categories=data.applicable_categories,
        applicable_products=data.applicable_products,
        max_uses=data.max_uses, max_uses_per_customer=data.max_uses_per_customer,
        valid_from=data.valid_from, valid_until=data.valid_until,
    )


@router.post("/validate", response_model=VoucherValidateResponse)
async def validate_voucher(
    data: VoucherValidateRequest,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = VoucherService(db)
    result = await svc.validate_voucher(data.code, data.order_amount, data.customer_id)
    return VoucherValidateResponse(**result)


@router.get("/stats")
async def voucher_stats(
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = VoucherService(db)
    return await svc.get_voucher_stats(shop_id)


@router.patch("/{voucher_id}/deactivate")
async def deactivate_voucher(
    voucher_id: str,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Voucher).where(and_(Voucher.id == voucher_id, Voucher.shop_id == shop_id))
    )
    voucher = result.scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    voucher.is_active = False
    await db.commit()
    return {"detail": "Voucher deactivated"}
