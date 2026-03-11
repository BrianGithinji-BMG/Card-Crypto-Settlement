# Card-to-Crypto Payment Settlement Platform

A production-grade system that receives card transactions (ISO 8583 / M1 format), processes them in real-time, converts the fiat value to cryptocurrency, and settles merchants on-chain.

---

## Architecture Overview

```
POS Terminal → M1 Message → FastAPI Backend
                               │
                    ┌──────────┼──────────────┐
                    ▼          ▼              ▼
              M1 Parser   Fraud Engine   Auth/JWT
                    │
                    ▼
            Transaction DB (PostgreSQL)
                    │
                    ▼
          Fiat→Crypto Conversion
          (Binance + Coinbase API)
                    │
                    ▼
        Blockchain Settlement (ERC20/BEP20/TRC20)
                    │
                    ▼
        Merchant Wallet ← TX Hash Recorded
```

---

## Key Components

### 1. M1 Transaction Parser (`app/services/m1_parser.py`)
- Parses ISO 8583-inspired pipe-delimited M1 messages
- Extracts: PAN, expiry, amount, currency, STAN, RRN, auth code, terminal ID, merchant ID
- PCI DSS compliant: tokenizes PAN immediately, computes one-way hash for track data
- Detects card network via BIN (Visa, Mastercard, Amex, Discover)
- Validates amount in minor units → major units conversion
- Luhn algorithm validation

### 2. Fraud Detection Engine (`app/services/fraud_service.py`)
Rule-based scoring engine with 9 rules:

| Rule ID | Description | Severity |
|---------|-------------|----------|
| R01 | Velocity: card used >10x per hour | HIGH |
| R02 | Amount over $50,000 limit | CRITICAL |
| R03 | Round number detection | LOW |
| R04 | Amount velocity >$20k/hr | HIGH |
| R05 | Card testing pattern | HIGH |
| R06 | Off-hours (1am-4am) | LOW |
| R07 | Declined authorization | HIGH |
| R08 | Manual POS entry | MEDIUM |
| R09 | Multi-merchant spreading | MEDIUM |

Score → Decision: 0-39 APPROVE | 40-69 REVIEW | 70-100 BLOCK

### 3. Fiat-to-Crypto Conversion (`app/services/conversion_service.py`)
- Fetches rates from Binance + Coinbase concurrently
- Smart routing: picks lowest ask (best rate for platform)
- 30-second rate cache to prevent excessive API calls
- Supports: USDT, USDC, BTC, ETH, BNB
- Multi-currency fiat normalization (USD, EUR, GBP, JPY, etc.)
- Platform fee: 0.5% (configurable)

### 4. Crypto Settlement Service (`app/services/settlement_service.py`)
- EVM-compatible network support: ERC20, BEP20, Polygon
- TRON TRC20 support
- Address validation per network
- Exponential backoff retry (3 attempts)
- Records: tx_hash, block_number, gas_fee, confirmations
- Token contracts: USDT, USDC on all supported networks

### 5. Security (`app/core/security.py`)
- **Card tokenization**: PAN → `TOK_<first6>XXXXXX<last4>_<hash8>` (non-reversible)
- **PCI encryption**: Fernet AES-128-CBC for sensitive track data at rest
- **JWT**: HS256 tokens with role-based access (admin, merchant, analyst)
- **Password hashing**: bcrypt with work factor
- **Constant-time comparison**: for API key verification

---

## Project Structure

```
card-crypto-platform/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app, middleware
│   │   ├── core/
│   │   │   ├── config.py              # Pydantic settings
│   │   │   ├── database.py            # Async SQLAlchemy setup
│   │   │   └── security.py            # JWT, tokenization, encryption
│   │   ├── models/
│   │   │   └── models.py              # SQLAlchemy ORM models
│   │   ├── schemas/
│   │   │   └── schemas.py             # Pydantic request/response models
│   │   ├── services/
│   │   │   ├── m1_parser.py           # M1 message parser
│   │   │   ├── transaction_processor.py # Full payment orchestration
│   │   │   ├── conversion_service.py  # Fiat-to-crypto conversion
│   │   │   ├── settlement_service.py  # Blockchain transfer
│   │   │   └── fraud_service.py       # Rule-based fraud detection
│   │   └── api/v1/
│   │       ├── auth.py                # Login, register
│   │       ├── transactions.py        # M1 submission, queries
│   │       ├── merchants.py           # Merchant CRUD
│   │       ├── settlements.py         # Settlement records + rates
│   │       ├── analytics.py           # Dashboard stats
│   │       └── fraud.py               # Alert management
│   ├── tests/
│   │   └── test_platform.py           # Comprehensive test suite
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   └── src/
│       └── App.jsx                    # React dashboard
├── infrastructure/
│   └── nginx.conf                     # Reverse proxy + rate limiting
└── docker-compose.yml
```

---

## API Endpoints

### Authentication
```
POST /api/v1/auth/login          # Get JWT token
POST /api/v1/auth/register       # Register merchant account
GET  /api/v1/auth/me             # Current user info
```

### Transactions
```
POST /api/v1/transactions/submit/m1         # Submit M1 message
GET  /api/v1/transactions/                  # List transactions
GET  /api/v1/transactions/{id}              # Get transaction
GET  /api/v1/transactions/{id}/settlement   # Get settlement details
```

### Settlements
```
GET /api/v1/settlements/          # List settlements
GET /api/v1/settlements/rates     # Live crypto exchange rates
GET /api/v1/settlements/{id}      # Get settlement details
```

### Analytics
```
GET /api/v1/analytics/dashboard   # Dashboard stats
GET /api/v1/analytics/summary     # Period summary (1d/7d/30d/90d)
```

### Fraud
```
GET  /api/v1/fraud/alerts         # List fraud alerts
POST /api/v1/fraud/alerts/{id}/resolve   # Resolve alert
GET  /api/v1/fraud/stats          # Fraud statistics
```

---

## M1 Message Format

```
Field | Description              | Example
------|--------------------------|---------------------------
  0   | MTI                      | 0110
  1   | Processing Code          | 000000
  2   | Amount (minor units)     | 00000010000  (= $100.00)
  3   | Currency (ISO 4217)      | 840 (USD)
  4   | STAN                     | 123456
  5   | DateTime (YYYYMMDDHHmmss)| 20240115120000
  6   | RRN                      | 123456789012
  7   | Authorization Code       | AUTH123
  8   | Response Code            | 00 (approved)
  9   | Terminal ID              | TERM001
 10   | Merchant ID              | MERCH_001
 11   | Track 2 Equivalent       | 4111111111111111=25121015...
 12   | Track 1 Data             | B4111...^HOLDER^25121015
 13   | POS Entry Mode           | 05 (chip)
 14   | Issuing Bank             | CITIBANK
```

Example full message:
```
0110|000000|00000010000|840|123456|20240115120000|123456789012|AUTH123|00|TERM001|MERCH_001|4111111111111111=25121015432112345678|B4111111111111111^TEST^2512101000|05|CITIBANK
```

---

## Setup & Running

### Prerequisites
- Docker + Docker Compose
- Python 3.12+ (for local dev)
- Node.js 20+ (for frontend)

### Quick Start with Docker
```bash
cp backend/.env.example backend/.env
# Edit .env with your API keys

docker-compose up -d
```

Services will be available at:
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/api/docs
- Frontend Dashboard: http://localhost:3000

### Local Development
```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

### Running Tests
```bash
cd backend
pip install pytest pytest-asyncio
pytest tests/ -v
```

---

## Security & Compliance Notes

### PCI DSS Considerations
- Raw PANs are **never stored** in the database
- Track data is encrypted with AES before any persistence
- Tokenization is applied immediately on M1 parse
- All sensitive fields use Fernet symmetric encryption
- Audit logs track all entity changes

### AML/KYC
- Merchant onboarding requires KYC verification before settlement
- High-value transactions (>$10k) automatically flagged for review
- Round-number detection for structuring (smurfing) detection
- Velocity checks help detect money laundering patterns

### Chargeback Risk
- Card chargebacks vs. irreversible crypto transfers is a key risk
- **Mitigation**: Settlement delay window (configurable hold period)
- Chargeback reserves per merchant recommended
- Settlement to be held for chargeback dispute window (typically 60-120 days for some card networks)

### Regulatory
- Platform operates as a Virtual Asset Service Provider (VASP) in most jurisdictions
- Requires Money Services Business (MSB) registration in applicable countries
- Crypto settlement may trigger tax reporting obligations for merchants

---

## Production Deployment Checklist

- [ ] Replace all default keys in `.env` with cryptographically secure values
- [ ] Configure HSM or KMS for PCI encryption key management
- [ ] Set up Alembic migrations (replace `create_tables()` call)
- [ ] Configure proper Binance/Coinbase API keys with appropriate permissions
- [ ] Set up funded hot wallets for settlement execution
- [ ] Enable SSL/TLS on nginx (Let's Encrypt or certificate)
- [ ] Configure log aggregation (ELK stack or similar)
- [ ] Set up metrics (Prometheus + Grafana)
- [ ] Configure Sentry for error tracking
- [ ] Review and tune fraud rules for your merchant category
- [ ] Implement settlement delay/hold for chargeback protection
- [ ] Complete PCI DSS Level 1 assessment
- [ ] Register as VASP/MSB in required jurisdictions
