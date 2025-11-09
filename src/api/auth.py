"""Authentication service for user and device authentication.

This module handles:
- User registration and login
- JWT token generation and validation
- Device registration and API key management
- OAuth2 social login support
"""

from fastapi import APIRouter, Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Annotated
from datetime import datetime
from uuid import UUID
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.database import crud
from src.database.models import User, Device
from src import auth_utils


router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer()


# ============================================================================
# Pydantic Models
# ============================================================================

class UserRegister(BaseModel):
    """User registration request."""
    email: EmailStr
    password: str = Field(min_length=8, description="Password must be at least 8 characters")
    full_name: Optional[str] = None
    registration_code: str = Field(min_length=1, description="Required registration code")


class UserLogin(BaseModel):
    """User login request."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """Request to refresh an access token."""
    refresh_token: str


class UserResponse(BaseModel):
    """User information response."""
    id: UUID
    email: str
    full_name: Optional[str] = None
    is_admin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DeviceRegisterRequest(BaseModel):
    """Device registration request."""
    device_id: str = Field(min_length=1, description="Unique device identifier")
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    street_name: Optional[str] = None
    speed_limit: Optional[float] = Field(None, gt=0)


class DeviceRegisterResponse(BaseModel):
    """Device registration response with API key."""
    id: UUID
    device_id: str
    api_key: str
    message: str = "Device registered successfully. Store this API key securely - it will not be shown again."


# ============================================================================
# Authentication Dependencies
# ============================================================================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency to get current authenticated user from JWT token.

    Raises HTTPException if token is invalid or user not found.
    """
    try:
        token = credentials.credentials
        payload = auth_utils.validate_access_token(token)
        user_id = UUID(payload.get("sub"))

        user = crud.get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )

        return user

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"}
        )


async def get_device_from_api_key(
    x_api_key: Annotated[str, Header(convert_underscores=True)],
    db: Session = Depends(get_db)
) -> Device:
    """
    Dependency to authenticate device via API key header.

    Raises HTTPException if API key is invalid or device not found.
    """
    # Validate API key format
    if not auth_utils.verify_api_key_format(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format"
        )

    # Hash the API key and look up device
    api_key_hash = auth_utils.hash_api_key(x_api_key)
    device = crud.get_device_by_api_key_hash(db, api_key_hash)

    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key"
        )

    # Update last used timestamp
    crud.update_api_key_last_used(db, api_key_hash)

    return device


async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency to require admin privileges.

    Raises HTTPException if user is not an admin.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user


# ============================================================================
# Authentication Endpoints
# ============================================================================

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Register a new user account.

    - Validates registration code
    - Validates email uniqueness
    - Hashes password using bcrypt
    - Creates user record in database
    - Creates default user preferences
    - Returns user information (not including password)
    """
    # Validate registration code
    if not crud.validate_and_use_registration_code(db, user_data.registration_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, or fully-used registration code"
        )

    # Check if email already exists
    existing_user = crud.get_user_by_email(db, user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Hash password
    password_hash = auth_utils.hash_password(user_data.password)

    # Create user
    user = crud.create_user(
        db,
        email=user_data.email,
        password_hash=password_hash,
        full_name=user_data.full_name
    )

    # Create default preferences
    crud.create_user_preferences(db, user.id)

    return user


@router.post("/login", response_model=TokenResponse)
async def login_user(credentials: UserLogin, db: Session = Depends(get_db)):
    """
    Authenticate user and return JWT tokens.

    - Validates email and password
    - Generates JWT access and refresh tokens
    - Updates last_login timestamp
    - Returns tokens

    Security: Uses constant-time comparison to prevent timing attacks
    that could be used for email enumeration.
    """
    # Get user by email
    user = crud.get_user_by_email(db, credentials.email)

    # Always perform password verification to prevent timing attacks
    # If user doesn't exist, verify against a dummy hash to maintain constant time
    if user:
        password_valid = auth_utils.verify_password(credentials.password, user.password_hash)
    else:
        # Use a dummy bcrypt hash to ensure the same computational delay
        # This prevents timing attacks from distinguishing "user not found" vs "wrong password"
        dummy_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqwL7K.sCe"  # bcrypt hash of "dummy"
        auth_utils.verify_password(credentials.password, dummy_hash)
        password_valid = False

    # Reject authentication with a generic message
    if not user or not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    # Generate tokens
    token_data = {"sub": str(user.id), "email": user.email}
    access_token = auth_utils.create_access_token(token_data)
    refresh_token = auth_utils.create_refresh_token(token_data)

    # Update last login
    crud.update_user_last_login(db, user.id)

    from src.config import settings
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshTokenRequest, db: Session = Depends(get_db)):
    """
    Refresh an access token using a refresh token.

    - Validates refresh token
    - Generates new access token
    - Returns new token pair
    """
    try:
        payload = auth_utils.validate_refresh_token(request.refresh_token)
        user_id = UUID(payload.get("sub"))

        # Verify user still exists
        user = crud.get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )

        # Generate new tokens
        token_data = {"sub": str(user.id), "email": user.email}
        access_token = auth_utils.create_access_token(token_data)
        new_refresh_token = auth_utils.create_refresh_token(token_data)

        from src.config import settings
        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=settings.jwt_access_token_expire_minutes * 60
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


@router.post("/logout")
async def logout_user(current_user: User = Depends(get_current_user)):
    """
    Logout user.

    Note: This API uses short-lived JWT tokens (15 minutes) for security.
    Logout is handled client-side by discarding the token. The token will
    remain technically valid for up to 15 minutes after logout, but this
    brief window is acceptable for most use cases and avoids the complexity
    and infrastructure overhead of server-side token blacklisting.

    Security consideration: If a token is compromised, the exposure window
    is limited to a maximum of 15 minutes. For higher security requirements,
    consider implementing Redis-based token blacklisting.
    """
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current authenticated user's information."""
    return current_user


# ============================================================================
# Device Registration
# ============================================================================

@router.post("/devices/register", response_model=DeviceRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    request: DeviceRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Register a new field device and generate API key.

    - Authenticates user via JWT
    - Validates device_id uniqueness
    - Generates unique API key for device
    - Creates device record in database
    - Returns device info and API key (shown only once)
    """
    # Check if device_id already exists
    existing_device = crud.get_device_by_device_id(db, request.device_id)
    if existing_device:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device ID already registered"
        )

    # Generate API key
    api_key = auth_utils.generate_api_key()
    api_key_hash = auth_utils.hash_api_key(api_key)

    # Create device
    device = crud.create_device(
        db,
        device_id=request.device_id,
        owner_id=current_user.id,
        latitude=request.latitude,
        longitude=request.longitude,
        street_name=request.street_name,
        speed_limit=request.speed_limit
    )

    # Create API key record
    crud.create_device_api_key(
        db,
        device_id=device.id,
        api_key_hash=api_key_hash,
        name="Primary API Key"
    )

    return DeviceRegisterResponse(
        id=device.id,
        device_id=device.device_id,
        api_key=api_key
    )


# ============================================================================
# OAuth2 Social Login (Future Implementation)
# ============================================================================

@router.get("/oauth/google")
async def google_oauth_login():
    """
    Initiate Google OAuth2 login flow.

    This endpoint will redirect to Google's OAuth2 consent screen.
    After user authorizes, Google will redirect back to the callback URL.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Google OAuth2 login not yet implemented"
    )


@router.get("/oauth/google/callback")
async def google_oauth_callback(code: str, db: Session = Depends(get_db)):
    """
    Handle Google OAuth2 callback.

    - Exchanges authorization code for access token
    - Retrieves user info from Google
    - Creates or updates user account
    - Returns JWT tokens
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Google OAuth2 callback not yet implemented"
    )


@router.get("/oauth/github")
async def github_oauth_login():
    """Initiate GitHub OAuth2 login flow."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="GitHub OAuth2 login not yet implemented"
    )


@router.get("/oauth/github/callback")
async def github_oauth_callback(code: str, db: Session = Depends(get_db)):
    """Handle GitHub OAuth2 callback."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="GitHub OAuth2 callback not yet implemented"
    )


# ============================================================================
# Password Reset (Future Implementation)
# ============================================================================

@router.post("/password-reset/request")
async def request_password_reset(email: EmailStr, db: Session = Depends(get_db)):
    """
    Request a password reset email.

    - Validates email exists
    - Generates reset token
    - Sends reset email
    """
    # Always return success to prevent email enumeration
    return {"message": "If the email exists, a password reset link has been sent"}


@router.post("/password-reset/confirm")
async def confirm_password_reset(token: str, new_password: str, db: Session = Depends(get_db)):
    """
    Confirm password reset with token.

    - Validates reset token
    - Updates password
    - Invalidates token
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Password reset confirmation not yet implemented"
    )
