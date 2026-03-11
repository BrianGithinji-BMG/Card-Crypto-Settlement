"""
Database Models
Complete schema for card-to-crypto settlement platform
"""

from sqlalchemy import (
    Column, String, Numeric, Integer, Boolean, DateTime, ForeignKey,
    Enum, Text, JSON, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.core.database import Base


# ── Enums ─────────────────────────────────────────────────────────────────────

class TransactionStatus(str, enum.Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    PROCESSING = "PROCESSING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    CHARGEBACK = "CHARGEBACK"
    REVERSED = "REVERSED"


class SettlementStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONVERTING = "CONVERTING"
    TRANSFERRING = "TRANSFERRING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FraudStatus(str, enum.Enum):
    CLEAR = "CLEAR"
    REVIEW = "REVIEW"
    BLOCKED = "BLOCKED"


class CardNetwork(str, enum.Enum):
    VISA = "VISA"
    MASTERCARD = "MASTERCARD"
    AMEX = "AMEX"
    DISCOVER = "DISCOVER"
    UNKNOWN = "UNKNOWN"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MERCHANT = "merchant"
    ANALYST = "analyst"


# ── Models ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(Enum(UserRole), default=UserRole.MERCHANT, nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    mfa_enabled = Column(Boolean, default=False)
    mfa_secret = Column(String(64))
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    merchant = relationship("Merchant", back_populates="user", uselist=False)


class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    merchant_code = Column(String(20), unique=True, nullable=False, index=True)
    business_name = Column(String(255), nullable=False)
    business_type = Column(String(100))
    country_code = Column(String(3), nullable=False)
    currency_code = Column(String(3), default="USD")
    kyc_status = Column(String(20), default="PENDING")
    kyc_verified_at = Column(DateTime(timezone=True))
    aml_risk_level = Column(String(20), default="LOW")

    # Crypto wallet details
    crypto_wallet_address = Column(String(255))
    preferred_crypto = Column(String(20), default="USDT")
    crypto_network = Column(String(50), default="ERC20")

    # Limits
    daily_limit_usd = Column(Numeric(18, 2), default=50000)
    monthly_limit_usd = Column(Numeric(18, 2), default=500000)

    is_active = Column(Boolean, default=True)
    metadata_ = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="merchant")
    transactions = relationship("Transaction", back_populates="merchant")
    settlements = relationship("Settlement", back_populates="merchant")

    __table_args__ = (
        Index("ix_merchants_kyc_status", "kyc_status"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_transaction_id = Column(String(100), unique=True, nullable=False, index=True)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False)

    # Card data (tokenized / masked)
    card_token = Column(String(100), nullable=False, index=True)
    card_masked = Column(String(25))
    card_network = Column(Enum(CardNetwork), default=CardNetwork.UNKNOWN)
    card_expiry_month = Column(Integer)
    card_expiry_year = Column(Integer)
    issuing_bank = Column(String(100))
    issuing_country = Column(String(3))

    # Transaction amounts
    amount_fiat = Column(Numeric(18, 2), nullable=False)
    currency_code = Column(String(3), nullable=False, default="USD")
    amount_usd = Column(Numeric(18, 2))  # Normalized to USD

    # Authorization
    authorization_code = Column(String(50))
    response_code = Column(String(10))
    rrn = Column(String(50))  # Retrieval Reference Number
    stan = Column(String(20))  # System Trace Audit Number

    # M1 / ISO 8583 fields
    mti = Column(String(10))  # Message Type Indicator
    processing_code = Column(String(10))
    pos_entry_mode = Column(String(10))
    terminal_id = Column(String(20))
    m1_raw_hash = Column(String(64))  # SHA256 of original M1 message

    # Status tracking
    status = Column(Enum(TransactionStatus), default=TransactionStatus.PENDING, nullable=False)
    fraud_status = Column(Enum(FraudStatus), default=FraudStatus.CLEAR)
    fraud_score = Column(Numeric(5, 2), default=0.0)

    # Timestamps
    transaction_datetime = Column(DateTime(timezone=True))
    authorized_at = Column(DateTime(timezone=True))
    settled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    merchant = relationship("Merchant", back_populates="transactions")
    settlement = relationship("Settlement", back_populates="transaction", uselist=False)
    fraud_alerts = relationship("FraudAlert", back_populates="transaction")

    __table_args__ = (
        Index("ix_transactions_status", "status"),
        Index("ix_transactions_merchant_created", "merchant_id", "created_at"),
        Index("ix_transactions_card_token_created", "card_token", "created_at"),
    )


class Settlement(Base):
    __tablename__ = "settlements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(UUID(as_uuid=True), ForeignKey("transactions.id"), unique=True)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False)

    # Fiat side
    fiat_amount = Column(Numeric(18, 2), nullable=False)
    fiat_currency = Column(String(3), nullable=False, default="USD")
    platform_fee_usd = Column(Numeric(18, 6))
    net_fiat_amount = Column(Numeric(18, 6))

    # Crypto conversion
    crypto_currency = Column(String(20), nullable=False)
    crypto_amount = Column(Numeric(28, 10))
    exchange_rate = Column(Numeric(28, 10))
    exchange_rate_source = Column(String(50))  # "BINANCE" | "COINBASE"
    conversion_fee = Column(Numeric(18, 6))
    rate_locked_at = Column(DateTime(timezone=True))

    # Blockchain
    blockchain_tx_hash = Column(String(100), index=True)
    blockchain_network = Column(String(50))
    wallet_address = Column(String(255))
    block_number = Column(Integer)
    confirmations = Column(Integer, default=0)
    gas_fee = Column(Numeric(18, 8))

    status = Column(Enum(SettlementStatus), default=SettlementStatus.PENDING)

    initiated_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    transaction = relationship("Transaction", back_populates="settlement")
    merchant = relationship("Merchant", back_populates="settlements")

    __table_args__ = (
        Index("ix_settlements_status", "status"),
        Index("ix_settlements_merchant_created", "merchant_id", "created_at"),
    )


class FraudAlert(Base):
    __tablename__ = "fraud_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"))

    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)  # LOW | MEDIUM | HIGH | CRITICAL
    description = Column(Text)
    rule_triggered = Column(String(100))
    fraud_score = Column(Numeric(5, 2))
    is_resolved = Column(Boolean, default=False)
    resolved_by = Column(String(100))
    resolved_at = Column(DateTime(timezone=True))
    metadata_ = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    transaction = relationship("Transaction", back_populates="fraud_alerts")

    __table_args__ = (
        Index("ix_fraud_alerts_severity", "severity"),
        Index("ix_fraud_alerts_resolved", "is_resolved"),
    )


class ExchangeRateSnapshot(Base):
    __tablename__ = "exchange_rate_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    base_currency = Column(String(10), nullable=False)
    quote_currency = Column(String(10), nullable=False)
    rate = Column(Numeric(28, 10), nullable=False)
    source = Column(String(50))
    bid = Column(Numeric(28, 10))
    ask = Column(Numeric(28, 10))
    volume_24h = Column(Numeric(28, 4))
    captured_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_rate_snapshots_pair_time", "base_currency", "quote_currency", "captured_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(100), nullable=False)
    action = Column(String(50), nullable=False)
    actor_id = Column(String(100))
    actor_role = Column(String(50))
    changes = Column(JSONB, default={})
    ip_address = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_created", "created_at"),
    )
