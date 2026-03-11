"""Merchants API Router"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
import structlog

from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.models import Merchant, User
from app.schemas.schemas import MerchantResponse, MerchantUpdate

router = APIRouter()
logger = structlog.get_logger()


@router.get("/", response_model=list[MerchantResponse])
async def list_merchants(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    result = await db.execute(select(Merchant).where(Merchant.is_active == True))
    return result.scalars().all()


@router.get("/{merchant_id}", response_model=MerchantResponse)
async def get_merchant(
    merchant_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return merchant


@router.patch("/{merchant_id}", response_model=MerchantResponse)
async def update_merchant(
    merchant_id: UUID,
    updates: MerchantUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    for field, value in updates.model_dump(exclude_none=True).items():
        setattr(merchant, field, value)

    await db.commit()
    return merchant


@router.get("/{merchant_id}/wallet")
async def get_merchant_wallet(
    merchant_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return {
        "wallet_address": merchant.crypto_wallet_address,
        "preferred_crypto": merchant.preferred_crypto,
        "network": merchant.crypto_network,
    }
