"""
Pydantic Schemas
Request/response models for all API endpoints
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from enum import Enum


# ── Auth Schemas ──────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(..., pattern=r"^[^@]+@[^@]+\.[^@]+$")
    password: str = Field(..., min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserCreate(BaseModel):
    email: str = Field(..., pattern=r"^[^@]+@[^@]+\.[^@]+$")
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2, max_length=255)
    role: str = Field(default="merchant")


# ── Merchant Schemas ───────────────────────────────────────────────────────────

class MerchantCreate(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=255)
    business_type: Optional[str] = None
    country_code: str = Field(..., min_length=2, max_length=3)
    currency_code: str = Field(default="USD", min_length=3, max_length=3)
    crypto_wallet_address: Optional[str] = None
    preferred_crypto: str = Field(default="USDT")
    crypto_network: str = Field(default="ERC20")


class MerchantUpdate(BaseModel):
    business_name: Optional[str] = None
    crypto_wallet_address: Optional[str] = None
    preferred_crypto: Optional[str] = None
    crypto_network: Optional[str] = None
    daily_limit_usd: Optional[Decimal] = None


class MerchantResponse(BaseModel):
    id: UUID
    merchant_code: str
    business_name: str
    business_type: Optional[str]
    country_code: str
    kyc_status: str
    preferred_crypto: str
    crypto_network: str
    crypto_wallet_address: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Transaction Schemas ────────────────────────────────────────────────────────

class M1SubmissionRequest(BaseModel):
    """Raw M1 message submission."""
    m1_message: str = Field(..., min_length=10, description="Raw M1 pipe-delimited message")
    idempotency_key: Optional[str] = Field(None, max_length=100)

    @field_validator("m1_message")
    @classmethod
    def validate_m1_format(cls, v):
        if "|" not in v:
            raise ValueError("M1 message must be pipe-delimited")
        if len(v.split("|")) < 8:
            raise ValueError("M1 message has insufficient fields")
        return v


class TransactionSubmitRequest(BaseModel):
    """Structured transaction submission (alternative to raw M1)."""
    merchant_id: str = Field(..., min_length=3, max_length=50)
    amount: Decimal = Field(..., gt=0, le=1_000_000)
    currency: str = Field(..., min_length=3, max_length=3)
    card_token: str = Field(..., min_length=10)
    authorization_code: Optional[str] = None
    response_code: str = Field(default="00")
    terminal_id: Optional[str] = None
    pos_entry_mode: str = Field(default="05")


class TransactionResponse(BaseModel):
    id: UUID
    external_transaction_id: str
    merchant_id: UUID
    card_masked: Optional[str]
    card_network: str
    amount_fiat: Decimal
    currency_code: str
    status: str
    fraud_status: str
    fraud_score: Decimal
    authorization_code: Optional[str]
    transaction_datetime: Optional[datetime]
    created_at: datetime
    settlement: Optional["SettlementResponse"] = None

    class Config:
        from_attributes = True


class TransactionListResponse(BaseModel):
    items: List[TransactionResponse]
    total: int
    page: int
    page_size: int
    pages: int


# ── Settlement Schemas ─────────────────────────────────────────────────────────

class SettlementResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    fiat_amount: Decimal
    fiat_currency: str
    platform_fee_usd: Optional[Decimal]
    net_fiat_amount: Optional[Decimal]
    crypto_currency: str
    crypto_amount: Optional[Decimal]
    exchange_rate: Optional[Decimal]
    exchange_rate_source: Optional[str]
    blockchain_tx_hash: Optional[str]
    blockchain_network: Optional[str]
    wallet_address: Optional[str]
    status: str
    initiated_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Fraud Alert Schemas ────────────────────────────────────────────────────────

class FraudAlertResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    alert_type: str
    severity: str
    description: Optional[str]
    rule_triggered: Optional[str]
    fraud_score: Optional[Decimal]
    is_resolved: bool
    created_at: datetime

    class Config:
        from_attributes = True


class FraudAlertResolve(BaseModel):
    resolved_by: str = Field(..., min_length=2)
    resolution_note: Optional[str] = None


# ── Analytics Schemas ──────────────────────────────────────────────────────────

class AnalyticsSummary(BaseModel):
    period: str
    total_transactions: int
    total_volume_usd: Decimal
    total_settled_usd: Decimal
    total_crypto_settled: Dict[str, Decimal]  # {"USDT": 1234.56, "BTC": 0.5}
    fraud_blocked_count: int
    fraud_review_count: int
    success_rate: float
    avg_transaction_usd: Decimal
    top_currencies: List[Dict[str, Any]]


class DashboardStats(BaseModel):
    live_transactions_count: int
    pending_settlements: int
    total_volume_24h_usd: Decimal
    fraud_alerts_24h: int
    conversion_rate_btc: Optional[Decimal]
    conversion_rate_eth: Optional[Decimal]
    conversion_rate_usdt: Optional[Decimal]
    recent_transactions: List[TransactionResponse]
    settlement_breakdown: Dict[str, Any]


# Allow forward reference resolution
TransactionResponse.model_rebuild()
