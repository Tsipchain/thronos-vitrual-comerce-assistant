#!/usr/bin/env python3
"""
Seed script: Provision Eukolakis tenant in the Thronos Commerce Assistant database.

Idempotent — safe to re-run at any time. Checks for existing records before inserting.

Usage:
    cd backend
    python -m scripts.seed_eukolakis

    # With explicit DB URL:
    DATABASE_URL=postgresql+asyncpg://user:pass@host/db python -m scripts.seed_eukolakis

After running, note the shop.id printed at the end.
Set EUKOLAKIS_ASSISTANT_SHOP_ID=<that id> in commerce .env for the JWT bridge.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models.base import Base
from models.shop import Shop
from models.products import Product
from models.orders import Order, OrderItem

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EUKOLAKIS_TENANT_ID = "eukolakis"

EUKOLAKIS_SHOP = {
    "name": "Eukolakis DIY Store",
    "owner_id": "eukolakis-owner-001",
    "owner_email": "admin@eukolaki.gr",
    "domain": "www.eukolaki.gr",
    "commerce_tenant_id": EUKOLAKIS_TENANT_ID,
    "description": "DIY kits και ανταλλακτικά για ρολά, συρόμενα και επισκευές — όλα σε ένα μέρος.",
    "return_policy_text": (
        "Δεχόμαστε επιστροφές εντός 14 ημερών από την παραλαβή. "
        "Το προϊόν πρέπει να είναι αχρησιμοποίητο και στην αρχική συσκευασία. "
        "Για επιστροφές επικοινωνήστε μαζί μας στο info@eukolaki.gr."
    ),
    "return_window_days": 14,
    "shipping_methods": [
        {"id": "standard_cod", "label": "Courier με αντικαταβολή", "base": 4, "codFee": 2},
        {"id": "standard_card", "label": "Courier με κάρτα", "base": 3, "codFee": 0},
    ],
    "sla_hours": 48,
}

EUKOLAKIS_PRODUCTS = [
    {
        "sku": "EUK-ROLL-KIT-001",
        "name": "Eukolaki DIY Roll Kit",
        "description": "Kit για κατασκευή ρολού με επιλογές χρώματος, οδηγού και κουτιού. Περιλαμβάνει βήμα-βήμα οδηγίες.",
        "category": "diy-rolla",
        "price": 12.0,
        "stock_quantity": 49,
        "low_stock_threshold": 10,
        "images": ["/tenants/eukolakis/media/kits/roll-main.jpg"],
        "tags": ["kit", "rolla", "diy"],
    },
    {
        "sku": "EUK-SLIDE-KIT-001",
        "name": "Eukolaki DIY Slide Door Kit",
        "description": "Kit συρόμενης πόρτας με οδηγούς, χρώμα και προαιρετικά αξεσουάρ.",
        "category": "diy-sliding",
        "price": 18.0,
        "stock_quantity": 30,
        "low_stock_threshold": 5,
        "images": ["/tenants/eukolakis/media/kits/slide-main.jpg"],
        "tags": ["kit", "sliding", "diy"],
    },
    {
        "sku": "EUK-PART-GUIDE-BASIC",
        "name": "Guide Basic 40mm",
        "description": "Ανταλλακτικός οδηγός 40mm για ρολά.",
        "category": "spare-parts",
        "price": 2.0,
        "stock_quantity": 100,
        "low_stock_threshold": 20,
        "images": ["/tenants/eukolakis/media/parts/guide-basic.jpg"],
        "tags": ["spare", "guide", "40mm"],
    },
]


def _get_db_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        logger.warning("DATABASE_URL not set — using local SQLite: ./eukolakis_seed.db")
        return "sqlite+aiosqlite:///eukolakis_seed.db"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def seed_shop(db: AsyncSession) -> Shop:
    result = await db.execute(
        select(Shop).where(Shop.commerce_tenant_id == EUKOLAKIS_TENANT_ID)
    )
    shop = result.scalar_one_or_none()
    if shop:
        logger.info(f"✓ Shop already exists: id={shop.id}  name={shop.name}")
        return shop

    shop = Shop(**EUKOLAKIS_SHOP)
    db.add(shop)
    await db.flush()
    logger.info(f"+ Created shop: id={shop.id}  name={shop.name}")
    return shop


async def seed_products(db: AsyncSession, shop: Shop) -> list:
    products = []
    for p_data in EUKOLAKIS_PRODUCTS:
        result = await db.execute(
            select(Product).where(
                Product.shop_id == shop.id,
                Product.sku == p_data["sku"],
            )
        )
        product = result.scalar_one_or_none()
        if product:
            logger.info(f"✓ Product already exists: {product.sku}")
            products.append(product)
            continue
        product = Product(shop_id=shop.id, **p_data)
        db.add(product)
        await db.flush()
        products.append(product)
        logger.info(f"+ Created product: {p_data['sku']} — {p_data['name']}")
    return products


async def seed_sample_orders(db: AsyncSession, shop: Shop, products: list) -> None:
    """Create 2 realistic sample orders if none exist for this shop yet."""
    result = await db.execute(
        select(Order).where(Order.shop_id == shop.id).limit(1)
    )
    if result.scalar_one_or_none():
        logger.info("✓ Orders already exist — skipping sample order creation")
        return

    now = datetime.utcnow()
    product_by_sku = {p.sku: p for p in products}

    orders_spec = [
        {
            "order_number": "ORD-EUK-0001",
            "customer_id": "cust-euk-001",
            "status": "delivered",
            "total_amount": 16.0,
            "shipping_cost": 3.0,
            "currency": "EUR",
            "shipping_method": "standard_card",
            "payment_method": "CARD",
            "payment_status": "paid",
            "shipping_address": {
                "name": "Γιάννης Παπαδόπουλος",
                "street": "Αιόλου 5",
                "city": "Αθήνα",
                "postal": "10551",
                "country": "GR",
            },
            "confirmed_at": now - timedelta(days=5),
            "shipped_at": now - timedelta(days=4),
            "delivered_at": now - timedelta(days=2),
            "_items": [("EUK-ROLL-KIT-001", 1, 12.0)],
        },
        {
            "order_number": "ORD-EUK-0002",
            "customer_id": "cust-euk-002",
            "status": "processing",
            "total_amount": 24.0,
            "shipping_cost": 4.0,
            "currency": "EUR",
            "shipping_method": "standard_cod",
            "payment_method": "COD",
            "payment_status": "pending",
            "shipping_address": {
                "name": "Μαρία Σταθοπούλου",
                "street": "Ερμού 22",
                "city": "Θεσσαλονίκη",
                "postal": "54623",
                "country": "GR",
            },
            "confirmed_at": now - timedelta(days=1),
            "shipped_at": None,
            "delivered_at": None,
            "_items": [
                ("EUK-SLIDE-KIT-001", 1, 18.0),
                ("EUK-PART-GUIDE-BASIC", 2, 2.0),
            ],
        },
    ]

    for spec in orders_spec:
        items_raw = spec.pop("_items")
        order = Order(shop_id=shop.id, **spec)
        db.add(order)
        await db.flush()
        for sku, qty, unit_price in items_raw:
            product = product_by_sku.get(sku)
            item = OrderItem(
                order_id=order.id,
                product_id=product.id if product else "unknown",
                sku=sku,
                product_name=product.name if product else sku,
                quantity=qty,
                unit_price=unit_price,
                total_price=unit_price * qty,
            )
            db.add(item)
        logger.info(f"+ Created order: {spec['order_number']} ({spec['status']})")


async def main() -> None:
    logger.info("=" * 50)
    logger.info("Seeding Eukolakis tenant in assistant DB")
    logger.info("=" * 50)

    db_url = _get_db_url()
    is_sqlite = db_url.startswith("sqlite")
    engine = create_async_engine(
        db_url,
        echo=False,
        **({
            "connect_args": {"check_same_thread": False}
        } if is_sqlite else {}),
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("DB schema verified / created")

    async with session_factory() as db:
        shop = await seed_shop(db)
        products = await seed_products(db, shop)
        await seed_sample_orders(db, shop, products)
        await db.commit()

    await engine.dispose()

    logger.info("=" * 50)
    logger.info("Seed complete!")
    logger.info(f"  Eukolakis shop.id = {shop.id}")
    logger.info("  Set this in commerce .env:")
    logger.info(f"  EUKOLAKIS_ASSISTANT_SHOP_ID={shop.id}")
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
