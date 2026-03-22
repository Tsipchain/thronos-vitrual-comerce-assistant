# Thronos Commerce Assistant

AI-powered virtual assistant for e-shop & business management. Part of the **Thronos Ecosystem**.

## Overview

The Commerce Assistant is the "digital employee" for merchants. It handles customer service, inventory management, logistics, notifications, and business analytics through a natural language AI interface.

## Features

### A. Customer Service
- Answer customer questions about orders, policies, and products
- Check order status and tracking
- Explain return policies
- Create and manage return requests
- AI-powered return risk assessment
- Generate vouchers and credit notes based on configurable rules

### B. Inventory Management
- Real-time stock monitoring
- Low stock alerts with configurable thresholds
- Dead stock detection (products not sold in 90+ days)
- Smart restock suggestions based on sales velocity
- Stock value analysis

### C. Logistics & Labels
- Shipping label generation (ACS, ELTA, Speedex, DHL, UPS, FedEx)
- Return label generation
- Packing instructions with fragile item handling
- Courier API summary for batch shipments

### D. Notifications
- Email notifications (SMTP / SendGrid / SES ready)
- SMS notifications
- Push notifications
- Automated alerts for:
  - Low stock
  - New return requests
  - Voucher creation
  - Suspicious return patterns
  - Stuck orders

### E. Business Intelligence
- Revenue summaries (daily/weekly/monthly)
- Top selling products
- Most cancelled SKUs
- Customer risk scoring
- Return pattern analysis
- Voucher usage statistics

### F. AI Assistant Chat
Natural language interface supporting Greek and English:
- "Ποια προϊόντα έχουν χαμηλό stock;"
- "Πόσες επιστροφές είχαμε αυτή την εβδομάδα;"
- "Ποιοι πελάτες ζήτησαν voucher τον τελευταίο μήνα;"
- "Ποιο SKU έχει τις περισσότερες ακυρώσεις;"
- "What's the revenue this month?"

## Tech Stack

- **Backend**: Python / FastAPI (async)
- **Database**: PostgreSQL with SQLAlchemy async ORM
- **Auth**: JWT tokens
- **AI**: OpenAI integration for advanced NLP
- **Deployment**: Railway / Vercel / AWS Lambda ready

## API Endpoints

| Group | Prefix | Description |
|-------|--------|-------------|
| Auth | `/api/v1/auth` | Login, token management |
| Shop | `/api/v1/shop` | Shop configuration |
| Products | `/api/v1/products` | Product CRUD & stock |
| Orders | `/api/v1/orders` | Order management |
| Returns | `/api/v1/returns` | Return workflow |
| Vouchers | `/api/v1/vouchers` | Voucher management |
| Customers | `/api/v1/customers` | Customer profiles |
| Shipping | `/api/v1/shipping` | Labels & logistics |
| Analytics | `/api/v1/analytics` | Business intelligence |
| Assistant | `/api/v1/assistant` | AI chat interface |
| Notifications | `/api/v1/notifications` | Notification log |

## Quick Start

```bash
cd backend
pip install -r requirements.txt
# Set DATABASE_URL and JWT_SECRET_KEY in .env
uvicorn main:app --reload --port 8000
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| DATABASE_URL | Yes | SQLite (dev) | PostgreSQL connection string |
| JWT_SECRET_KEY | Yes | change-me | JWT signing key |
| OPENAI_API_KEY | No | - | For advanced AI features |
| CORS_ALLOW_ORIGINS | No | localhost | Comma-separated origins |
| EMAIL_ENABLED | No | false | Enable email notifications |
| SMTP_HOST | No | - | SMTP server host |

## Part of Thronos Ecosystem

- **thronos-V3.6** - Core blockchain platform
- **thronos-verifyid** - KYC/Identity verification
- **thronos-commerce-assistant** - E-shop AI assistant (this)
- **skystriker** - Tour guide platform
