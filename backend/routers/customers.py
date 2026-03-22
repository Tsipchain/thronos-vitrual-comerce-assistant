import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_shop_id
from dependencies.database import get_db
from models.customers import Customer
from schemas.customers import CustomerCreate, CustomerResponse, CustomerUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/customers", tags=["customers"])


@router.get("/", response_model=list[CustomerResponse])
async def list_customers(
    search: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    query = select(Customer).where(Customer.shop_id == shop_id)
    if search:
        query = query.where(
            (Customer.name.ilike(f"%{search}%")) | (Customer.email.ilike(f"%{search}%"))
        )
    query = query.order_by(Customer.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", response_model=CustomerResponse, status_code=201)
async def create_customer(
    data: CustomerCreate,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(Customer).where(and_(Customer.shop_id == shop_id, Customer.email == data.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Customer with this email already exists")
    customer = Customer(shop_id=shop_id, **data.model_dump())
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: str,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Customer).where(and_(Customer.id == customer_id, Customer.shop_id == shop_id))
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    data: CustomerUpdate,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Customer).where(and_(Customer.id == customer_id, Customer.shop_id == shop_id))
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    await db.commit()
    await db.refresh(customer)
    return customer
