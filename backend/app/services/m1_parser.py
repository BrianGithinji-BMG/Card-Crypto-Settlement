"""
M1 Transaction File Parser
Parses ISO 8583-inspired M1 card transaction messages.

M1 Format (pipe-delimited with field type identifiers):
MTI|processing_code|amount|currency|STAN|datetime|RRN|auth_code|
response_code|terminal_id|merchant_id|track2_equivalent|card_data|
pos_entry_mode|issuer_data

Example M1 message:
0110|000000|00000010000|840|123456|20240115120000|123456789012|AUTH123|
00|TERM001|MERCH_001|4111111111111111=25121015432112345678|
B4111111111111111^CARDHOLDER/TEST^2512101000000000000|02|CITIBANK
"""

import re
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import structlog

from app.core.security import (
    tokenize_card_number, mask_card_number, hash_track_data, encrypt_sensitive_data
)

logger = structlog.get_logger()


class M1ParseError(Exception):
    pass


class CardNetworkDetector:
    """Detect card network from BIN (first 6 digits)."""

    PATTERNS = {
        "VISA": re.compile(r"^4"),
        "MASTERCARD": re.compile(r"^5[1-5]|^2(?:2[2-9]|[3-6]\d|7[01])"),
        "AMEX": re.compile(r"^3[47]"),
        "DISCOVER": re.compile(r"^6(?:011|5\d{2})"),
    }

    @classmethod
    def detect(cls, card_number: str) -> str:
        cleaned = card_number.replace(" ", "").replace("-", "")
        for network, pattern in cls.PATTERNS.items():
            if pattern.match(cleaned):
                return network
        return "UNKNOWN"


@dataclass
class ParsedM1Transaction:
    """Structured result from M1 message parsing."""
    # Message metadata
    mti: str
    processing_code: str
    raw_message_hash: str

    # Card data (sanitized)
    card_token: str
    card_masked: str
    card_network: str
    card_expiry_month: Optional[int]
    card_expiry_year: Optional[int]
    track_data_hash: str          # Non-reversible hash of track data

    # Transaction amounts
    amount_fiat: float
    currency_code: str
    currency_numeric: str

    # Authorization fields
    authorization_code: Optional[str]
    response_code: str
    rrn: Optional[str]            # Retrieval Reference Number
    stan: Optional[str]           # System Trace Audit Number

    # Terminal / Merchant
    terminal_id: Optional[str]
    merchant_id: str
    pos_entry_mode: str

    # Issuer
    issuing_bank: Optional[str]

    # Status flags
    is_approved: bool
    transaction_datetime: Optional[datetime]

    # Raw encrypted fields (PCI compliant storage)
    encrypted_card_data: Optional[str] = None

    # Extra parsed fields
    extra: Dict[str, Any] = field(default_factory=dict)


# ISO 4217 numeric-to-alpha currency mapping (subset)
CURRENCY_MAP = {
    "840": "USD",
    "978": "EUR",
    "826": "GBP",
    "392": "JPY",
    "756": "CHF",
    "036": "AUD",
    "124": "CAD",
    "404": "KES",
}

# Response codes indicating approval
APPROVAL_CODES = {"00", "10", "11", "16", "87"}


class M1Parser:
    """
    Parses M1 transaction messages into structured data.

    Supports:
    - Pipe-delimited M1 text format
    - JSON-wrapped M1 messages
    - Partial field handling with graceful defaults
    """

    FIELD_COUNT = 15

    def parse(self, raw_message: str) -> ParsedM1Transaction:
        """
        Main entry point. Accepts raw M1 string or JSON-wrapped message.
        Always sanitizes card data per PCI DSS requirements.
        """
        try:
            # Compute hash of raw message BEFORE any processing
            raw_hash = hashlib.sha256(raw_message.encode()).hexdigest()

            # Clean up whitespace/newlines
            cleaned = raw_message.strip().replace("\n", "").replace("\r", "")

            # Parse fields
            fields = self._split_fields(cleaned)
            result = self._extract_fields(fields, raw_hash)

            logger.info(
                "m1_parsed",
                mti=result.mti,
                merchant_id=result.merchant_id,
                amount=result.amount_fiat,
                currency=result.currency_code,
                is_approved=result.is_approved,
                card_token=result.card_token,
            )

            return result

        except M1ParseError:
            raise
        except Exception as e:
            logger.error("m1_parse_error", error=str(e), raw_length=len(raw_message))
            raise M1ParseError(f"Failed to parse M1 message: {str(e)}") from e

    def _split_fields(self, message: str) -> list[str]:
        """Split M1 pipe-delimited fields."""
        parts = message.split("|")
        # Pad with empty strings if fields are missing
        while len(parts) < self.FIELD_COUNT:
            parts.append("")
        return parts

    def _extract_fields(self, fields: list[str], raw_hash: str) -> ParsedM1Transaction:
        """Extract and validate all M1 fields."""

        # Field 0: MTI (Message Type Indicator)
        mti = fields[0].strip() or "0100"

        # Field 1: Processing code
        processing_code = fields[1].strip() or "000000"

        # Field 2: Amount (in minor units, e.g., cents)
        raw_amount = fields[2].strip()
        amount_fiat = self._parse_amount(raw_amount)

        # Field 3: Currency (ISO 4217 numeric)
        currency_numeric = fields[3].strip() or "840"
        currency_code = CURRENCY_MAP.get(currency_numeric, currency_numeric)

        # Field 4: STAN
        stan = fields[4].strip() or None

        # Field 5: Transaction datetime (YYYYMMDDHHmmss)
        transaction_datetime = self._parse_datetime(fields[5].strip())

        # Field 6: RRN
        rrn = fields[6].strip() or None

        # Field 7: Authorization code
        auth_code = fields[7].strip() or None

        # Field 8: Response code
        response_code = fields[8].strip() or "05"
        is_approved = response_code in APPROVAL_CODES

        # Field 9: Terminal ID
        terminal_id = fields[9].strip() or None

        # Field 10: Merchant ID
        merchant_id = fields[10].strip()
        if not merchant_id:
            raise M1ParseError("Missing merchant_id in M1 message (field 10)")

        # Field 11: Track2 equivalent (contains PAN)
        track2 = fields[11].strip()
        pan, expiry_month, expiry_year = self._parse_track2(track2)

        # Field 12: Track1 data (may contain cardholder name)
        track1 = fields[12].strip()

        # Extract issuing bank from track1 if present
        issuing_bank = self._extract_issuer(fields[14].strip() if len(fields) > 14 else "")

        # Field 13: POS entry mode
        pos_entry_mode = fields[13].strip() or "00"

        # ── PCI DSS: Sanitize card data ───────────────────────────────────────
        if pan:
            card_token = tokenize_card_number(pan)
            card_masked = mask_card_number(pan)
            card_network = CardNetworkDetector.detect(pan)
            # Encrypt original track data for secure vault storage
            raw_track = f"{track1}|{track2}"
            encrypted_card_data = encrypt_sensitive_data(raw_track) if raw_track.strip("|") else None
            track_hash = hash_track_data(track2) if track2 else ""
        else:
            raise M1ParseError("No PAN found in M1 message")

        return ParsedM1Transaction(
            mti=mti,
            processing_code=processing_code,
            raw_message_hash=raw_hash,
            card_token=card_token,
            card_masked=card_masked,
            card_network=card_network,
            card_expiry_month=expiry_month,
            card_expiry_year=expiry_year,
            track_data_hash=track_hash,
            amount_fiat=amount_fiat,
            currency_code=currency_code,
            currency_numeric=currency_numeric,
            authorization_code=auth_code,
            response_code=response_code,
            rrn=rrn,
            stan=stan,
            terminal_id=terminal_id,
            merchant_id=merchant_id,
            pos_entry_mode=pos_entry_mode,
            issuing_bank=issuing_bank,
            is_approved=is_approved,
            transaction_datetime=transaction_datetime,
            encrypted_card_data=encrypted_card_data,
            extra={
                "track_hash": track_hash,
                "currency_numeric": currency_numeric,
            },
        )

    def _parse_amount(self, raw: str) -> float:
        """Parse amount from minor units (cents) to major units (dollars)."""
        if not raw:
            return 0.0
        try:
            # Remove any non-numeric characters
            numeric = re.sub(r"[^\d]", "", raw)
            # Assume last 2 digits are decimal (cents)
            return int(numeric) / 100.0
        except (ValueError, TypeError):
            raise M1ParseError(f"Invalid amount field: {raw!r}")

    def _parse_datetime(self, raw: str) -> Optional[datetime]:
        """Parse transaction datetime from YYYYMMDDHHmmss."""
        if not raw or len(raw) < 14:
            return None
        try:
            return datetime.strptime(raw[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _parse_track2(self, track2: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
        """
        Parse Track 2 equivalent data.
        Format: PAN=YYMM[service_code][discretionary_data]
        """
        if not track2:
            return None, None, None

        # Remove start/end sentinels if present
        cleaned = track2.strip().lstrip(";").rstrip("?")

        # Split on separator '='
        if "=" in cleaned:
            parts = cleaned.split("=", 1)
            pan = re.sub(r"[^\d]", "", parts[0])
            expiry_raw = parts[1][:4] if len(parts) > 1 else ""
            try:
                expiry_year = int("20" + expiry_raw[:2])
                expiry_month = int(expiry_raw[2:4])
                if expiry_month < 1 or expiry_month > 12:
                    expiry_month = None
                    expiry_year = None
            except (ValueError, IndexError):
                expiry_month = None
                expiry_year = None
        else:
            # Try extracting PAN as raw digits (16-19 digits)
            match = re.search(r"\d{13,19}", cleaned)
            pan = match.group(0) if match else None
            expiry_month = None
            expiry_year = None

        if pan and not self._luhn_check(pan):
            logger.warning("luhn_check_failed", pan_masked=f"****{pan[-4:] if len(pan) >= 4 else pan}")

        return pan, expiry_month, expiry_year

    def _luhn_check(self, card_number: str) -> bool:
        """Luhn algorithm validation."""
        digits = [int(d) for d in card_number]
        checksum = 0
        parity = len(digits) % 2
        for i, digit in enumerate(digits):
            if i % 2 == parity:
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        return checksum % 10 == 0

    def _extract_issuer(self, raw: str) -> Optional[str]:
        """Extract issuing bank name from metadata field."""
        if not raw:
            return None
        return raw.strip()[:100] or None


# Module-level singleton
m1_parser = M1Parser()
