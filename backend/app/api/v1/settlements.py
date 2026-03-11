"""Settlements API Router"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Settlement, SettlementStatus
from app.schemas.schemas import SettlementResponse
from app.services.conversion_service import conversion_service

router = APIRouter()


@router.get("/", response_model=list[SettlementResponse])
async def list_settlements(
    status: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    query = select(Settlement).order_by(desc(Settlement.created_at))
    if status:
        query = query.where(Settlement.status == SettlementStatus(status))
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/rates")
async def get_current_rates():
    """Get current fiat-to-crypto exchange rates."""
    rates = {}
    for crypto in ["USDT", "BTC", "ETH", "BNB"]:
        try:
            rate_result = await conversion_service.get_best_rate(crypto, "USD")
            rates[crypto] = {
                "rate": str(rate_result.rate),
                "bid": str(rate_result.bid),
                "ask": str(rate_result.ask),
                "source": rate_result.source,
            }
        except Exception:
            rates[crypto] = {"rate": "N/A", "source": "UNAVAILABLE"}
    return rates


@router.get("/{settlement_id}", response_model=SettlementResponse)
async def get_settlement(
    settlement_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Settlement).where(Settlement.id == settlement_id))
    settlement = result.scalar_one_or_none()
    if not settlement:
        raise HTTPException(status_code=404, detail="Settlement not found")
    return settlement
