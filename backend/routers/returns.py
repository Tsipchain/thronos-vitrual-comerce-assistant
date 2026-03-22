import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_shop_id
from dependencies.database import get_db
from models.returns import ReturnRequest
from schemas.returns import ReturnCreate, ReturnDecision, ReturnResponse
from services.returns import ReturnsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/returns", tags=["returns"])


@router.get("/", response_model=list[ReturnResponse])
async def list_returns(
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    query = select(ReturnRequest).where(ReturnRequest.shop_id == shop_id)
    if status:
        query = query.where(ReturnRequest.status == status)
    query = query.order_by(ReturnRequest.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", response_model=ReturnResponse, status_code=201)
async def create_return(
    data: ReturnCreate,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = ReturnsService(db)
    try:
        # Get customer_id from order
        from models.orders import Order
        order_result = await db.execute(
            select(Order).where(and_(Order.id == data.order_id, Order.shop_id == shop_id))
        )
        order = order_result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        ret = await svc.create_return_request(
            shop_id=shop_id, order_id=data.order_id, customer_id=order.customer_id,
            reason=data.reason, reason_category=data.reason_category,
            items=[i.model_dump() for i in data.items], refund_type=data.refund_type,
        )
        return ret
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{return_id}", response_model=ReturnResponse)
async def get_return(
    return_id: str,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReturnRequest).where(and_(ReturnRequest.id == return_id, ReturnRequest.shop_id == shop_id))
    )
    ret = result.scalar_one_or_none()
    if not ret:
        raise HTTPException(status_code=404, detail="Return request not found")
    return ret


@router.post("/{return_id}/decide", response_model=ReturnResponse)
async def decide_return(
    return_id: str,
    data: ReturnDecision,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = ReturnsService(db)
    try:
        if data.action == "approve":
            return await svc.approve_return(
                return_id, shop_id, data.refund_type, data.refund_amount, data.admin_notes
            )
        elif data.action == "reject":
            return await svc.reject_return(return_id, shop_id, data.rejected_reason or "Rejected")
        else:
            raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
