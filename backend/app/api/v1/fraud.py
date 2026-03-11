"""Fraud Detection API Router"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.models import FraudAlert, Transaction
from app.schemas.schemas import FraudAlertResponse, FraudAlertResolve
from datetime import datetime, timezone

router = APIRouter()


@router.get("/alerts", response_model=list[FraudAlertResponse])
async def list_fraud_alerts(
    severity: Optional[str] = Query(default=None),
    resolved: Optional[bool] = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List fraud alerts with optional filters."""
    query = select(FraudAlert).order_by(desc(FraudAlert.created_at))
    if severity:
        query = query.where(FraudAlert.severity == severity.upper())
    if resolved is not None:
        query = query.where(FraudAlert.is_resolved == resolved)
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/alerts/{alert_id}/resolve", response_model=FraudAlertResponse)
async def resolve_fraud_alert(
    alert_id: UUID,
    resolution: FraudAlertResolve,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Mark a fraud alert as resolved."""
    result = await db.execute(select(FraudAlert).where(FraudAlert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.is_resolved = True
    alert.resolved_by = resolution.resolved_by
    alert.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return alert


@router.get("/stats")
async def fraud_statistics(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Fraud detection statistics summary."""
    from sqlalchemy import func
    result = await db.execute(
        select(
            FraudAlert.severity,
            func.count(FraudAlert.id).label("count")
        ).group_by(FraudAlert.severity)
    )
    by_severity = {row.severity: row.count for row in result.all()}

    unresolved = await db.execute(
        select(func.count(FraudAlert.id)).where(FraudAlert.is_resolved == False)
    )

    return {
        "by_severity": by_severity,
        "total_unresolved": unresolved.scalar() or 0,
        "severity_levels": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    }
