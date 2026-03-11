"""
Transaction Processing Engine
Orchestrates the full card-to-crypto payment flow:
1. Parse & validate
2. Fraud check
3. Store transaction
4. Execute fiat-to-crypto conversion
5. Trigger settlement
6. Record audit log
"""

import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from uuid import UUID
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import (
    Transaction, Settlement, Merchant, FraudAlert, AuditLog,
    TransactionStatus, SettlementStatus, FraudStatus, CardNetwork
)
from app.services.m1_parser import m1_parser, ParsedM1Transaction, M1ParseError
from app.services.conversion_service import conversion_service
from app.services.settlement_service import settlement_service
from app.services.fraud_service import fraud_service, FraudDecision
from app.core.config import settings

logger = structlog.get_logger()


class TransactionProcessingError(Exception):
    pass


class TransactionProcessor:
    """
    End-to-end transaction processing pipeline.
    Each step writes to the database so partial failures are recoverable.
    """

    async def process_m1_message(
        self,
        raw_m1: str,
        db: AsyncSession,
        submitted_by: Optional[str] = None,
    ) -> Transaction:
        """
        Process a raw M1 transaction message end-to-end.

        Returns the created/updated Transaction record.
        """
        # ── Step 1: Parse M1 ──────────────────────────────────────────────────
        try:
            parsed = m1_parser.parse(raw_m1)
        except M1ParseError as e:
            raise TransactionProcessingError(f"M1 parse error: {e}")

        # ── Step 2: Look up merchant ──────────────────────────────────────────
        merchant = await self._get_merchant(parsed.merchant_id, db)
        if not merchant:
            raise TransactionProcessingError(
                f"Merchant not found: {parsed.merchant_id}"
            )
        if not merchant.is_active:
            raise TransactionProcessingError(
                f"Merchant account inactive: {parsed.merchant_id}"
            )
        if merchant.kyc_status != "VERIFIED":
            raise TransactionProcessingError(
                f"Merchant KYC not verified: {parsed.merchant_id}"
            )

        # ── Step 3: Fraud Assessment ──────────────────────────────────────────
        txn_hour = (parsed.transaction_datetime or datetime.now(timezone.utc)).hour
        fraud_assessment = await fraud_service.assess_transaction(
            transaction_id=parsed.rrn or parsed.stan or "pending",
            card_token=parsed.card_token,
            merchant_id=parsed.merchant_id,
            amount_usd=parsed.amount_fiat,
            currency_code=parsed.currency_code,
            card_network=parsed.card_network,
            pos_entry_mode=parsed.pos_entry_mode,
            is_approved=parsed.is_approved,
            transaction_hour=txn_hour,
            authorization_code=parsed.authorization_code,
        )

        # ── Step 4: Create Transaction Record ─────────────────────────────────
        fraud_status = FraudStatus.CLEAR
        initial_status = TransactionStatus.PENDING

        if fraud_assessment.decision == FraudDecision.BLOCK:
            fraud_status = FraudStatus.BLOCKED
            initial_status = TransactionStatus.FAILED
        elif fraud_assessment.decision == FraudDecision.REVIEW:
            fraud_status = FraudStatus.REVIEW

        transaction = Transaction(
            external_transaction_id=parsed.rrn or parsed.stan or f"EXT_{parsed.raw_message_hash[:12]}",
            merchant_id=merchant.id,
            card_token=parsed.card_token,
            card_masked=parsed.card_masked,
            card_network=CardNetwork(parsed.card_network) if parsed.card_network in CardNetwork.__members__ else CardNetwork.UNKNOWN,
            card_expiry_month=parsed.card_expiry_month,
            card_expiry_year=parsed.card_expiry_year,
            issuing_bank=parsed.issuing_bank,
            amount_fiat=Decimal(str(parsed.amount_fiat)),
            currency_code=parsed.currency_code,
            amount_usd=Decimal(str(parsed.amount_fiat)),  # Simplified; use forex in prod
            authorization_code=parsed.authorization_code,
            response_code=parsed.response_code,
            rrn=parsed.rrn,
            stan=parsed.stan,
            mti=parsed.mti,
            processing_code=parsed.processing_code,
            pos_entry_mode=parsed.pos_entry_mode,
            terminal_id=parsed.terminal_id,
            m1_raw_hash=parsed.raw_message_hash,
            status=initial_status,
            fraud_status=fraud_status,
            fraud_score=Decimal(str(fraud_assessment.fraud_score)),
            transaction_datetime=parsed.transaction_datetime,
        )

        db.add(transaction)
        await db.flush()  # Get the UUID assigned

        # ── Step 5: Store Fraud Alerts ─────────────────────────────────────────
        for signal in fraud_assessment.signals:
            alert = FraudAlert(
                transaction_id=transaction.id,
                merchant_id=merchant.id,
                alert_type=signal.rule_id,
                severity=signal.severity.value,
                description=signal.description,
                rule_triggered=signal.rule_id,
                fraud_score=Decimal(str(signal.score_contribution)),
                metadata_=signal.metadata,
            )
            db.add(alert)

        # ── Step 6: Block if fraud detected ───────────────────────────────────
        if fraud_assessment.decision == FraudDecision.BLOCK:
            await db.commit()
            logger.warning(
                "transaction_blocked_fraud",
                transaction_id=str(transaction.id),
                fraud_score=fraud_assessment.fraud_score,
            )
            return transaction

        # ── Step 7: Verify authorization ──────────────────────────────────────
        if not parsed.is_approved:
            transaction.status = TransactionStatus.FAILED
            await db.commit()
            logger.info(
                "transaction_declined",
                transaction_id=str(transaction.id),
                response_code=parsed.response_code,
            )
            return transaction

        transaction.status = TransactionStatus.AUTHORIZED
        transaction.authorized_at = datetime.now(timezone.utc)
        await db.flush()

        # ── Step 8: Calculate Conversion ──────────────────────────────────────
        transaction.status = TransactionStatus.PROCESSING
        await db.flush()

        try:
            conversion = await conversion_service.calculate_conversion(
                fiat_amount=Decimal(str(parsed.amount_fiat)),
                fiat_currency=parsed.currency_code,
                crypto_currency=merchant.preferred_crypto or settings.DEFAULT_CRYPTO_CURRENCY,
            )
        except Exception as e:
            transaction.status = TransactionStatus.FAILED
            await db.commit()
            logger.error("conversion_error", error=str(e), transaction_id=str(transaction.id))
            raise TransactionProcessingError(f"Conversion failed: {e}")

        # ── Step 9: Create Settlement Record ──────────────────────────────────
        settlement = Settlement(
            transaction_id=transaction.id,
            merchant_id=merchant.id,
            fiat_amount=conversion.fiat_amount,
            fiat_currency=conversion.fiat_currency,
            platform_fee_usd=conversion.platform_fee_usd,
            net_fiat_amount=conversion.net_fiat_amount,
            crypto_currency=conversion.crypto_currency,
            crypto_amount=conversion.crypto_amount,
            exchange_rate=conversion.exchange_rate,
            exchange_rate_source=conversion.source,
            conversion_fee=conversion.conversion_fee,
            rate_locked_at=datetime.now(timezone.utc),
            wallet_address=merchant.crypto_wallet_address,
            blockchain_network=merchant.crypto_network or "ERC20",
            status=SettlementStatus.CONVERTING,
            initiated_at=datetime.now(timezone.utc),
        )
        db.add(settlement)
        await db.flush()

        # ── Step 10: Execute Blockchain Settlement ────────────────────────────
        if not merchant.crypto_wallet_address:
            settlement.status = SettlementStatus.FAILED
            transaction.status = TransactionStatus.FAILED
            await db.commit()
            raise TransactionProcessingError("Merchant has no wallet configured")

        settlement.status = SettlementStatus.TRANSFERRING

        transfer_result = await settlement_service.execute_settlement(
            merchant_wallet=merchant.crypto_wallet_address,
            crypto_amount=conversion.crypto_amount,
            crypto_currency=conversion.crypto_currency,
            network=merchant.crypto_network or "ERC20",
            settlement_id=str(settlement.id),
        )

        if transfer_result.success:
            settlement.blockchain_tx_hash = transfer_result.tx_hash
            settlement.block_number = transfer_result.block_number
            settlement.gas_fee = transfer_result.gas_fee
            settlement.confirmations = transfer_result.confirmations
            settlement.status = SettlementStatus.COMPLETED
            settlement.completed_at = datetime.now(timezone.utc)

            transaction.status = TransactionStatus.SETTLED
            transaction.settled_at = datetime.now(timezone.utc)
        else:
            settlement.status = SettlementStatus.FAILED
            transaction.status = TransactionStatus.FAILED
            logger.error(
                "settlement_failed",
                settlement_id=str(settlement.id),
                error=transfer_result.error_message,
            )

        # ── Step 11: Audit Log ─────────────────────────────────────────────────
        audit = AuditLog(
            entity_type="transaction",
            entity_id=str(transaction.id),
            action="process_payment",
            actor_id=submitted_by,
            actor_role="system",
            changes={
                "status": transaction.status.value,
                "fraud_score": float(transaction.fraud_score),
                "settlement_status": settlement.status.value,
                "tx_hash": transfer_result.tx_hash,
            },
        )
        db.add(audit)

        await db.commit()

        logger.info(
            "transaction_processed",
            transaction_id=str(transaction.id),
            status=transaction.status.value,
            merchant_id=parsed.merchant_id,
            amount_fiat=parsed.amount_fiat,
            crypto_amount=str(conversion.crypto_amount),
            crypto_currency=conversion.crypto_currency,
            tx_hash=transfer_result.tx_hash,
        )

        return transaction

    async def _get_merchant(
        self, merchant_code: str, db: AsyncSession
    ) -> Optional[Merchant]:
        result = await db.execute(
            select(Merchant).where(Merchant.merchant_code == merchant_code)
        )
        return result.scalar_one_or_none()


# Module-level singleton
transaction_processor = TransactionProcessor()
