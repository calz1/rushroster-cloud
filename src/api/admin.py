"""Admin API endpoints for managing users, devices, and events.

This module provides admin-only endpoints for managing the platform.
All endpoints require admin privileges.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from uuid import UUID
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.database import crud
from src.database.models import User, Device, SpeedEvent, RegistrationCode
from src.api.auth import get_admin_user, UserResponse


router = APIRouter(prefix="/admin", tags=["admin"])


# ============================================================================
# Pydantic Models
# ============================================================================

class UserListResponse(BaseModel):
    """User list item response."""
    id: UUID
    email: str
    full_name: Optional[str] = None
    is_admin: bool
    created_at: datetime
    last_login: Optional[datetime] = None
    device_count: int = 0

    model_config = {"from_attributes": True}


class DeviceListResponse(BaseModel):
    """Device list item response."""
    id: UUID
    device_id: str
    owner_email: str
    owner_id: UUID
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    street_name: Optional[str] = None
    speed_limit: Optional[float] = None
    is_active: bool
    share_community: bool
    registered_at: datetime
    last_sync: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SetAdminStatusRequest(BaseModel):
    """Request to change user admin status."""
    is_admin: bool


class AdminStatsResponse(BaseModel):
    """Admin dashboard statistics."""
    total_users: int
    admin_users: int
    total_devices: int
    active_devices: int
    total_events: int
    speeding_events: int


class RegistrationCodeResponse(BaseModel):
    """Registration code response."""
    id: UUID
    code: str
    max_uses: int
    current_uses: int
    is_active: bool
    created_at: datetime
    expires_at: Optional[datetime] = None
    created_by_id: Optional[UUID] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class CreateRegistrationCodeRequest(BaseModel):
    """Request to create a registration code."""
    code: str
    max_uses: int = 1
    expires_at: Optional[datetime] = None
    description: Optional[str] = None


class UpdateRegistrationCodeRequest(BaseModel):
    """Request to update a registration code."""
    max_uses: Optional[int] = None
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None
    description: Optional[str] = None


# ============================================================================
# User Management Endpoints
# ============================================================================

@router.get("/users", response_model=List[UserListResponse])
async def list_all_users(
    limit: int = 100,
    offset: int = 0,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get all users (admin only).

    Returns a list of all users with their basic information and device count.
    """
    users = crud.get_all_users(db, limit=limit, offset=offset)

    # Add device count for each user
    result = []
    for user in users:
        user_dict = UserListResponse.model_validate(user).model_dump()
        user_dict["device_count"] = len(crud.get_user_devices(db, user.id))
        result.append(UserListResponse(**user_dict))

    return result


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user_details(
    user_id: UUID,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific user (admin only).
    """
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user


@router.patch("/users/{user_id}/admin", response_model=UserResponse)
async def set_user_admin_status(
    user_id: UUID,
    request: SetAdminStatusRequest,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Set or remove admin privileges for a user (admin only).

    - Allows admin users to promote/demote other users
    - Cannot demote yourself (must be done by another admin)
    """
    # Prevent self-demotion
    if user_id == admin_user.id and not request.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove your own admin privileges"
        )

    user = crud.set_user_admin_status(db, user_id, request.is_admin)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Delete a user and all their data (admin only).

    - Deletes user account, devices, events, reports, and preferences
    - Cannot delete yourself (must be done by another admin)
    - This operation is irreversible
    """
    # Prevent self-deletion
    if user_id == admin_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )

    success = crud.delete_user(db, user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return None


# ============================================================================
# Device Management Endpoints
# ============================================================================

@router.get("/devices", response_model=List[DeviceListResponse])
async def list_all_devices(
    limit: int = 100,
    offset: int = 0,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get all devices from all users (admin only).

    Returns a list of all devices with owner information.
    """
    devices = crud.get_all_devices(db, limit=limit, offset=offset)

    # Add owner email to each device
    result = []
    for device in devices:
        device_dict = {
            "id": device.id,
            "device_id": device.device_id,
            "owner_id": device.owner_id,
            "owner_email": device.owner.email if device.owner else "Unknown",
            "latitude": device.latitude,
            "longitude": device.longitude,
            "street_name": device.street_name,
            "speed_limit": device.speed_limit,
            "is_active": device.is_active,
            "share_community": device.share_community,
            "registered_at": device.registered_at,
            "last_sync": device.last_sync
        }
        result.append(DeviceListResponse(**device_dict))

    return result


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: UUID,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Delete a device and all its data (admin only).

    - Deletes device, events, API keys, and reports
    - This operation is irreversible
    """
    success = crud.delete_device(db, device_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )

    return None


# ============================================================================
# Event Management Endpoints
# ============================================================================

@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: UUID,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Delete a specific speed event (admin only).

    This operation is irreversible.
    """
    event = db.get(SpeedEvent, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )

    db.delete(event)
    db.commit()

    return None


# ============================================================================
# Admin Dashboard Statistics
# ============================================================================

@router.get("/stats", response_model=AdminStatsResponse)
async def get_admin_stats(
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get admin dashboard statistics (admin only).

    Returns platform-wide statistics for the admin dashboard.
    """
    from sqlalchemy import select, func, and_

    # Count users
    total_users = db.scalar(select(func.count(User.id))) or 0
    admin_users = db.scalar(select(func.count(User.id)).where(User.is_admin == True)) or 0

    # Count devices
    total_devices = db.scalar(select(func.count(Device.id))) or 0
    active_devices = db.scalar(select(func.count(Device.id)).where(Device.is_active == True)) or 0

    # Count events
    total_events = db.scalar(select(func.count(SpeedEvent.id))) or 0
    speeding_events = db.scalar(select(func.count(SpeedEvent.id)).where(SpeedEvent.is_speeding == True)) or 0

    return AdminStatsResponse(
        total_users=total_users,
        admin_users=admin_users,
        total_devices=total_devices,
        active_devices=active_devices,
        total_events=total_events,
        speeding_events=speeding_events
    )


# ============================================================================
# Registration Code Management Endpoints
# ============================================================================

@router.get("/registration-codes", response_model=List[RegistrationCodeResponse])
async def list_registration_codes(
    limit: int = 100,
    offset: int = 0,
    include_inactive: bool = False,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get all registration codes (admin only).

    Returns a list of all registration codes with their usage information.
    """
    codes = crud.get_all_registration_codes(db, limit=limit, offset=offset, include_inactive=include_inactive)
    return codes


@router.post("/registration-codes", response_model=RegistrationCodeResponse, status_code=status.HTTP_201_CREATED)
async def create_registration_code(
    request: CreateRegistrationCodeRequest,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Create a new registration code (admin only).

    - Code must be unique
    - Can set max uses and expiration date
    - Optional description for tracking purposes
    """
    # Check if code already exists
    existing_code = crud.get_registration_code_by_code(db, request.code)
    if existing_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration code already exists"
        )

    code = crud.create_registration_code(
        db,
        code=request.code,
        max_uses=request.max_uses,
        expires_at=request.expires_at,
        created_by_id=admin_user.id,
        description=request.description
    )

    return code


@router.get("/registration-codes/{code_id}", response_model=RegistrationCodeResponse)
async def get_registration_code(
    code_id: UUID,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get details about a specific registration code (admin only).
    """
    code = db.get(RegistrationCode, code_id)
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration code not found"
        )
    return code


@router.patch("/registration-codes/{code_id}", response_model=RegistrationCodeResponse)
async def update_registration_code(
    code_id: UUID,
    request: UpdateRegistrationCodeRequest,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Update a registration code (admin only).

    - Can update max uses, active status, expiration date, and description
    - Cannot change the code itself or current uses count
    """
    update_data = {}
    if request.max_uses is not None:
        update_data["max_uses"] = request.max_uses
    if request.is_active is not None:
        update_data["is_active"] = request.is_active
    if request.expires_at is not None:
        update_data["expires_at"] = request.expires_at
    if request.description is not None:
        update_data["description"] = request.description

    code = crud.update_registration_code(db, code_id, **update_data)
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration code not found"
        )

    return code


@router.delete("/registration-codes/{code_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registration_code(
    code_id: UUID,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    Delete a registration code (admin only).

    This operation is irreversible.
    """
    success = crud.delete_registration_code(db, code_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration code not found"
        )

    return None
