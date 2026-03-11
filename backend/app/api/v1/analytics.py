"""Analytics API Router"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from decimal import Decimal
from typing import Optional
from datetime import datetime, timedelta, timezone

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Transaction, Settlement, FraudAlert, TransactionStatus, SettlementStatus
from app.schemas.schemas import DashboardStats, TransactionResponse

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Comprehensive dashboard statistics."""
    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)

    # Volume in last 24h
    vol_result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount_fiat), 0)).where(
            Transaction.created_at >= last_24h,
            Transaction.status == TransactionStatus.SETTLED
        )
    )
    volume_24h = vol_result.scalar() or Decimal("0")

    # Transaction counts
    total_result = await db.execute(
        select(func.count(Transaction.id)).where(Transaction.created_at >= last_24h)
    )
    total_24h = total_result.scalar() or 0

    # Pending settlements
    pending_result = await db.execute(
        select(func.count(Settlement.id)).where(
            Settlement.status.in_([SettlementStatus.PENDING, SettlementStatus.CONVERTING, SettlementStatus.TRANSFERRING])
        )
    )
    pending_settlements = pending_result.scalar() or 0

    # Fraud alerts
    fraud_result = await db.execute(
        select(func.count(FraudAlert.id)).where(
            FraudAlert.created_at >= last_24h,
            FraudAlert.is_resolved == False
        )
    )
    fraud_count = fraud_result.scalar() or 0

    # Recent transactions
    recent_result = await db.execute(
        select(Transaction).order_by(desc(Transaction.created_at)).limit(10)
    )
    recent_txns = recent_result.scalars().all()

    # Crypto breakdown
    crypto_result = await db.execute(
        select(Settlement.crypto_currency, func.coalesce(func.sum(Settlement.crypto_amount), 0))
        .where(Settlement.status == SettlementStatus.COMPLETED)
        .group_by(Settlement.crypto_currency)
    )
    crypto_breakdown = {row[0]: str(row[1]) for row in crypto_result.all()}

    return {
        "live_transactions_count": total_24h,
        "pending_settlements": pending_settlements,
        "total_volume_24h_usd": str(volume_24h),
        "fraud_alerts_24h": fraud_count,
        "recent_transactions": [
            {
                "id": str(t.id),
                "card_masked": t.card_masked,
                "amount_fiat": str(t.amount_fiat),
                "currency": t.currency_code,
                "status": t.status.value,
                "fraud_status": t.fraud_status.value if t.fraud_status else "CLEAR",
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in recent_txns
        ],
        "settlement_breakdown": crypto_breakdown,
    }


@router.get("/summary")
async def get_analytics_summary(
    period: str = Query(default="7d", pattern=r"^(1d|7d|30d|90d)$"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Analytics summary for a time period."""
    days = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}[period]
    since = datetime.now(timezone.utc) - timedelta(days=days)

    total_result = await db.execute(
        select(func.count(Transaction.id), func.coalesce(func.sum(Transaction.amount_fiat), 0))
        .where(Transaction.created_at >= since)
    )
    count, volume = total_result.one()

    settled_result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount_fiat), 0))
        .where(Transaction.created_at >= since, Transaction.status == TransactionStatus.SETTLED)
    )
    settled_volume = settled_result.scalar() or Decimal("0")

    return {
        "period": period,
        "total_transactions": count,
        "total_volume_usd": str(volume),
        "total_settled_usd": str(settled_volume),
        "success_rate": round(float(settled_volume) / max(float(volume), 1) * 100, 2),
    }
