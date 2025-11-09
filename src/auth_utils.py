"""Authentication utilities for password hashing, JWT tokens, and API keys.

This module provides core authentication functionality used by the auth API.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from uuid import UUID
import secrets
import hashlib

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from src.config import settings


# ============================================================================
# Password Hashing (using bcrypt directly)
# ============================================================================

def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password
    """
    # Convert password to bytes
    password_bytes = password.encode('utf-8')

    # Bcrypt has a max password length of 72 bytes, truncate if necessary
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]

    # Generate salt and hash
    salt = bcrypt.gensalt(rounds=settings.password_bcrypt_rounds)
    hashed = bcrypt.hashpw(password_bytes, salt)

    # Return as string
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against

    Returns:
        True if password matches, False otherwise
    """
    # Convert to bytes
    password_bytes = plain_password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]

    hashed_bytes = hashed_password.encode('utf-8')

    # Verify
    return bcrypt.checkpw(password_bytes, hashed_bytes)


# ============================================================================
# JWT Token Management
# ============================================================================

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Payload data to encode in token
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )

    return encoded_jwt


def create_refresh_token(data: Dict[str, Any]) -> str:
    """
    Create a JWT refresh token with longer expiration.

    Args:
        data: Payload data to encode in token

    Returns:
        Encoded JWT refresh token
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh"
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )

    return encoded_jwt


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT token.

    Args:
        token: JWT token to decode

    Returns:
        Decoded token payload

    Raises:
        InvalidTokenError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except InvalidTokenError:
        raise


def verify_token(token: str) -> Dict[str, Any]:
    """
    Verify and decode a JWT token (alias for decode_token).

    Args:
        token: JWT token to verify

    Returns:
        Decoded token payload

    Raises:
        InvalidTokenError: If token is invalid or expired
    """
    return decode_token(token)


def get_token_user_id(token: str) -> Optional[UUID]:
    """
    Extract user ID from a JWT token.

    Args:
        token: JWT token

    Returns:
        User UUID or None if invalid
    """
    try:
        payload = decode_token(token)
        user_id_str = payload.get("sub")
        if user_id_str:
            return UUID(user_id_str)
    except (InvalidTokenError, ValueError):
        pass

    return None


# ============================================================================
# Device API Key Management
# ============================================================================

def generate_api_key() -> str:
    """
    Generate a secure random API key for device authentication.

    Format: rushroster_<32-byte-hex>

    Returns:
        API key string
    """
    # Generate 32 random bytes (256 bits) for strong security
    random_bytes = secrets.token_bytes(32)
    key_hex = random_bytes.hex()

    return f"rushroster_{key_hex}"


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key using SHA-256 for storage.

    Args:
        api_key: Plain API key

    Returns:
        Hashed API key
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key_format(api_key: str) -> bool:
    """
    Verify that an API key has the correct format.

    Args:
        api_key: API key to verify

    Returns:
        True if format is valid, False otherwise
    """
    if not api_key.startswith("rushroster_"):
        return False

    # Check that the hex part is 64 characters (32 bytes)
    hex_part = api_key[11:]  # Remove "rushroster_" prefix
    return len(hex_part) == 64 and all(c in "0123456789abcdef" for c in hex_part)


# ============================================================================
# Token Validation Helpers
# ============================================================================

def validate_access_token(token: str) -> Dict[str, Any]:
    """
    Validate an access token and return its payload.

    Args:
        token: JWT access token

    Returns:
        Token payload

    Raises:
        ValueError: If token is invalid, expired, or wrong type
    """
    try:
        payload = decode_token(token)

        # Verify it's an access token
        if payload.get("type") != "access":
            raise ValueError("Invalid token type")

        return payload

    except InvalidTokenError as e:
        raise ValueError(f"Invalid token: {str(e)}")


def validate_refresh_token(token: str) -> Dict[str, Any]:
    """
    Validate a refresh token and return its payload.

    Args:
        token: JWT refresh token

    Returns:
        Token payload

    Raises:
        ValueError: If token is invalid, expired, or wrong type
    """
    try:
        payload = decode_token(token)

        # Verify it's a refresh token
        if payload.get("type") != "refresh":
            raise ValueError("Invalid token type")

        return payload

    except InvalidTokenError as e:
        raise ValueError(f"Invalid token: {str(e)}")
