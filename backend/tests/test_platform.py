"""
Test Suite for Card-to-Crypto Platform
Tests for M1 parser, fraud detection, and conversion services
"""

import pytest
from decimal import Decimal
import asyncio


# ── M1 Parser Tests ───────────────────────────────────────────────────────────

class TestM1Parser:
    def setup_method(self):
        from app.services.m1_parser import M1Parser
        self.parser = M1Parser()

    def test_parse_valid_m1(self):
        m1 = "0110|000000|00000010000|840|123456|20240115120000|123456789012|AUTH123|00|TERM001|MERCH_001|4111111111111111=25121015432112345678|B4111111111111111^TEST^25121015|02|CITIBANK"
        result = self.parser.parse(m1)
        assert result.amount_fiat == 100.0
        assert result.currency_code == "USD"
        assert result.merchant_id == "MERCH_001"
        assert result.is_approved == True
        assert result.mti == "0110"
        assert result.authorization_code == "AUTH123"
        assert "TOK_" in result.card_token
        assert "1111" in result.card_masked
        assert "4111" not in result.card_token  # Raw PAN not in token display

    def test_parse_declined_transaction(self):
        m1 = "0110|000000|00000050000|840|999888|20240115130000|000111222333|AUTHXXX|05|TERM002|MERCH_002|5500005555555559=26011015432112345678|B5500005555555559^CARD/TEST^26011015|05|BANKOFTEST"
        result = self.parser.parse(m1)
        assert result.is_approved == False
        assert result.response_code == "05"
        assert result.amount_fiat == 500.0

    def test_card_tokenization_hides_pan(self):
        m1 = "0110|000000|00000010000|840|111111|20240115120000|111111111111|AUTH111|00|TERM001|MERCH_001|4111111111111111=25121015|B|02|BANK"
        result = self.parser.parse(m1)
        assert "4111111111111111" not in result.card_token
        assert result.card_masked.startswith("****")
        assert result.card_masked.endswith("1111")

    def test_parse_mastercard(self):
        m1 = "0110|000000|00000025000|840|222333|20240115150000|222333444555|AUTHMC1|00|TERMMC|MERCH_MC|5500005555555559=25121015|B|05|TESTBANK"
        result = self.parser.parse(m1)
        assert result.card_network == "MASTERCARD"

    def test_parse_visa(self):
        m1 = "0110|000000|00000010000|840|333444|20240115160000|333444555666|AUTHV01|00|TERMV1|MERCH_V1|4111111111111111=25121015|B|05|VISABANK"
        result = self.parser.parse(m1)
        assert result.card_network == "VISA"

    def test_amount_parsing(self):
        m1 = "0110|000000|00000199999|840|444555|20240115170000|444555666777|AUTHAMT|00|TERMA1|MERCH_A1|4111111111111111=25121015|B|05|BANK"
        result = self.parser.parse(m1)
        assert result.amount_fiat == 1999.99

    def test_missing_merchant_raises_error(self):
        from app.services.m1_parser import M1ParseError
        m1 = "0110|000000|00000010000|840|123456|20240115120000|123456789012|AUTH123|00|TERM001||4111111111111111=25121015|B|05|BANK"
        with pytest.raises(M1ParseError):
            self.parser.parse(m1)

    def test_invalid_format_raises_error(self):
        from app.services.m1_parser import M1ParseError
        with pytest.raises(M1ParseError):
            self.parser.parse("not-a-valid-m1-message")

    def test_eur_currency_mapping(self):
        m1 = "0110|000000|00000010000|978|555666|20240115180000|555666777888|AUTHEUR|00|TERME1|MERCH_E1|4111111111111111=25121015|B|05|EUROBANK"
        result = self.parser.parse(m1)
        assert result.currency_code == "EUR"

    def test_raw_hash_computed(self):
        m1 = "0110|000000|00000010000|840|123456|20240115120000|123456789012|AUTH123|00|TERM001|MERCH_001|4111111111111111=25121015|B|02|BANK"
        result = self.parser.parse(m1)
        assert len(result.raw_message_hash) == 64  # SHA256 hex

    def test_luhn_invalid_card_still_parsed(self):
        # Luhn-invalid PAN should be parsed but logged as warning
        m1 = "0110|000000|00000010000|840|123456|20240115120000|123456789012|AUTH123|00|TERM001|MERCH_001|4111111111111112=25121015|B|02|BANK"
        result = self.parser.parse(m1)  # Should not raise
        assert result.card_token is not None


# ── Fraud Detection Tests ──────────────────────────────────────────────────────

class TestFraudDetection:
    def setup_method(self):
        from app.services.fraud_service import FraudDetectionService, FraudDecision
        self.service = FraudDetectionService()
        self.FraudDecision = FraudDecision

    @pytest.mark.asyncio
    async def test_clean_transaction_approved(self):
        assessment = await self.service.assess_transaction(
            transaction_id="test-001",
            card_token="TOK_411111XXXXXX1111_ABCD1234",
            merchant_id="MERCH_001",
            amount_usd=150.00,
            currency_code="USD",
            card_network="VISA",
            pos_entry_mode="05",
            is_approved=True,
            transaction_hour=14,
        )
        assert assessment.decision == self.FraudDecision.APPROVE
        assert assessment.fraud_score < 40

    @pytest.mark.asyncio
    async def test_over_limit_blocked(self):
        assessment = await self.service.assess_transaction(
            transaction_id="test-002",
            card_token="TOK_411111XXXXXX1111_DCBA4321",
            merchant_id="MERCH_001",
            amount_usd=60000.00,  # Over 50k limit
            currency_code="USD",
            card_network="VISA",
            pos_entry_mode="05",
            is_approved=True,
            transaction_hour=14,
        )
        assert assessment.decision == self.FraudDecision.BLOCK
        assert assessment.fraud_score >= 70

    @pytest.mark.asyncio
    async def test_declined_transaction_flagged(self):
        assessment = await self.service.assess_transaction(
            transaction_id="test-003",
            card_token="TOK_411111XXXXXX9999_EFGH5678",
            merchant_id="MERCH_002",
            amount_usd=200.00,
            currency_code="USD",
            card_network="MASTERCARD",
            pos_entry_mode="05",
            is_approved=False,  # Declined
            transaction_hour=14,
        )
        # Declined transactions should get high score
        assert assessment.fraud_score >= 25

    @pytest.mark.asyncio
    async def test_large_amount_review(self):
        assessment = await self.service.assess_transaction(
            transaction_id="test-004",
            card_token="TOK_555500XXXXXX5559_IJKL9012",
            merchant_id="MERCH_003",
            amount_usd=12000.00,
            currency_code="USD",
            card_network="MASTERCARD",
            pos_entry_mode="05",
            is_approved=True,
            transaction_hour=10,
        )
        assert assessment.decision == self.FraudDecision.REVIEW

    @pytest.mark.asyncio
    async def test_manual_entry_flagged(self):
        assessment = await self.service.assess_transaction(
            transaction_id="test-005",
            card_token="TOK_378282XXXXXX3197_MNOP3456",
            merchant_id="MERCH_001",
            amount_usd=300.00,
            currency_code="USD",
            card_network="AMEX",
            pos_entry_mode="01",  # Manual entry
            is_approved=True,
            transaction_hour=11,
        )
        rule_ids = [s.rule_id for s in assessment.signals]
        assert "R08_MANUAL_ENTRY" in rule_ids


# ── Conversion Service Tests ──────────────────────────────────────────────────

class TestConversionService:
    def setup_method(self):
        from app.services.conversion_service import ConversionService
        self.service = ConversionService()

    @pytest.mark.asyncio
    async def test_usd_to_usdt_conversion(self):
        result = await self.service.calculate_conversion(
            fiat_amount=Decimal("100.00"),
            fiat_currency="USD",
            crypto_currency="USDT",
        )
        assert result.crypto_currency == "USDT"
        assert result.fiat_amount == Decimal("100.00")
        assert result.platform_fee_usd > 0
        assert result.net_fiat_amount < Decimal("100.00")
        assert result.crypto_amount > 0

    @pytest.mark.asyncio
    async def test_platform_fee_deducted(self):
        result = await self.service.calculate_conversion(
            fiat_amount=Decimal("1000.00"),
            fiat_currency="USD",
            crypto_currency="USDT",
        )
        # Fee should be 0.5% = $5.00
        expected_fee = Decimal("1000.00") * Decimal("0.005")
        assert abs(result.platform_fee_usd - expected_fee) < Decimal("0.01")

    @pytest.mark.asyncio
    async def test_unsupported_crypto_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            await self.service.calculate_conversion(
                fiat_amount=Decimal("100.00"),
                fiat_currency="USD",
                crypto_currency="DOGE",
            )

    @pytest.mark.asyncio
    async def test_below_minimum_raises(self):
        with pytest.raises(ValueError, match="minimum"):
            await self.service.calculate_conversion(
                fiat_amount=Decimal("0.50"),  # Below $1 minimum
                fiat_currency="USD",
                crypto_currency="USDT",
            )


# ── Security Tests ────────────────────────────────────────────────────────────

class TestSecurity:
    def test_tokenize_card_number(self):
        from app.core.security import tokenize_card_number, mask_card_number
        pan = "4111111111111111"
        token = tokenize_card_number(pan)
        assert pan not in token
        assert token.startswith("TOK_")
        assert "1111" in token  # Last 4 preserved

    def test_mask_card_number(self):
        from app.core.security import mask_card_number
        pan = "4111111111111111"
        masked = mask_card_number(pan)
        assert masked == "**** **** **** 1111"
        assert "4111111111111111" not in masked

    def test_encrypt_decrypt_roundtrip(self):
        from app.core.security import encrypt_sensitive_data, decrypt_sensitive_data
        original = "4111111111111111=2512101000000"
        encrypted = encrypt_sensitive_data(original)
        assert original not in encrypted
        decrypted = decrypt_sensitive_data(encrypted)
        assert decrypted == original

    def test_jwt_creation_and_validation(self):
        from app.core.security import create_access_token, decode_access_token
        payload = {"sub": "user-123", "email": "test@example.com", "role": "merchant"}
        token = create_access_token(payload)
        decoded = decode_access_token(token)
        assert decoded["sub"] == "user-123"
        assert decoded["role"] == "merchant"

    def test_password_hash_and_verify(self):
        from app.core.security import hash_password, verify_password
        password = "SecurePassword123!"
        hashed = hash_password(password)
        assert password != hashed
        assert verify_password(password, hashed)
        assert not verify_password("WrongPassword", hashed)

    def test_different_pans_get_different_tokens(self):
        from app.core.security import tokenize_card_number
        token1 = tokenize_card_number("4111111111111111")
        token2 = tokenize_card_number("5500005555555559")
        assert token1 != token2
