"""Auth API Router"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import secrets
import structlog

from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, get_current_user
from app.models.models import User, Merchant, UserRole
from app.schemas.schemas import LoginRequest, TokenResponse, UserCreate, MerchantCreate, MerchantResponse
from app.core.config import settings

router = APIRouter()
logger = structlog.get_logger()


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user and return JWT access token."""
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    token = create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value,
    })

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(request: UserCreate, merchant_data: MerchantCreate, db: AsyncSession = Depends(get_db)):
    """Register new merchant account."""
    existing = await db.execute(select(User).where(User.email == request.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=request.email,
        hashed_password=hash_password(request.password),
        full_name=request.full_name,
        role=UserRole.MERCHANT,
    )
    db.add(user)
    await db.flush()

    merchant_code = f"M{secrets.token_hex(4).upper()}"
    merchant = Merchant(
        user_id=user.id,
        merchant_code=merchant_code,
        business_name=merchant_data.business_name,
        business_type=merchant_data.business_type,
        country_code=merchant_data.country_code,
        currency_code=merchant_data.currency_code,
        crypto_wallet_address=merchant_data.crypto_wallet_address,
        preferred_crypto=merchant_data.preferred_crypto,
        crypto_network=merchant_data.crypto_network,
    )
    db.add(merchant)
    await db.commit()

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": "merchant"})
    return TokenResponse(access_token=token, token_type="bearer", expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)


@router.get("/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    return current_user
