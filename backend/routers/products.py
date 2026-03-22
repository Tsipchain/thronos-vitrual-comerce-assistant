import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_shop_id
from dependencies.database import get_db
from models.products import Product
from schemas.products import ProductCreate, ProductResponse, ProductUpdate, StockUpdateRequest
from services.inventory import InventoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("/", response_model=list[ProductResponse])
async def list_products(
    category: str | None = None,
    search: str | None = None,
    low_stock_only: bool = False,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    query = select(Product).where(Product.shop_id == shop_id)
    if category:
        query = query.where(Product.category == category)
    if search:
        query = query.where(Product.name.ilike(f"%{search}%"))
    if low_stock_only:
        query = query.where(Product.stock_quantity <= Product.low_stock_threshold)
    query = query.order_by(Product.name).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    products = result.scalars().all()
    return [_product_to_response(p) for p in products]


@router.post("/", response_model=ProductResponse, status_code=201)
async def create_product(
    data: ProductCreate,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    product = Product(shop_id=shop_id, **data.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return _product_to_response(product)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).where(and_(Product.id == product_id, Product.shop_id == shop_id))
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _product_to_response(product)


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    data: ProductUpdate,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).where(and_(Product.id == product_id, Product.shop_id == shop_id))
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await db.commit()
    await db.refresh(product)
    return _product_to_response(product)


@router.patch("/{product_id}/stock", response_model=dict)
async def update_stock(
    product_id: str,
    data: StockUpdateRequest,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = InventoryService(db)
    return await svc.update_stock(product_id, data.quantity, shop_id)


@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).where(and_(Product.id == product_id, Product.shop_id == shop_id))
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.is_active = False
    await db.commit()
    return {"detail": "Product deactivated"}


def _product_to_response(p: Product) -> ProductResponse:
    return ProductResponse(
        id=p.id, shop_id=p.shop_id, sku=p.sku, name=p.name, description=p.description,
        category=p.category, tags=p.tags or [], price=p.price, cost_price=p.cost_price,
        currency=p.currency, stock_quantity=p.stock_quantity,
        low_stock_threshold=p.low_stock_threshold,
        available_stock=p.available_stock, is_low_stock=p.is_low_stock,
        is_dead_stock=p.is_dead_stock, total_sold=p.total_sold,
        total_returned=p.total_returned, last_sold_at=p.last_sold_at,
        is_active=p.is_active, created_at=p.created_at,
    )
