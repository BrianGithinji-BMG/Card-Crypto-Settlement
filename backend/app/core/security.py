"""
Security Module
JWT authentication, card tokenization, PCI-DSS encryption
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import hashlib
import hmac
import secrets
import structlog

from app.core.config import settings

logger = structlog.get_logger()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()

# ── Fernet symmetric encryption for PCI data ─────────────────────────────────
def _derive_fernet_key(raw_key: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"card-crypto-platform-salt-v1",
        iterations=100_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(raw_key.encode()))


_fernet = Fernet(_derive_fernet_key(settings.PCI_ENCRYPTION_KEY))


# ── Password Hashing ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT Tokens ────────────────────────────────────────────────────────────────

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> Dict[str, Any]:
    token = credentials.credentials
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    role = payload.get("role", "merchant")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return {"user_id": user_id, "role": role, "email": payload.get("email")}


async def require_admin(current_user: Dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def verify_api_key(api_key: str) -> bool:
    """Verify internal service API key using constant-time comparison."""
    expected = settings.SECRET_KEY
    return hmac.compare_digest(api_key.encode(), expected.encode())


# ── Card Data Tokenization (PCI DSS) ─────────────────────────────────────────

def tokenize_card_number(card_number: str) -> str:
    """
    Replace PAN with a non-reversible token.
    Format: TOK_<first6><last4><hash8>
    """
    cleaned = card_number.replace(" ", "").replace("-", "")
    first6 = cleaned[:6]
    last4 = cleaned[-4:]
    pan_hash = hashlib.sha256(
        (cleaned + settings.CARD_TOKENIZATION_KEY).encode()
    ).hexdigest()[:8].upper()
    return f"TOK_{first6}XXXXXX{last4}_{pan_hash}"


def mask_card_number(card_number: str) -> str:
    """Return masked PAN for display: **** **** **** 1234"""
    cleaned = card_number.replace(" ", "").replace("-", "")
    return f"**** **** **** {cleaned[-4:]}"


def encrypt_sensitive_data(plaintext: str) -> str:
    """Encrypt sensitive card data at rest (Fernet AES-128-CBC)."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_sensitive_data(ciphertext: str) -> str:
    """Decrypt sensitive card data."""
    return _fernet.decrypt(ciphertext.encode()).decode()


def generate_idempotency_key() -> str:
    """Generate a cryptographically secure idempotency key."""
    return secrets.token_urlsafe(32)


def hash_track_data(track_data: str) -> str:
    """One-way hash of track data for fraud matching without storing raw data."""
    return hashlib.sha256(
        (track_data + settings.CARD_TOKENIZATION_KEY).encode()
    ).hexdigest()
