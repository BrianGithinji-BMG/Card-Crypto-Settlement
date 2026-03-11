"""
Fiat-to-Crypto Conversion Service
Integrates with Binance and Coinbase for real-time exchange rates
and executes conversions with best-price routing.
"""

import asyncio
import time
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, Tuple
import httpx
import hmac
import hashlib
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = structlog.get_logger()

# Supported crypto currencies and their minimum trade amounts (in USD)
SUPPORTED_CRYPTOS = {
    "USDT": {"min_usd": 1.0, "decimals": 6},
    "USDC": {"min_usd": 1.0, "decimals": 6},
    "BTC":  {"min_usd": 10.0, "decimals": 8},
    "ETH":  {"min_usd": 5.0, "decimals": 8},
    "BNB":  {"min_usd": 5.0, "decimals": 8},
}


class ExchangeRateResult:
    def __init__(
        self,
        crypto_currency: str,
        fiat_currency: str,
        rate: Decimal,
        bid: Decimal,
        ask: Decimal,
        source: str,
        volume_24h: Optional[Decimal] = None,
    ):
        self.crypto_currency = crypto_currency
        self.fiat_currency = fiat_currency
        self.rate = rate
        self.bid = bid
        self.ask = ask
        self.source = source
        self.volume_24h = volume_24h
        self.timestamp = time.time()

    def is_stale(self, max_age_seconds: int = 30) -> bool:
        return (time.time() - self.timestamp) > max_age_seconds


class ConversionResult:
    def __init__(
        self,
        fiat_amount: Decimal,
        fiat_currency: str,
        crypto_amount: Decimal,
        crypto_currency: str,
        exchange_rate: Decimal,
        platform_fee_usd: Decimal,
        net_fiat_amount: Decimal,
        source: str,
        conversion_fee: Decimal,
    ):
        self.fiat_amount = fiat_amount
        self.fiat_currency = fiat_currency
        self.crypto_amount = crypto_amount
        self.crypto_currency = crypto_currency
        self.exchange_rate = exchange_rate
        self.platform_fee_usd = platform_fee_usd
        self.net_fiat_amount = net_fiat_amount
        self.source = source
        self.conversion_fee = conversion_fee


class BinanceClient:
    """Binance REST API client for spot price queries."""

    BASE_URL = "https://api.binance.com"

    # Fiat-to-USDT rates (Binance uses USDT as bridge for fiat pairs)
    FIAT_TO_USDT = {
        "USD": Decimal("1.0"),
        "EUR": None,  # Will be fetched
        "GBP": None,
        "JPY": None,
    }

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key
        self.api_secret = api_secret
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=10.0,
            headers={"X-MBX-APIKEY": self.api_key} if self.api_key else {},
        )

    async def get_ticker_price(self, symbol: str) -> Optional[Dict]:
        """Get current price for a trading pair."""
        try:
            resp = await self._client.get("/api/v3/ticker/bookTicker", params={"symbol": symbol})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("binance_ticker_error", symbol=symbol, error=str(e))
            return None

    async def get_usd_to_crypto_rate(self, crypto: str) -> Optional[ExchangeRateResult]:
        """Get USD -> crypto conversion rate."""
        # Binance uses USDT as USD proxy
        symbol = f"{crypto}USDT"
        data = await self.get_ticker_price(symbol)
        if not data:
            return None

        try:
            bid = Decimal(str(data.get("bidPrice", 0)))
            ask = Decimal(str(data.get("askPrice", 0)))
            rate = (bid + ask) / Decimal("2")

            return ExchangeRateResult(
                crypto_currency=crypto,
                fiat_currency="USD",
                rate=rate,
                bid=bid,
                ask=ask,
                source="BINANCE",
            )
        except Exception as e:
            logger.error("binance_rate_parse_error", error=str(e))
            return None

    async def close(self):
        await self._client.aclose()


class CoinbaseClient:
    """Coinbase Advanced Trade API client."""

    BASE_URL = "https://api.coinbase.com"

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key
        self.api_secret = api_secret
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=10.0,
        )

    async def get_usd_to_crypto_rate(self, crypto: str) -> Optional[ExchangeRateResult]:
        """Get exchange rate from Coinbase prices endpoint."""
        try:
            resp = await self._client.get(
                f"/v2/prices/{crypto}-USD/spot",
                headers={"CB-ACCESS-KEY": self.api_key} if self.api_key else {},
            )
            resp.raise_for_status()
            data = resp.json()
            rate = Decimal(str(data["data"]["amount"]))

            return ExchangeRateResult(
                crypto_currency=crypto,
                fiat_currency="USD",
                rate=rate,
                bid=rate * Decimal("0.9995"),  # Approximate
                ask=rate * Decimal("1.0005"),
                source="COINBASE",
            )
        except Exception as e:
            logger.warning("coinbase_rate_error", crypto=crypto, error=str(e))
            return None

    async def close(self):
        await self._client.aclose()


# ── Fiat normalization (multi-currency support) ───────────────────────────────

# Hardcoded fallback rates relative to USD (refreshed from live API in production)
FIAT_USD_RATES = {
    "USD": Decimal("1.0"),
    "EUR": Decimal("1.08"),
    "GBP": Decimal("1.27"),
    "JPY": Decimal("0.0067"),
    "CHF": Decimal("1.11"),
    "AUD": Decimal("0.65"),
    "CAD": Decimal("0.74"),
    "KES": Decimal("0.0077"),
}


async def fiat_to_usd(amount: Decimal, currency: str) -> Decimal:
    """Convert any fiat amount to USD equivalent."""
    if currency == "USD":
        return amount
    rate = FIAT_USD_RATES.get(currency.upper())
    if rate is None:
        logger.warning("unknown_fiat_currency", currency=currency)
        return amount  # Fallback: assume 1:1
    return (amount * rate).quantize(Decimal("0.000001"))


# ── Main Conversion Service ───────────────────────────────────────────────────

class ConversionService:
    """
    Routes fiat-to-crypto conversions through best available exchange.
    Uses smart routing: picks lowest ask (best price for buyer) across exchanges.
    """

    def __init__(self):
        self._binance = BinanceClient(settings.BINANCE_API_KEY, settings.BINANCE_API_SECRET)
        self._coinbase = CoinbaseClient(settings.COINBASE_API_KEY, settings.COINBASE_API_SECRET)
        self._rate_cache: Dict[str, ExchangeRateResult] = {}
        self._platform_fee = Decimal(str(settings.SETTLEMENT_FEE_PERCENT)) / Decimal("100")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def get_best_rate(
        self,
        crypto_currency: str,
        fiat_currency: str = "USD",
    ) -> ExchangeRateResult:
        """
        Fetch rates from all exchanges and return the best available.
        Uses cache for recent rates (< 30s old).
        """
        cache_key = f"{fiat_currency}:{crypto_currency}"
        cached = self._rate_cache.get(cache_key)
        if cached and not cached.is_stale():
            logger.debug("rate_cache_hit", cache_key=cache_key)
            return cached

        # Fetch concurrently from both exchanges
        rates = await asyncio.gather(
            self._binance.get_usd_to_crypto_rate(crypto_currency),
            self._coinbase.get_usd_to_crypto_rate(crypto_currency),
            return_exceptions=True,
        )

        valid_rates = [r for r in rates if isinstance(r, ExchangeRateResult)]

        if not valid_rates:
            # Ultimate fallback: use hardcoded rates for demo mode
            logger.warning(
                "all_exchange_feeds_failed",
                crypto=crypto_currency,
                using_fallback=True,
            )
            rate = self._get_fallback_rate(crypto_currency)
            return ExchangeRateResult(
                crypto_currency=crypto_currency,
                fiat_currency=fiat_currency,
                rate=rate,
                bid=rate * Decimal("0.999"),
                ask=rate * Decimal("1.001"),
                source="FALLBACK",
            )

        # Choose best rate (lowest ask = best price for buying crypto)
        best = min(valid_rates, key=lambda r: r.ask)

        # If fiat is not USD, adjust rate
        if fiat_currency != "USD":
            usd_rate = FIAT_USD_RATES.get(fiat_currency, Decimal("1"))
            best.rate = best.rate * usd_rate
            best.bid = best.bid * usd_rate
            best.ask = best.ask * usd_rate

        self._rate_cache[cache_key] = best
        logger.info(
            "rate_fetched",
            crypto=crypto_currency,
            fiat=fiat_currency,
            rate=str(best.rate),
            source=best.source,
        )
        return best

    async def calculate_conversion(
        self,
        fiat_amount: Decimal,
        fiat_currency: str,
        crypto_currency: str,
    ) -> ConversionResult:
        """
        Calculate how much crypto the merchant receives after fees.

        Flow:
        1. Normalize fiat to USD
        2. Deduct platform fee
        3. Query best exchange rate
        4. Calculate crypto amount
        """
        if crypto_currency not in SUPPORTED_CRYPTOS:
            raise ValueError(f"Unsupported crypto currency: {crypto_currency}")

        config = SUPPORTED_CRYPTOS[crypto_currency]
        decimals = config["decimals"]

        # 1. Normalize to USD
        usd_amount = await fiat_to_usd(fiat_amount, fiat_currency)

        # 2. Validate minimum
        if float(usd_amount) < settings.MIN_SETTLEMENT_AMOUNT_USD:
            raise ValueError(
                f"Amount ${usd_amount} is below minimum ${settings.MIN_SETTLEMENT_AMOUNT_USD}"
            )

        # 3. Deduct platform fee
        platform_fee = (usd_amount * self._platform_fee).quantize(Decimal("0.000001"))
        net_usd = usd_amount - platform_fee

        # 4. Get best exchange rate
        rate_result = await self.get_best_rate(crypto_currency, "USD")

        # 5. Convert: crypto_amount = net_usd / rate_per_crypto
        quantize_str = Decimal("0." + "0" * decimals)
        crypto_amount = (net_usd / rate_result.rate).quantize(quantize_str, rounding=ROUND_DOWN)

        # Exchange slippage / conversion fee (estimated 0.1% of trade)
        conversion_fee = (net_usd * Decimal("0.001")).quantize(Decimal("0.000001"))

        logger.info(
            "conversion_calculated",
            fiat_amount=str(fiat_amount),
            fiat_currency=fiat_currency,
            usd_amount=str(usd_amount),
            platform_fee=str(platform_fee),
            net_usd=str(net_usd),
            crypto_currency=crypto_currency,
            crypto_amount=str(crypto_amount),
            exchange_rate=str(rate_result.rate),
            source=rate_result.source,
        )

        return ConversionResult(
            fiat_amount=fiat_amount,
            fiat_currency=fiat_currency,
            crypto_amount=crypto_amount,
            crypto_currency=crypto_currency,
            exchange_rate=rate_result.rate,
            platform_fee_usd=platform_fee,
            net_fiat_amount=net_usd,
            source=rate_result.source,
            conversion_fee=conversion_fee,
        )

    def _get_fallback_rate(self, crypto: str) -> Decimal:
        """Static fallback rates (for development/demo only)."""
        fallbacks = {
            "USDT": Decimal("1.0"),
            "USDC": Decimal("1.0"),
            "BTC":  Decimal("65000.0"),
            "ETH":  Decimal("3500.0"),
            "BNB":  Decimal("580.0"),
        }
        return fallbacks.get(crypto, Decimal("1.0"))

    async def close(self):
        await self._binance.close()
        await self._coinbase.close()


# Module-level singleton
conversion_service = ConversionService()
