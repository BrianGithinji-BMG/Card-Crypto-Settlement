"""
Application Configuration
Loads from environment variables with sensible defaults
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
import os


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────────
    ENVIRONMENT: str = Field(default="development")
    DEBUG: bool = Field(default=False)
    SECRET_KEY: str = Field(default="change-me-in-production-use-256-bit-key")
    API_KEY: str = Field(default="")
    JWT_SECRET_KEY: str = Field(default="your-jwt-secret-key-here")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./card_crypto.db"
    )
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    REDIS_CACHE_TTL: int = 300  # 5 minutes

    # ── Crypto Exchange APIs ──────────────────────────────────────────────────
    BINANCE_API_KEY: str = Field(default="")
    BINANCE_API_SECRET: str = Field(default="")
    BINANCE_SECRET_KEY: str = Field(default="")
    BINANCE_BASE_URL: str = "https://api.binance.com"

    COINBASE_API_KEY: str = Field(default="")
    COINBASE_API_SECRET: str = Field(default="")
    COINBASE_SECRET_KEY: str = Field(default="")
    COINBASE_BASE_URL: str = "https://api.coinbase.com"

    # ── Blockchain ───────────────────────────────────────────────────────────
    ETHEREUM_RPC_URL: str = Field(default="https://mainnet.infura.io/v3/YOUR_PROJECT_ID")
    BSC_RPC_URL: str = Field(default="https://bsc-dataseed.binance.org/")
    POLYGON_RPC_URL: str = Field(default="https://polygon-rpc.com/")
    TRON_RPC_URL: str = Field(default="https://api.trongrid.io")

    # ── Card Processing ───────────────────────────────────────────────────────
    CARD_TOKENIZATION_KEY: str = Field(default="tokenization-key-change-in-production")
    PCI_ENCRYPTION_KEY: str = Field(default="pci-encryption-key-32-bytes-long!")

    # ── Settlement ────────────────────────────────────────────────────────────
    DEFAULT_CRYPTO_CURRENCY: str = "USDT"
    SETTLEMENT_FEE_PERCENT: float = 0.5  # 0.5% platform fee
    PLATFORM_FEE_PERCENT: float = 0.5
    MIN_SETTLEMENT_AMOUNT_USD: float = 1.0

    # ── Fraud Detection ───────────────────────────────────────────────────────
    FRAUD_VELOCITY_WINDOW_SECONDS: int = 3600  # 1 hour
    FRAUD_MAX_TRANSACTIONS_PER_CARD: int = 10
    FRAUD_MAX_AMOUNT_PER_TRANSACTION: float = 50000.0
    MAX_TRANSACTION_AMOUNT: float = 50000.0
    FRAUD_SUSPICIOUS_AMOUNT_THRESHOLD: float = 10000.0
    FRAUD_VELOCITY_HOURS: int = 1
    FRAUD_AMOUNT_VELOCITY_HOURS: int = 1

    # ── Monitoring ────────────────────────────────────────────────────────────
    SENTRY_DSN: str = Field(default="")
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
