"""
Transactions API Router
Endpoints for M1 message ingestion, transaction queries, and status tracking
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional, List
from uuid import UUID
import structlog

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Transaction, Settlement, TransactionStatus, Merchant
from app.schemas.schemas import (
    M1SubmissionRequest, TransactionResponse, TransactionListResponse, SettlementResponse
)
from app.services.transaction_processor import transaction_processor, TransactionProcessingError

router = APIRouter()
logger = structlog.get_logger()


@router.post("/submit/m1", response_model=TransactionResponse, status_code=201)
async def submit_m1_transaction(
    request: M1SubmissionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    x_idempotency_key: Optional[str] = Header(None),
):
    """
    Submit a raw M1 transaction message for processing.
    
    The platform will:
    1. Parse the M1 message
    2. Run fraud detection
    3. Execute fiat-to-crypto conversion
    4. Settle the merchant in cryptocurrency
    
    Returns the processed transaction with settlement details.
    """
    idempotency_key = x_idempotency_key or request.idempotency_key

    # Check idempotency if key provided
    if idempotency_key:
        existing = await db.execute(
            select(Transaction).where(
                Transaction.external_transaction_id == idempotency_key
            )
        )
        existing_txn = existing.scalar_one_or_none()
        if existing_txn:
            logger.info("idempotent_request", key=idempotency_key)
            return await _build_transaction_response(existing_txn, db)

    try:
        transaction = await transaction_processor.process_m1_message(
            raw_m1=request.m1_message,
            db=db,
            submitted_by=current_user.get("user_id"),
        )
    except TransactionProcessingError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("transaction_submission_error", error=str(e))
        raise HTTPException(status_code=500, detail="Transaction processing failed")

    return await _build_transaction_response(transaction, db)


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get transaction details by ID."""
    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    transaction = result.scalar_one_or_none()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Role-based access: merchants can only see their own transactions
    if current_user.get("role") == "merchant":
        merchant = await _get_user_merchant(current_user["user_id"], db)
        if merchant and transaction.merchant_id != merchant.id:
            raise HTTPException(status_code=403, detail="Access denied")

    return await _build_transaction_response(transaction, db)


@router.get("/", response_model=TransactionListResponse)
async def list_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    merchant_id: Optional[UUID] = Query(default=None),
    from_date: Optional[str] = Query(default=None),
    to_date: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List transactions with filtering and pagination."""
    query = select(Transaction).order_by(desc(Transaction.created_at))

    # Role-based filtering
    if current_user.get("role") == "merchant":
        merchant = await _get_user_merchant(current_user["user_id"], db)
        if merchant:
            query = query.where(Transaction.merchant_id == merchant.id)
        else:
            return TransactionListResponse(items=[], total=0, page=page, page_size=page_size, pages=0)
    elif merchant_id:
        query = query.where(Transaction.merchant_id == merchant_id)

    if status:
        try:
            query = query.where(Transaction.status == TransactionStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    transactions = result.scalars().all()

    items = []
    for txn in transactions:
        items.append(await _build_transaction_response(txn, db))

    return TransactionListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, -(-total // page_size)),
    )


@router.get("/{transaction_id}/settlement", response_model=SettlementResponse)
async def get_transaction_settlement(
    transaction_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get settlement details for a transaction."""
    from app.models.models import Settlement
    result = await db.execute(
        select(Settlement).where(Settlement.transaction_id == transaction_id)
    )
    settlement = result.scalar_one_or_none()
    if not settlement:
        raise HTTPException(status_code=404, detail="Settlement not found")
    return settlement


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _build_transaction_response(
    transaction: Transaction, db: AsyncSession
) -> TransactionResponse:
    """Build response model with optional settlement data."""
    from app.models.models import Settlement

    settlement_result = await db.execute(
        select(Settlement).where(Settlement.transaction_id == transaction.id)
    )
    settlement = settlement_result.scalar_one_or_none()

    data = {
        "id": transaction.id,
        "external_transaction_id": transaction.external_transaction_id,
        "merchant_id": transaction.merchant_id,
        "card_masked": transaction.card_masked,
        "card_network": transaction.card_network.value if transaction.card_network else "UNKNOWN",
        "amount_fiat": transaction.amount_fiat,
        "currency_code": transaction.currency_code,
        "status": transaction.status.value,
        "fraud_status": transaction.fraud_status.value if transaction.fraud_status else "CLEAR",
        "fraud_score": transaction.fraud_score or 0,
        "authorization_code": transaction.authorization_code,
        "transaction_datetime": transaction.transaction_datetime,
        "created_at": transaction.created_at,
        "settlement": settlement,
    }
    return TransactionResponse(**data)


async def _get_user_merchant(user_id: str, db: AsyncSession) -> Optional[Merchant]:
    from app.models.models import User
    result = await db.execute(
        select(Merchant).join(Merchant.user).where(
            User.id == user_id
        )
    )
    return result.scalar_one_or_none()
