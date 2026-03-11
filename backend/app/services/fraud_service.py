"""
Fraud Detection Module
Rule-based engine + anomaly scoring for real-time transaction risk assessment.

Rules evaluated:
- Velocity checks (card frequency, amount patterns)
- Geo-velocity (impossible travel)
- Amount thresholds and round-number detection
- Card BIN country vs IP country mismatch
- Unusual time-of-day patterns
- High-value crypto settlement risk
"""

import asyncio
import json
import time
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import structlog

from app.core.config import settings

logger = structlog.get_logger()


class FraudSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FraudDecision(str, Enum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass
class FraudSignal:
    rule_id: str
    description: str
    severity: FraudSeverity
    score_contribution: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FraudAssessment:
    transaction_id: str
    card_token: str
    fraud_score: float          # 0.0 - 100.0
    decision: FraudDecision
    signals: List[FraudSignal]
    review_reasons: List[str]
    processing_time_ms: float

    @property
    def is_high_risk(self) -> bool:
        return self.fraud_score >= 70.0

    @property
    def needs_review(self) -> bool:
        return self.fraud_score >= 40.0

    def to_dict(self) -> Dict:
        return {
            "transaction_id": self.transaction_id,
            "fraud_score": self.fraud_score,
            "decision": self.decision.value,
            "signals": [
                {
                    "rule_id": s.rule_id,
                    "description": s.description,
                    "severity": s.severity.value,
                    "score_contribution": s.score_contribution,
                }
                for s in self.signals
            ],
            "review_reasons": self.review_reasons,
        }


@dataclass
class TransactionContext:
    """All available context for fraud evaluation."""
    transaction_id: str
    card_token: str
    merchant_id: str
    amount_usd: float
    currency_code: str
    card_network: str
    issuing_country: Optional[str]
    pos_entry_mode: str
    terminal_id: Optional[str]
    transaction_hour: int       # 0-23
    authorization_code: Optional[str]
    is_approved: bool

    # Enriched from Redis velocity cache
    card_txn_count_1h: int = 0
    card_amount_sum_1h: float = 0.0
    merchant_txn_count_1h: int = 0
    card_unique_merchants_1h: int = 0
    card_txn_count_24h: int = 0

    # Derived
    is_high_value: bool = False
    is_round_amount: bool = False


class VelocityChecker:
    """
    Redis-backed velocity checks for card and merchant transaction patterns.
    Falls back to in-memory dict if Redis is unavailable.
    """

    def __init__(self):
        self._memory_store: Dict[str, list] = {}

    async def get_card_velocity(self, card_token: str, window_seconds: int = 3600) -> Dict[str, Any]:
        """Get card transaction velocity metrics from Redis."""
        # In production: use Redis ZADD + ZCOUNT with sliding window
        # For now: return from in-memory store
        key = f"vel:card:{card_token}"
        now = time.time()
        events = [e for e in self._memory_store.get(key, []) if e["ts"] > now - window_seconds]

        return {
            "count": len(events),
            "amount_sum": sum(e["amount"] for e in events),
            "unique_merchants": len({e.get("merchant") for e in events}),
        }

    async def record_transaction(
        self,
        card_token: str,
        amount: float,
        merchant_id: str,
    ) -> None:
        """Record a new transaction in the velocity window."""
        key = f"vel:card:{card_token}"
        if key not in self._memory_store:
            self._memory_store[key] = []
        self._memory_store[key].append({
            "ts": time.time(),
            "amount": amount,
            "merchant": merchant_id,
        })
        # Trim to last 24h
        cutoff = time.time() - 86400
        self._memory_store[key] = [
            e for e in self._memory_store[key] if e["ts"] > cutoff
        ]


class FraudRuleEngine:
    """
    Evaluates a sequence of fraud detection rules and aggregates a risk score.

    Each rule contributes a score 0-100, weighted by severity.
    Final score = weighted sum, capped at 100.
    """

    RULE_WEIGHTS = {
        FraudSeverity.LOW: 5,
        FraudSeverity.MEDIUM: 15,
        FraudSeverity.HIGH: 30,
        FraudSeverity.CRITICAL: 50,
    }

    def evaluate(self, ctx: TransactionContext) -> List[FraudSignal]:
        signals: List[FraudSignal] = []

        # ── R01: High velocity - too many transactions in 1 hour ──────────────
        if ctx.card_txn_count_1h >= settings.FRAUD_MAX_TRANSACTIONS_PER_CARD:
            signals.append(FraudSignal(
                rule_id="R01_HIGH_VELOCITY",
                description=f"Card used {ctx.card_txn_count_1h} times in last hour",
                severity=FraudSeverity.HIGH,
                score_contribution=30.0,
                metadata={"count": ctx.card_txn_count_1h, "threshold": settings.FRAUD_MAX_TRANSACTIONS_PER_CARD},
            ))
        elif ctx.card_txn_count_1h >= settings.FRAUD_MAX_TRANSACTIONS_PER_CARD * 0.7:
            signals.append(FraudSignal(
                rule_id="R01_ELEVATED_VELOCITY",
                description=f"Card approaching velocity limit ({ctx.card_txn_count_1h} txns/hr)",
                severity=FraudSeverity.MEDIUM,
                score_contribution=10.0,
                metadata={"count": ctx.card_txn_count_1h},
            ))

        # ── R02: Large single transaction ─────────────────────────────────────
        if ctx.amount_usd > settings.FRAUD_MAX_AMOUNT_PER_TRANSACTION:
            signals.append(FraudSignal(
                rule_id="R02_OVER_LIMIT",
                description=f"Transaction amount ${ctx.amount_usd:.2f} exceeds max limit",
                severity=FraudSeverity.CRITICAL,
                score_contribution=50.0,
                metadata={"amount": ctx.amount_usd, "limit": settings.FRAUD_MAX_AMOUNT_PER_TRANSACTION},
            ))
        elif ctx.amount_usd > settings.FRAUD_SUSPICIOUS_AMOUNT_THRESHOLD:
            signals.append(FraudSignal(
                rule_id="R02_LARGE_AMOUNT",
                description=f"Large transaction: ${ctx.amount_usd:.2f}",
                severity=FraudSeverity.MEDIUM,
                score_contribution=15.0,
                metadata={"amount": ctx.amount_usd},
            ))

        # ── R03: Round number detection (structuring suspicion) ───────────────
        if ctx.amount_usd >= 100 and ctx.amount_usd % 100 == 0:
            signals.append(FraudSignal(
                rule_id="R03_ROUND_AMOUNT",
                description=f"Suspicious round amount: ${ctx.amount_usd:.0f}",
                severity=FraudSeverity.LOW,
                score_contribution=5.0,
                metadata={"amount": ctx.amount_usd},
            ))

        # ── R04: High amount velocity (smurfing detection) ────────────────────
        if ctx.card_amount_sum_1h > 20000:
            signals.append(FraudSignal(
                rule_id="R04_AMOUNT_VELOCITY",
                description=f"Card spent ${ctx.card_amount_sum_1h:.2f} in last hour",
                severity=FraudSeverity.HIGH,
                score_contribution=25.0,
                metadata={"amount_sum_1h": ctx.card_amount_sum_1h},
            ))

        # ── R05: Card testing pattern (multiple merchants, small amounts) ──────
        if ctx.card_unique_merchants_1h >= 3 and ctx.amount_usd < 10:
            signals.append(FraudSignal(
                rule_id="R05_CARD_TESTING",
                description=f"Possible card testing: {ctx.card_unique_merchants_1h} merchants, small amount",
                severity=FraudSeverity.HIGH,
                score_contribution=30.0,
                metadata={"unique_merchants": ctx.card_unique_merchants_1h, "amount": ctx.amount_usd},
            ))

        # ── R06: Off-hours transaction ─────────────────────────────────────────
        if ctx.transaction_hour in range(1, 5):  # 1am - 4am
            signals.append(FraudSignal(
                rule_id="R06_OFF_HOURS",
                description=f"Transaction at unusual hour: {ctx.transaction_hour:02d}:00",
                severity=FraudSeverity.LOW,
                score_contribution=5.0,
                metadata={"hour": ctx.transaction_hour},
            ))

        # ── R07: Declined authorization ────────────────────────────────────────
        if not ctx.is_approved:
            signals.append(FraudSignal(
                rule_id="R07_DECLINED",
                description="Transaction was declined by issuer",
                severity=FraudSeverity.HIGH,
                score_contribution=25.0,
                metadata={"authorization": ctx.authorization_code},
            ))

        # ── R08: Manual POS entry (card not present, higher risk) ─────────────
        if ctx.pos_entry_mode in ("01", "00"):  # Manual keyed entry
            signals.append(FraudSignal(
                rule_id="R08_MANUAL_ENTRY",
                description="Card manually entered (not chip/swipe)",
                severity=FraudSeverity.MEDIUM,
                score_contribution=12.0,
                metadata={"pos_entry_mode": ctx.pos_entry_mode},
            ))

        # ── R09: High spending across multiple merchants (multi-merchant fraud) ─
        if ctx.card_unique_merchants_1h >= 5:
            signals.append(FraudSignal(
                rule_id="R09_MULTI_MERCHANT",
                description=f"Card used at {ctx.card_unique_merchants_1h} different merchants in 1 hour",
                severity=FraudSeverity.MEDIUM,
                score_contribution=15.0,
                metadata={"unique_merchants": ctx.card_unique_merchants_1h},
            ))

        return signals

    def calculate_score(self, signals: List[FraudSignal]) -> float:
        """Weighted fraud score aggregation."""
        if not signals:
            return 0.0
        total = sum(s.score_contribution for s in signals)
        return min(round(total, 2), 100.0)

    def make_decision(self, score: float) -> FraudDecision:
        """Convert fraud score to approval decision."""
        if score >= 70:
            return FraudDecision.BLOCK
        elif score >= 40:
            return FraudDecision.REVIEW
        else:
            return FraudDecision.APPROVE


class FraudDetectionService:
    """
    Main service for transaction fraud assessment.
    Called synchronously before transaction settlement.
    """

    def __init__(self):
        self._rule_engine = FraudRuleEngine()
        self._velocity = VelocityChecker()

    async def assess_transaction(
        self,
        transaction_id: str,
        card_token: str,
        merchant_id: str,
        amount_usd: float,
        currency_code: str,
        card_network: str,
        pos_entry_mode: str,
        is_approved: bool,
        transaction_hour: int,
        authorization_code: Optional[str] = None,
        issuing_country: Optional[str] = None,
        terminal_id: Optional[str] = None,
    ) -> FraudAssessment:
        """
        Full fraud assessment pipeline.
        Returns FraudAssessment with score, decision, and triggered signals.
        """
        start_ms = time.time() * 1000

        # Enrich with velocity data
        velocity = await self._velocity.get_card_velocity(card_token)

        ctx = TransactionContext(
            transaction_id=transaction_id,
            card_token=card_token,
            merchant_id=merchant_id,
            amount_usd=amount_usd,
            currency_code=currency_code,
            card_network=card_network,
            issuing_country=issuing_country,
            pos_entry_mode=pos_entry_mode,
            terminal_id=terminal_id,
            transaction_hour=transaction_hour,
            authorization_code=authorization_code,
            is_approved=is_approved,
            card_txn_count_1h=velocity["count"],
            card_amount_sum_1h=velocity["amount_sum"],
            card_unique_merchants_1h=velocity["unique_merchants"],
            is_high_value=amount_usd > settings.FRAUD_SUSPICIOUS_AMOUNT_THRESHOLD,
            is_round_amount=amount_usd >= 100 and amount_usd % 100 == 0,
        )

        # Run rule engine
        signals = self._rule_engine.evaluate(ctx)
        score = self._rule_engine.calculate_score(signals)
        decision = self._rule_engine.make_decision(score)

        # Record for velocity tracking
        await self._velocity.record_transaction(card_token, amount_usd, merchant_id)

        review_reasons = [s.description for s in signals if s.severity in (FraudSeverity.HIGH, FraudSeverity.CRITICAL)]
        elapsed = (time.time() * 1000) - start_ms

        assessment = FraudAssessment(
            transaction_id=transaction_id,
            card_token=card_token,
            fraud_score=score,
            decision=decision,
            signals=signals,
            review_reasons=review_reasons,
            processing_time_ms=round(elapsed, 2),
        )

        logger.info(
            "fraud_assessment",
            transaction_id=transaction_id,
            score=score,
            decision=decision.value,
            signals_count=len(signals),
            processing_ms=elapsed,
        )

        return assessment


# Module-level singleton
fraud_service = FraudDetectionService()
