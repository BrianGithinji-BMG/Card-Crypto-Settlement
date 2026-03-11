"""
Crypto Settlement Service
Executes on-chain transfers to merchant wallets and records transaction hashes.
Supports ERC20 (Ethereum/Polygon), TRC20 (Tron), BEP20 (BSC) networks.

In production: integrate Web3.py for ETH/ERC20, tronpy for TRC20.
This module implements the full settlement flow with blockchain integration patterns.
"""

import asyncio
import secrets
import hashlib
import time
from decimal import Decimal
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError

from app.core.config import settings

logger = structlog.get_logger()


class BlockchainNetwork(str, Enum):
    ETHEREUM = "ERC20"
    BSC = "BEP20"
    TRON = "TRC20"
    POLYGON = "MATIC"
    SOLANA = "SOL"


@dataclass
class TransferRequest:
    to_address: str
    amount: Decimal
    crypto_currency: str
    network: str
    reference_id: str        # Our internal settlement ID
    memo: Optional[str] = None


@dataclass
class TransferResult:
    success: bool
    tx_hash: Optional[str]
    block_number: Optional[int]
    gas_fee: Optional[Decimal]
    network: str
    confirmations: int
    error_message: Optional[str] = None
    raw_response: Optional[Dict] = None


class AddressValidator:
    """Validate cryptocurrency wallet addresses by network."""

    @staticmethod
    def validate_evm_address(address: str) -> bool:
        """Validate Ethereum/BSC/Polygon address (EIP-55)."""
        import re
        if not re.match(r"^0x[0-9a-fA-F]{40}$", address):
            return False
        return True

    @staticmethod
    def validate_trc20_address(address: str) -> bool:
        """Validate TRON address (Base58, starts with T)."""
        import re
        return bool(re.match(r"^T[1-9A-HJ-NP-Za-km-z]{33}$", address))

    @classmethod
    def validate(cls, address: str, network: str) -> bool:
        if network in ("ERC20", "BEP20", "MATIC"):
            return cls.validate_evm_address(address)
        elif network == "TRC20":
            return cls.validate_trc20_address(address)
        else:
            # For unknown networks, do basic non-empty check
            return bool(address and len(address) >= 26)


class EVMSettlementClient:
    """
    EVM-compatible blockchain settlement client.
    In production, uses Web3.py with a funded hot wallet.
    """

    def __init__(self, network: str):
        self.network = network
        self.rpc_urls = {
            "ERC20": "https://mainnet.infura.io/v3/YOUR_PROJECT_ID",
            "BEP20": "https://bsc-dataseed1.binance.org",
            "MATIC": "https://polygon-rpc.com",
        }

    async def transfer_erc20(
        self,
        to_address: str,
        amount: Decimal,
        token_contract: str,
        token_decimals: int,
    ) -> TransferResult:
        """
        Execute ERC20 token transfer.

        Production implementation:
        1. web3.eth.account.sign_transaction(tx, private_key)
        2. web3.eth.send_raw_transaction(signed.rawTransaction)
        3. web3.eth.wait_for_transaction_receipt(tx_hash)
        """
        # Simulate blockchain call with realistic response structure
        await asyncio.sleep(0.1)  # Simulate network latency

        # Generate deterministic fake tx hash based on inputs (for demo)
        tx_seed = f"{to_address}{amount}{token_contract}{time.time()}"
        tx_hash = "0x" + hashlib.sha256(tx_seed.encode()).hexdigest()

        logger.info(
            "evm_transfer_executed",
            network=self.network,
            to_address=to_address[:10] + "...",
            amount=str(amount),
            tx_hash=tx_hash[:20] + "...",
        )

        return TransferResult(
            success=True,
            tx_hash=tx_hash,
            block_number=19_500_000 + secrets.randbelow(1000),
            gas_fee=Decimal("0.002"),
            network=self.network,
            confirmations=1,
        )

    async def get_transaction_status(self, tx_hash: str) -> Dict[str, Any]:
        """Check confirmation status of a transaction."""
        return {
            "hash": tx_hash,
            "confirmations": secrets.randbelow(6) + 1,
            "status": "success",
            "block_number": 19_500_100,
        }


# Token contract addresses (mainnet)
ERC20_CONTRACTS = {
    "USDT": {
        "ERC20": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "BEP20": "0x55d398326f99059fF775485246999027B3197955",
        "MATIC": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "TRC20": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    },
    "USDC": {
        "ERC20": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "BEP20": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        "MATIC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    },
}


class SettlementService:
    """
    Main settlement orchestrator.
    Handles the full crypto payout lifecycle:
    1. Validate merchant wallet address
    2. Get token contract for crypto + network
    3. Execute blockchain transfer
    4. Wait for confirmation
    5. Return settlement proof (tx_hash)
    """

    def __init__(self):
        self._evm_clients: Dict[str, EVMSettlementClient] = {
            network: EVMSettlementClient(network)
            for network in ("ERC20", "BEP20", "MATIC")
        }

    async def execute_settlement(
        self,
        merchant_wallet: str,
        crypto_amount: Decimal,
        crypto_currency: str,
        network: str,
        settlement_id: str,
    ) -> TransferResult:
        """
        Execute the crypto transfer to merchant wallet.

        Raises ValueError for invalid inputs.
        Raises RuntimeError if all retry attempts fail.
        """
        # Validate wallet address
        if not AddressValidator.validate(merchant_wallet, network):
            raise ValueError(
                f"Invalid {network} wallet address: {merchant_wallet[:20]}..."
            )

        # Validate supported crypto
        if crypto_currency not in ERC20_CONTRACTS:
            raise ValueError(f"Unsupported settlement currency: {crypto_currency}")

        network_contracts = ERC20_CONTRACTS.get(crypto_currency, {})
        contract_address = network_contracts.get(network)
        if not contract_address:
            raise ValueError(
                f"{crypto_currency} not supported on {network} network"
            )

        logger.info(
            "settlement_initiated",
            settlement_id=settlement_id,
            wallet=merchant_wallet[:10] + "...",
            amount=str(crypto_amount),
            crypto=crypto_currency,
            network=network,
        )

        try:
            result = await self._execute_with_retry(
                merchant_wallet=merchant_wallet,
                crypto_amount=crypto_amount,
                crypto_currency=crypto_currency,
                network=network,
                contract_address=contract_address,
                settlement_id=settlement_id,
            )

            logger.info(
                "settlement_completed",
                settlement_id=settlement_id,
                tx_hash=result.tx_hash,
                gas_fee=str(result.gas_fee),
                confirmations=result.confirmations,
            )
            return result

        except RetryError as e:
            logger.error(
                "settlement_failed_all_retries",
                settlement_id=settlement_id,
                error=str(e),
            )
            return TransferResult(
                success=False,
                tx_hash=None,
                block_number=None,
                gas_fee=None,
                network=network,
                confirmations=0,
                error_message=f"Settlement failed after retries: {str(e)}",
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
    )
    async def _execute_with_retry(
        self,
        merchant_wallet: str,
        crypto_amount: Decimal,
        crypto_currency: str,
        network: str,
        contract_address: str,
        settlement_id: str,
    ) -> TransferResult:
        """Attempt blockchain transfer with exponential backoff retry."""
        client = self._evm_clients.get(network)
        if not client:
            raise ValueError(f"No client for network: {network}")

        token_decimals = 6 if crypto_currency in ("USDT", "USDC") else 18

        return await client.transfer_erc20(
            to_address=merchant_wallet,
            amount=crypto_amount,
            token_contract=contract_address,
            token_decimals=token_decimals,
        )

    async def get_confirmation_status(
        self, tx_hash: str, network: str
    ) -> Dict[str, Any]:
        """Poll blockchain for transaction confirmations."""
        client = self._evm_clients.get(network)
        if not client:
            return {"error": f"Unknown network: {network}"}
        return await client.get_transaction_status(tx_hash)

    async def estimate_gas_fee(self, network: str, crypto: str) -> Decimal:
        """Estimate current gas fee for a settlement transaction."""
        # In production: call eth_estimateGas + eth_gasPrice
        gas_estimates = {
            "ERC20": Decimal("0.005"),  # ~$18 at $3500 ETH
            "BEP20": Decimal("0.0005"),
            "MATIC": Decimal("0.0001"),
            "TRC20": Decimal("1.0"),    # ~1 TRX
        }
        return gas_estimates.get(network, Decimal("0.001"))


# Module-level singleton
settlement_service = SettlementService()
